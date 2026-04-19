import asyncio
import logging
import uuid
import os
from datetime import datetime
from typing import Optional

import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage

import requests

# ========================= КОНФИГУРАЦИЯ =========================
BOT_TOKEN = "8633169948:AAGNxJN0CseW6nLiS-FWhmAivjqM4jhxx44"
YOOMONEY_ACCESS_TOKEN = "4100118889570559.3288B2E716CEEB922A26BD6BEAC58648FBFB680CCF64E4E1447D714D6FB5EA5F01F1478FAC686BEF394C8A186C98982DE563C1ABCDF9F2F61D971B61DA3C7E486CA818F98B9E0069F1C0891E090DD56A11319D626A40F0AE8302A8339DED9EB7969617F191D93275F64C4127A3ECB7AED33FCDE91CA68690EB7534C67E6C219E"
YOOMONEY_WALLET = "4100118889570559"
ADMIN_ID = 8346538289  # ←←← ЗАМЕНИ НА СВОЙ ID
SUPPORT_USERNAME = "MetroShopSupport"  # ←←← Ник поддержки

# ================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, parse_mode="HTML")
dp = Dispatcher(storage=MemoryStorage())
os.makedirs("configs", exist_ok=True)

# ====================== FSM СОСТОЯНИЯ ======================
class AddConfig(StatesGroup):
    name = State()
    price = State()
    description = State()
    file = State()

# ====================== БАЗА ДАННЫХ ======================
async def init_db():
    """Инициализация базы данных"""
    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS configs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                price REAL NOT NULL,
                description TEXT,
                filename TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            
            CREATE TABLE IF NOT EXISTS payments (
                label TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL,
                username TEXT,
                config_id INTEGER NOT NULL,
                amount REAL NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                completed_at TEXT
            );
            
            CREATE TABLE IF NOT EXISTS purchases (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                username TEXT,
                config_id INTEGER NOT NULL,
                purchased_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
            CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);
        """)
        await db.commit()
    logger.info("✅ База данных инициализирована")

# ====================== КЛАВИАТУРЫ ======================
def main_menu() -> InlineKeyboardMarkup:
    """Главное меню пользователя"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛒 Купить VPN конфиг", callback_data="buy")],
        [InlineKeyboardButton(text="📦 Мои покупки", callback_data="my_purchases")],
        [InlineKeyboardButton(text="💡 Инструкция", callback_data="info"),
         InlineKeyboardButton(text="💬 Поддержка", url=f"https://t.me/{SUPPORT_USERNAME}")]
    ])

def admin_menu() -> InlineKeyboardMarkup:
    """Админ-панель"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить конфиг", callback_data="add_config")],
        [InlineKeyboardButton(text="📋 Список конфигов", callback_data="list_configs")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="stats")],
        [InlineKeyboardButton(text="💰 Последние платежи", callback_data="recent_payments")]
    ])

def back_button() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")]
    ])

# ====================== ОСНОВНЫЕ ХЕНДЛЕРЫ ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username or "Неизвестно"
    
    logger.info(f"👤 Новый пользователь: {username} (ID: {user_id})")
    
    welcome_text = (
        "🌐 <b>Добро пожаловать в WIXYEZ VPN!</b>\n\n"
        "🎮 Лучший сервис VPN-конфигов для <b>PUBG Mobile</b>\n\n"
        "⚡️ <b>Наши преимущества:</b>\n"
        "✅ Минимальный пинг для комфортной игры\n"
        "✅ Обход любых блокировок\n"
        "✅ Мгновенная автоматическая выдача\n"
        "✅ Поддержка 24/7\n"
        "✅ Стабильное соединение\n\n"
        "📱 Выберите действие ниже:"
    )
    
    await message.answer(welcome_text, reply_markup=main_menu())
    
    if user_id == ADMIN_ID:
        await message.answer("👑 <b>Режим администратора активирован</b>", reply_markup=admin_menu())

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Команда /admin"""
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ Доступ запрещён")
    
    await message.answer(
        "🛠 <b>Панель управления WIXYEZ VPN</b>\n\n"
        "Выберите нужное действие:",
        reply_markup=admin_menu()
    )

# ====================== ПОКУПКА ======================
@dp.callback_query(F.data == "buy")
async def show_configs(call: types.CallbackQuery):
    """Показать список доступных конфигов"""
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT id, name, price, description FROM configs ORDER BY price"
        ) as cursor:
            configs = await cursor.fetchall()

    if not configs:
        return await call.message.edit_text(
            "😔 <b>К сожалению, конфиги временно недоступны</b>\n\n"
            "Мы уже работаем над пополнением ассортимента.\n"
            "Попробуйте заглянуть позже!",
            reply_markup=back_button()
        )

    keyboard = []
    for config_id, name, price, _ in configs:
        keyboard.append([
            InlineKeyboardButton(
                text=f"⚡️ {name} — {int(price)}₽",
                callback_data=f"cfg_{config_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")])

    await call.message.edit_text(
        "🛒 <b>Доступные VPN-конфиги для PUBG Mobile</b>\n\n"
        "Выберите подходящий тариф:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("cfg_"))
async def show_config_details(call: types.CallbackQuery):
    """Показать детали конфига"""
    config_id = int(call.data.split("_")[1])

    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT name, price, description FROM configs WHERE id = ?",
            (config_id,)
        ) as cursor:
            config = await cursor.fetchone()

    if not config:
        return await call.answer("❌ Конфиг не найден", show_alert=True)

    name, price, description = config

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"💳 Оплатить {int(price)}₽", callback_data=f"pay_{config_id}")],
        [InlineKeyboardButton(text="◀️ К списку конфигов", callback_data="buy")]
    ])

    await call.message.edit_text(
        f"⚡️ <b>{name}</b>\n\n"
        f"📝 <b>Описание:</b>\n{description}\n\n"
        f"💰 <b>Стоимость:</b> {int(price)}₽\n\n"
        f"🎁 После оплаты конфиг придёт автоматически в течение 10 секунд!",
        reply_markup=kb
    )

@dp.callback_query(F.data.startswith("pay_"))
async def create_payment(call: types.CallbackQuery):
    """Создать платёж"""
    config_id = int(call.data.split("_")[1])
    user_id = call.from_user.id
    username = call.from_user.username or "Неизвестно"

    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT name, price FROM configs WHERE id = ?",
            (config_id,)
        ) as cursor:
            config = await cursor.fetchone()

    if not config:
        return await call.answer("❌ Ошибка загрузки конфига", show_alert=True)

    name, price = config
    label = str(uuid.uuid4())

    # Формируем URL для оплаты
    payment_url = (
        f"https://yoomoney.ru/quickpay/confirm?"
        f"receiver={YOOMONEY_WALLET}"
        f"&quickpay-form=shop"
        f"&targets=WIXYEZ VPN - {name}"
        f"&paymentType=SB"
        f"&sum={price}"
        f"&label={label}"
    )

    # Сохранение в базу
    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.execute(
            "INSERT INTO payments (label, user_id, username, config_id, amount, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (label, user_id, username, config_id, price, datetime.now().isoformat())
        )
        await db.commit()

    logger.info(f"💳 Создан платёж: {username} ({user_id}) - {name} - {price}₽ - Label: {label}")

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💳 Оплатить через ЮMoney", url=payment_url)],
        [InlineKeyboardButton(text="◀️ Отменить", callback_data=f"cfg_{config_id}")]
    ])

    await call.message.edit_text(
        f"✅ <b>Счёт успешно создан!</b>\n\n"
        f"📦 <b>Товар:</b> {name}\n"
        f"💰 <b>К оплате:</b> {int(price)}₽\n\n"
        f"🔹 Нажмите кнопку ниже для перехода к оплате\n"
        f"🔹 После успешной оплаты конфиг придёт автоматически\n"
        f"🔹 Обычно это занимает 5-15 секунд\n\n"
        f"⏱ <i>Срок действия счёта: 1 час</i>",
        reply_markup=kb
    )

# ====================== МОИ ПОКУПКИ ======================
@dp.callback_query(F.data == "my_purchases")
async def show_purchases(call: types.CallbackQuery):
    """Показать покупки пользователя"""
    user_id = call.from_user.id
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("""
            SELECT c.name, c.filename, p.purchased_at 
            FROM purchases p
            JOIN configs c ON p.config_id = c.id
            WHERE p.user_id = ?
            ORDER BY p.purchased_at DESC
        """, (user_id,)) as cursor:
            purchases = await cursor.fetchall()
    
    if not purchases:
        return await call.message.edit_text(
            "📦 <b>У вас пока нет покупок</b>\n\n"
            "🛒 Перейдите в раздел покупки, чтобы приобрести VPN-конфиг!\n\n"
            "⚡️ Быстрая автоматическая выдача\n"
            "💯 Гарантия качества",
            reply_markup=back_button()
        )
    
    keyboard = []
    for name, filename, _ in purchases:
        keyboard.append([
            InlineKeyboardButton(
                text=f"📥 Скачать: {name}",
                callback_data=f"download_{filename}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")])
    
    await call.message.edit_text(
        "📦 <b>Ваши покупки:</b>\n\n"
        "Вы можете скачать любой конфиг повторно в любое время.\n"
        "Нажмите на нужный файл:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("download_"))
async def download_config(call: types.CallbackQuery):
    """Скачать конфиг повторно"""
    filename = call.data.replace("download_", "")
    filepath = f"configs/{filename}"
    
    if not os.path.exists(filepath):
        return await call.answer("❌ Файл не найден на сервере", show_alert=True)
    
    await call.message.answer_document(
        FSInputFile(filepath),
        caption=(
            "📥 <b>Ваш VPN-конфиг</b>\n\n"
            "✅ Просто импортируйте файл в WireGuard\n"
            "🎮 Наслаждайтесь игрой без лагов!"
        )
    )
    await call.answer("✅ Конфиг отправлен")

# ====================== ИНФОРМАЦИЯ ======================
@dp.callback_query(F.data == "info")
async def show_info(call: types.CallbackQuery):
    """Показать информацию"""
    info_text = (
        "💡 <b>Как использовать конфиг?</b>\n\n"
        "<b>1️⃣ Скачайте VPN-клиент (WireGuard)</b>\n"
        "   • Android: Google Play\n"
        "   • iOS: App Store\n\n"
        "<b>2️⃣ Импортируйте полученный .conf файл</b>\n"
        "   • Откройте WireGuard\n"
        "   • Нажмите «+» или «Импорт из файла»\n"
        "   • Выберите скачанный .conf файл\n\n"
        "<b>3️⃣ Подключитесь к VPN</b>\n"
        "   • Активируйте переключатель\n"
        "   • Дождитесь подключения\n\n"
        "<b>4️⃣ Наслаждайтесь стабильной игрой!</b>\n"
        "   • Низкий пинг\n"
        "   • Без лагов\n"
        "   • Стабильное соединение\n\n"
        "━━━━━━━━━━━━━━━━━━━\n\n"
        "❓ <b>Проблемы с подключением?</b>\n"
        f"Напишите @{SUPPORT_USERNAME}\n"
        "Мы поможем в течение 5 минут!"
    )
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💬 Связаться с поддержкой", url=f"https://t.me/{SUPPORT_USERNAME}")],
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")]
    ])
    
    await call.message.edit_text(info_text, reply_markup=kb)

@dp.callback_query(F.data == "back_main")
async def back_to_main(call: types.CallbackQuery):
    """Вернуться в главное меню"""
    await call.message.edit_text(
        "🌐 <b>WIXYEZ VPN</b>\n\n"
        "🎮 Ваш надёжный помощник для PUBG Mobile\n\n"
        "📱 Выберите действие:",
        reply_markup=main_menu()
    )

# ====================== ПРОВЕРКА ПЛАТЕЖЕЙ ======================
async def check_payments_loop():
    """Фоновая проверка платежей через API"""
    logger.info("🔄 Запущена проверка платежей")
    
    while True:
        try:
            headers = {
                "Authorization": f"Bearer {YOOMONEY_ACCESS_TOKEN}",
                "Content-Type": "application/x-www-form-urlencoded"
            }
            
            response = requests.post(
                "https://yoomoney.ru/api/operation-history",
                headers=headers,
                data={"records": 50}
            )
            
            if response.status_code == 200:
                history = response.json()
                operations = history.get("operations", [])
                
                async with aiosqlite.connect("vpn_shop.db") as db:
                    for operation in operations:
                        if operation.get("status") != "success" or operation.get("direction") != "in":
                            continue
                        
                        label = operation.get("label")
                        if not label:
                            continue
                        
                        async with db.execute(
                            "SELECT user_id, config_id, amount FROM payments WHERE label = ? AND status = 'pending'",
                            (label,)
                        ) as cursor:
                            payment = await cursor.fetchone()
                        
                        if not payment:
                            continue
                        
                        user_id, config_id, amount = payment
                        
                        await db.execute(
                            "UPDATE payments SET status = 'succeeded', completed_at = ? WHERE label = ?",
                            (datetime.now().isoformat(), label)
                        )
                        
                        async with db.execute(
                            "SELECT username FROM payments WHERE label = ?", (label,)
                        ) as cur:
                            username = (await cur.fetchone())[0]
                        
                        await db.execute(
                            "INSERT INTO purchases (user_id, username, config_id, purchased_at) VALUES (?, ?, ?, ?)",
                            (user_id, username, config_id, datetime.now().isoformat())
                        )
                        await db.commit()
                        
                        async with db.execute(
                            "SELECT filename, name FROM configs WHERE id = ?",
                            (config_id,)
                        ) as cursor:
                            config = await cursor.fetchone()
                        
                        if config:
                            filename, conf_name = config
                            filepath = f"configs/{filename}"
                            
                            if os.path.exists(filepath):
                                try:
                                    await bot.send_document(
                                        user_id,
                                        FSInputFile(filepath),
                                        caption=(
                                            f"✅ <b>Оплата успешно получена!</b>\n\n"
                                            f"📦 <b>Ваш конфиг:</b> {conf_name}\n"
                                            f"💰 <b>Оплачено:</b> {int(amount)}₽\n\n"
                                            f"🎯 <b>Что дальше?</b>\n"
                                            f"1. Откройте WireGuard\n"
                                            f"2. Импортируйте этот файл\n"
                                            f"3. Подключитесь к VPN\n"
                                            f"4. Играйте без лагов!\n\n"
                                            f"🎮 <b>Приятной игры!</b>\n\n"
                                            f"💬 Вопросы? Пишите @{SUPPORT_USERNAME}"
                                        )
                                    )
                                    logger.info(f"✅ Выдан конфиг {conf_name} пользователю {user_id}")
                                    
                                    await bot.send_message(
                                        ADMIN_ID,
                                        f"💰 <b>Новая продажа!</b>\n\n"
                                        f"👤 Покупатель: @{username}\n"
                                        f"📦 Конфиг: {conf_name}\n"
                                        f"💵 Сумма: {int(amount)}₽"
                                    )
                                except Exception as e:
                                    logger.error(f"❌ Ошибка отправки конфига: {e}")
        
        except Exception as e:
            logger.error(f"❌ Ошибка проверки платежей: {e}")
        
        await asyncio.sleep(10)

# ====================== АДМИН-ПАНЕЛЬ ======================
@dp.callback_query(F.data == "add_config")
async def start_add_config(call: types.CallbackQuery, state: FSMContext):
    """Начать добавление конфига"""
    if call.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(AddConfig.name)
    await call.message.edit_text(
        "📝 <b>Добавление нового конфига</b>\n\n"
        "Введите название конфига:\n"
        "<i>Например: VPN EU Premium 🇪🇺</i>"
    )

@dp.message(AddConfig.name)
async def process_config_name(message: types.Message, state: FSMContext):
    """Обработка названия конфига"""
    await state.update_data(name=message.text)
    await state.set_state(AddConfig.price)
    await message.answer(
        "💰 <b>Установка цены</b>\n\n"
        "Введите стоимость в рублях:\n"
        "<i>Только число, например: 150</i>"
    )

@dp.message(AddConfig.price)
async def process_config_price(message: types.Message, state: FSMContext):
    """Обработка цены конфига"""
    try:
        price = float(message.text)
        if price <= 0:
            raise ValueError
        await state.update_data(price=price)
        await state.set_state(AddConfig.description)
        await message.answer(
            "📄 <b>Описание конфига</b>\n\n"
            "Введите подробное описание:\n"
            "<i>Например: Быстрый сервер в Европе, пинг 15-25ms, идеально для PUBG Mobile</i>"
        )
    except ValueError:
        await message.answer("❌ Введите корректную цену (число больше 0)")

@dp.message(AddConfig.description)
async def process_config_description(message: types.Message, state: FSMContext):
    """Обработка описания конфига"""
    await state.update_data(description=message.text)
    await state.set_state(AddConfig.file)
    await message.answer(
        "📎 <b>Загрузка файла конфига</b>\n\n"
        "Отправьте файл .conf:"
    )

@dp.message(AddConfig.file, F.document)
async def process_config_file(message: types.Message, state: FSMContext):
    """Сохранение конфига"""
    if not message.document.file_name.endswith(".conf"):
        return await message.answer("❌ Необходимо отправить файл с расширением .conf")

    data = await state.get_data()
    filename = f"{uuid.uuid4()}.conf"
    filepath = f"configs/{filename}"

    await bot.download(message.document, destination=filepath)

    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.execute(
            "INSERT INTO configs (name, price, description, filename, created_at) VALUES (?, ?, ?, ?, ?)",
            (data["name"], data["price"], data["description"], filename, datetime.now().isoformat())
        )
        await db.commit()

    await message.answer(
        f"✅ <b>Конфиг успешно добавлен!</b>\n\n"
        f"📦 Название: {data['name']}\n"
        f"💰 Цена: {int(data['price'])}₽\n"
        f"📝 Описание: {data['description']}\n\n"
        f"Конфиг уже доступен для покупки!",
        reply_markup=admin_menu()
    )
    await state.clear()
    logger.info(f"➕ Добавлен новый конфиг: {data['name']}")

@dp.callback_query(F.data == "list_configs")
async def list_all_configs(call: types.CallbackQuery):
    """Список всех конфигов"""
    if call.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("SELECT id, name, price, created_at FROM configs ORDER BY id DESC") as cursor:
            configs = await cursor.fetchall()

    if not configs:
        return await call.message.edit_text(
            "📋 <b>Список конфигов пуст</b>\n\n"
            "Добавьте первый конфиг!",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
            ])
        )

    text = "📋 <b>Все конфиги в магазине:</b>\n\n"
    for config_id, name, price, created_at in configs:
        text += f"🆔 <code>{config_id}</code> | {name} — {int(price)}₽\n"

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
        ])
    )

@dp.callback_query(F.data == "stats")
async def show_stats(call: types.CallbackQuery):
    """Показать статистику"""
    if call.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("SELECT COUNT(*) FROM purchases") as cursor:
            total_sales = (await cursor.fetchone())[0]
        
        async with db.execute("SELECT SUM(amount) FROM payments WHERE status = 'succeeded'") as cursor:
            total_revenue = (await cursor.fetchone())[0] or 0
        
        async with db.execute("SELECT COUNT(DISTINCT user_id) FROM purchases") as cursor:
            unique_buyers = (await cursor.fetchone())[0]

    stats_text = (
        f"📊 <b>Статистика WIXYEZ VPN</b>\n\n"
        f"💰 <b>Общая выручка:</b> {int(total_revenue)}₽\n"
        f"📦 <b>Продано конфигов:</b> {total_sales} шт.\n"
        f"👥 <b>Уникальных покупателей:</b> {unique_buyers}\n"
        f"📈 <b>Средний чек:</b> {int(total_revenue / total_sales) if total_sales > 0 else 0}₽\n"
    )

    await call.message.edit_text(
        stats_text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
        ])
    )

@dp.callback_query(F.data == "recent_payments")
async def show_recent_payments(call: types.CallbackQuery):
    """Показать последние платежи"""
    if call.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("""
            SELECT p.username, c.name, p.amount, p.status, p.created_at
            FROM payments p
            JOIN configs c ON p.config_id = c.id
            ORDER BY p.created_at DESC
            LIMIT 10
        """) as cursor:
            payments = await cursor.fetchall()

    if not payments:
        return await call.message.edit_text(
            "💳 <b>Платежей пока нет</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
            ])
        )

    text = "💳 <b>Последние 10 платежей:</b>\n\n"
    for username, conf_name, amount, status, created_at in payments:
        status_emoji = "✅" if status == "succeeded" else "⏳"
        text += f"{status_emoji} @{username} | {conf_name} | {int(amount)}₽\n"

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
        ])
    )

@dp.callback_query(F.data == "back_admin")
async def back_to_admin(call: types.CallbackQuery):
    """Вернуться в админ-панель"""
    await call.message.edit_text(
        "🛠 <b>Панель управления WIXYEZ VPN</b>\n\n"
        "Выберите нужное действие:",
        reply_markup=admin_menu()
    )

# ====================== ЗАПУСК БОТА ======================
async def on_startup():
    """Действия при запуске"""
    await init_db()
    asyncio.create_task(check_payments_loop())
    logger.info("=" * 50)
    logger.info("🚀 WIXYEZ VPN Bot успешно запущен!")
    logger.info("=" * 50)

async def on_shutdown():
    """Действия при остановке"""
    logger.info("🛑 WIXYEZ VPN Bot остановлен")

async def main():
    """Главная функция"""
    await on_startup()
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await on_shutdown()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⚠️ Бот остановлен пользователем")
