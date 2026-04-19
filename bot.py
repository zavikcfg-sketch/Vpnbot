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

from yoomoney import Client, Quickpay

# ========================= КОНФИГУРАЦИЯ =========================
BOT_TOKEN = "8633169948:AAGNxJN0CseW6nLiS-FWhmAivjqM4jhxx44"  # От @BotFather
YOOMONEY_ACCESS_TOKEN = "4100118889570559.3288B2E716CEEB922A26BD6BEAC58648FBFB680CCF64E4E1447D714D6FB5EA5F01F1478FAC686BEF394C8A186C98982DE563C1ABCDF9F2F61D971B61DA3C7E486CA818F98B9E0069F1C0891E090DD56A11319D626A40F0AE8302A8339DED9EB7969617F191D93275F64C4127A3ECB7AED33FCDE91CA68690EB7534C67E6C219E"
YOOMONEY_WALLET = "4100118889570559"
ADMIN_ID = 8346538289  # ←←← ЗАМЕНИ НА СВОЙ TELEGRAM ID

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
        [InlineKeyboardButton(text="ℹ️ Информация", callback_data="info")]
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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")]
    ])

# ====================== ОСНОВНЫЕ ХЕНДЛЕРЫ ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username or "Неизвестно"
    
    logger.info(f"👤 Новый пользователь: {username} (ID: {user_id})")
    
    welcome_text = (
        "🎮 <b>PUBG Mobile VPN Shop</b>\n\n"
        "Профессиональные VPN-конфиги для стабильной игры:\n"
        "✅ Низкий пинг\n"
        "✅ Обход блокировок\n"
        "✅ Моментальная выдача после оплаты\n\n"
        "Выберите действие:"
    )
    
    await message.answer(welcome_text, reply_markup=main_menu())
    
    if user_id == ADMIN_ID:
        await message.answer("👑 <b>Админ-панель доступна</b>", reply_markup=admin_menu())

@dp.message(Command("admin"))
async def cmd_admin(message: types.Message):
    """Команда /admin"""
    if message.from_user.id != ADMIN_ID:
        return await message.answer("❌ У вас нет доступа к админ-панели")
    
    await message.answer("🛠 <b>Панель администратора</b>", reply_markup=admin_menu())

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
            "❌ В данный момент конфиги недоступны.\n"
            "Попробуйте позже.",
            reply_markup=back_button()
        )

    keyboard = []
    for config_id, name, price, _ in configs:
        keyboard.append([
            InlineKeyboardButton(
                text=f"{name} — {int(price)}₽",
                callback_data=f"cfg_{config_id}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])

    await call.message.edit_text(
        "🛒 <b>Доступные VPN-конфиги:</b>\n\n"
        "Выберите подходящий вариант:",
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
        [InlineKeyboardButton(text="◀️ Назад", callback_data="buy")]
    ])

    await call.message.edit_text(
        f"<b>📦 {name}</b>\n\n"
        f"{description}\n\n"
        f"💰 <b>Цена: {int(price)}₽</b>\n\n"
        f"После оплаты конфиг придёт автоматически.",
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

    # Создание формы оплаты YooMoney
    quickpay = Quickpay(
        receiver=YOOMONEY_WALLET,
        quickpay_form="shop",
        targets=f"Покупка VPN {name}",
        paymentType="SB",
        sum=price,
        label=label
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
        [InlineKeyboardButton(text="💳 Перейти к оплате", url=quickpay.redirected_url)],
        [InlineKeyboardButton(text="◀️ Отмена", callback_data=f"cfg_{config_id}")]
    ])

    await call.message.edit_text(
        f"✅ <b>Счёт создан</b>\n\n"
        f"📦 Товар: <b>{name}</b>\n"
        f"💰 Сумма: <b>{int(price)}₽</b>\n\n"
        f"Нажмите кнопку ниже для оплаты.\n"
        f"После успешной оплаты конфиг будет отправлен автоматически.\n\n"
        f"⏱ Платёж действителен 1 час.",
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
            "Перейдите в раздел покупки, чтобы приобрести конфиг.",
            reply_markup=back_button()
        )
    
    keyboard = []
    for name, filename, _ in purchases:
        keyboard.append([
            InlineKeyboardButton(
                text=f"📥 {name}",
                callback_data=f"download_{filename}"
            )
        ])
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="back_main")])
    
    await call.message.edit_text(
        "📦 <b>Ваши покупки:</b>\n\n"
        "Нажмите на конфиг, чтобы скачать его заново:",
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
        caption="📥 <b>Ваш конфиг</b>\n\nИмпортируйте его в VPN-клиент."
    )
    await call.answer("✅ Конфиг отправлен")

# ====================== ИНФОРМАЦИЯ ======================
@dp.callback_query(F.data == "info")
async def show_info(call: types.CallbackQuery):
    """Показать информацию"""
    info_text = (
        "ℹ️ <b>Как использовать конфиг?</b>\n\n"
        "1️⃣ Скачайте VPN-клиент (например, OpenVPN)\n"
        "2️⃣ Импортируйте полученный .conf файл\n"
        "3️⃣ Подключитесь к VPN\n"
        "4️⃣ Наслаждайтесь стабильной игрой!\n\n"
        "❓ <b>Проблемы с подключением?</b>\n"
        "Напишите @your_support_username"
    )
    
    await call.message.edit_text(
        info_text,
        reply_markup=back_button()
    )

@dp.callback_query(F.data == "back_main")
async def back_to_main(call: types.CallbackQuery):
    """Вернуться в главное меню"""
    await call.message.edit_text(
        "🎮 <b>PUBG Mobile VPN Shop</b>\n\n"
        "Выберите действие:",
        reply_markup=main_menu()
    )

# ====================== ПРОВЕРКА ПЛАТЕЖЕЙ ======================
async def check_payments_loop():
    """Фоновая проверка платежей"""
    client = Client(YOOMONEY_ACCESS_TOKEN)
    logger.info("🔄 Запущена проверка платежей")
    
    while True:
        try:
            history = client.operation_history(records=50)
            
            async with aiosqlite.connect("vpn_shop.db") as db:
                for operation in history.operations:
                    if operation.status != "success" or operation.direction != "in":
                        continue
                    
                    label = operation.label
                    if not label:
                        continue
                    
                    # Проверяем, есть ли платёж в базе
                    async with db.execute(
                        "SELECT user_id, config_id, amount FROM payments WHERE label = ? AND status = 'pending'",
                        (label,)
                    ) as cursor:
                        payment = await cursor.fetchone()
                    
                    if not payment:
                        continue
                    
                    user_id, config_id, amount = payment
                    
                    # Обновляем статус платежа
                    await db.execute(
                        "UPDATE payments SET status = 'succeeded', completed_at = ? WHERE label = ?",
                        (datetime.now().isoformat(), label)
                    )
                    
                    # Добавляем в покупки
                    async with db.execute(
                        "SELECT username FROM payments WHERE label = ?", (label,)
                    ) as cur:
                        username = (await cur.fetchone())[0]
                    
                    await db.execute(
                        "INSERT INTO purchases (user_id, username, config_id, purchased_at) VALUES (?, ?, ?, ?)",
                        (user_id, username, config_id, datetime.now().isoformat())
                    )
                    await db.commit()
                    
                    # Получаем данные конфига
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
                                        f"✅ <b>Оплата получена!</b>\n\n"
                                        f"📦 Конфиг: <b>{conf_name}</b>\n"
                                        f"💰 Сумма: <b>{int(amount)}₽</b>\n\n"
                                        f"Импортируйте файл в ваш VPN-клиент.\n"
                                        f"Приятной игры! 🎮"
                                    )
                                )
                                logger.info(f"✅ Выдан конфиг {conf_name} пользователю {user_id}")
                                
                                # Уведомление админу
                                await bot.send_message(
                                    ADMIN_ID,
                                    f"💰 <b>Новая продажа!</b>\n\n"
                                    f"Пользователь: @{username}\n"
                                    f"Конфиг: {conf_name}\n"
                                    f"Сумма: {int(amount)}₽"
                                )
                            except Exception as e:
                                logger.error(f"❌ Ошибка отправки конфига: {e}")
                                await bot.send_message(
                                    user_id,
                                    "❌ Ошибка при отправке файла. Обратитесь в поддержку."
                                )
                        else:
                            logger.error(f"❌ Файл не найден: {filepath}")
                            await bot.send_message(
                                user_id,
                                "❌ Файл конфига не найден. Обратитесь в поддержку."
                            )
        
        except Exception as e:
            logger.error(f"❌ Ошибка проверки платежей: {e}")
        
        await asyncio.sleep(10)  # Проверка каждые 10 секунд

# ====================== АДМИН-ПАНЕЛЬ ======================
@dp.callback_query(F.data == "add_config")
async def start_add_config(call: types.CallbackQuery, state: FSMContext):
    """Начать добавление конфига"""
    if call.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(AddConfig.name)
    await call.message.edit_text("📝 <b>Введите название конфига:</b>\n\nНапример: VPN EU Premium")

@dp.message(AddConfig.name)
async def process_config_name(message: types.Message, state: FSMContext):
    """Обработка названия конфига"""
    await state.update_data(name=message.text)
    await state.set_state(AddConfig.price)
    await message.answer("💰 <b>Введите цену в рублях:</b>\n\nТолько число, например: 150")

@dp.message(AddConfig.price)
async def process_config_price(message: types.Message, state: FSMContext):
    """Обработка цены конфига"""
    try:
        price = float(message.text)
        if price <= 0:
            raise ValueError
        await state.update_data(price=price)
        await state.set_state(AddConfig.description)
        await message.answer("📄 <b>Введите описание конфига:</b>\n\nНапример: Быстрый сервер в Европе, пинг 20-30ms")
    except ValueError:
        await message.answer("❌ Введите корректную цену (число больше 0)")

@dp.message(AddConfig.description)
async def process_config_description(message: types.Message, state: FSMContext):
    """Обработка описания конфига"""
    await state.update_data(description=message.text)
    await state.set_state(AddConfig.file)
    await message.answer("📎 <b>Отправьте .conf файл:</b>")

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
        f"Название: {data['name']}\n"
        f"Цена: {int(data['price'])}₽\n"
        f"Описание: {data['description']}",
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
            "📋 <b>Список конфигов пуст</b>",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
            ])
        )

    text = "📋 <b>Все конфиги:</b>\n\n"
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
        f"📊 <b>Статистика магазина</b>\n\n"
        f"💰 Общая выручка: <b>{int(total_revenue)}₽</b>\n"
        f"📦 Продано конфигов: <b>{total_sales}</b>\n"
        f"👥 Уникальных покупателей: <b>{unique_buyers}</b>\n"
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
        "🛠 <b>Панель администратора</b>",
        reply_markup=admin_menu()
    )

# ====================== ЗАПУСК БОТА ======================
async def on_startup():
    """Действия при запуске"""
    await init_db()
    asyncio.create_task(check_payments_loop())
    logger.info("=" * 50)
    logger.info("🚀 VPN Shop Bot успешно запущен!")
    logger.info("=" * 50)

async def on_shutdown():
    """Действия при остановке"""
    logger.info("🛑 Бот остановлен")

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
