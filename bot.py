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
BOT_TOKEN = "8633169948:AAFfCeDz1gJGsjg4WvODHKtNulTRCotLzWo"
YOOMONEY_ACCESS_TOKEN = "4100118889570559.3288B2E716CEEB922A26BD6BEAC58648FBFB680CCF64E4E1447D714D6FB5EA5F01F1478FAC686BEF394C8A186C98982DE563C1ABCDF9F2F61D971B61DA3C7E486CA818F98B9E0069F1C0891E090DD56A11319D626A40F0AE8302A8339DED9EB7969617F191D93275F64C4127A3ECB7AED33FCDE91CA68690EB7534C67E6C219E"
YOOMONEY_WALLET = "4100118889570559"
ADMIN_ID = 8346538289  # ←←← ЗАМЕНИ НА СВОЙ ID
SUPPORT_USERNAME = "MetroShopSupport"

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

class AddChannel(StatesGroup):
    channel_id = State()
    channel_name = State()

class BroadcastState(StatesGroup):
    message = State()
    confirm = State()

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
                original_filename TEXT NOT NULL,
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
            
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                first_name TEXT,
                last_name TEXT,
                joined_at TEXT NOT NULL,
                last_activity TEXT,
                has_access INTEGER DEFAULT 0
            );
            
            CREATE TABLE IF NOT EXISTS channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id TEXT NOT NULL UNIQUE,
                channel_name TEXT NOT NULL,
                is_active INTEGER DEFAULT 1,
                added_at TEXT NOT NULL
            );
            
            CREATE INDEX IF NOT EXISTS idx_payments_status ON payments(status);
            CREATE INDEX IF NOT EXISTS idx_purchases_user ON purchases(user_id);
            CREATE INDEX IF NOT EXISTS idx_users_joined ON users(joined_at);
        """)
        await db.commit()
    logger.info("✅ База данных инициализирована")

async def add_user(user_id: int, username: str = None, first_name: str = None, last_name: str = None):
    """Добавить пользователя в базу"""
    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (user_id, username, first_name, last_name, joined_at, last_activity, has_access) 
               VALUES (?, ?, ?, ?, ?, ?, 0)""",
            (user_id, username, first_name, last_name, datetime.now().isoformat(), datetime.now().isoformat())
        )
        await db.execute(
            "UPDATE users SET last_activity = ? WHERE user_id = ?",
            (datetime.now().isoformat(), user_id)
        )
        await db.commit()

async def grant_access(user_id: int):
    """Предоставить доступ пользователю"""
    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.execute(
            "UPDATE users SET has_access = 1 WHERE user_id = ?",
            (user_id,)
        )
        await db.commit()

async def has_access(user_id: int) -> bool:
    """Проверить, есть ли доступ у пользователя"""
    # Админ всегда имеет доступ
    if user_id == ADMIN_ID:
        return True
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT has_access FROM users WHERE user_id = ?",
            (user_id,)
        ) as cursor:
            result = await cursor.fetchone()
            return result and result[0] == 1

async def get_active_channels():
    """Получить активные каналы"""
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT channel_id, channel_name FROM channels WHERE is_active = 1"
        ) as cursor:
            return await cursor.fetchall()

async def check_subscription(user_id: int) -> bool:
    """Проверка подписки на все каналы"""
    channels = await get_active_channels()
    
    if not channels:
        return True  # Если нет каналов, доступ открыт
    
    for channel_id, _ in channels:
        try:
            member = await bot.get_chat_member(chat_id=channel_id, user_id=user_id)
            if member.status in ['left', 'kicked']:
                return False
        except Exception as e:
            logger.error(f"Ошибка проверки подписки на {channel_id}: {e}")
            return False
    
    return True

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
        [InlineKeyboardButton(text="📊 Полная статистика", callback_data="full_stats")],
        [InlineKeyboardButton(text="👥 Управление каналами", callback_data="manage_channels")],
        [InlineKeyboardButton(text="📢 Рассылка", callback_data="broadcast")],
        [InlineKeyboardButton(text="💰 Платежи", callback_data="recent_payments")]
    ])

def channels_menu() -> InlineKeyboardMarkup:
    """Меню управления каналами"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить канал", callback_data="add_channel")],
        [InlineKeyboardButton(text="📋 Список каналов", callback_data="list_channels")],
        [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
    ])

def back_button() -> InlineKeyboardMarkup:
    """Кнопка назад"""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="◀️ Назад в меню", callback_data="back_main")]
    ])

async def subscription_keyboard():
    """Клавиатура с каналами для подписки"""
    channels = await get_active_channels()
    keyboard = []
    
    for channel_id, channel_name in channels:
        # Убираем @ если есть для формирования ссылки
        clean_id = channel_id.replace('@', '')
        keyboard.append([
            InlineKeyboardButton(
                text=f"📢 {channel_name}",
                url=f"https://t.me/{clean_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="✅ Я подписался", callback_data="check_subscription")])
    
    return InlineKeyboardMarkup(inline_keyboard=keyboard)

# ====================== ПРОВЕРКА ПОДПИСКИ ======================
@dp.callback_query(F.data == "check_subscription")
async def check_sub_callback(call: types.CallbackQuery):
    """Проверка подписки по кнопке"""
    user_id = call.from_user.id
    
    is_subscribed = await check_subscription(user_id)
    
    if is_subscribed:
        # Предоставляем доступ
        await grant_access(user_id)
        await call.answer("✅ Подписка подтверждена!", show_alert=True)
        await call.message.edit_text(
            "🎉 <b>Отлично! Теперь у вас есть доступ к боту!</b>\n\n"
            "🌐 <b>WIXYEZ VPN</b>\n\n"
            "🎮 Ваш надёжный помощник для PUBG Mobile\n\n"
            "📱 Выберите действие:",
            reply_markup=main_menu()
        )
    else:
        await call.answer("❌ Вы не подписаны на все каналы!", show_alert=True)

# ====================== ОСНОВНЫЕ ХЕНДЛЕРЫ ======================
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    """Команда /start"""
    user_id = message.from_user.id
    username = message.from_user.username
    first_name = message.from_user.first_name
    last_name = message.from_user.last_name
    
    await add_user(user_id, username, first_name, last_name)
    logger.info(f"👤 Пользователь: {username} (ID: {user_id})")
    
    # Проверяем доступ
    if not await has_access(user_id):
        channels = await get_active_channels()
        
        if channels:
            # Есть обязательные каналы - требуем подписку
            await message.answer(
                "👋 <b>Добро пожаловать в WIXYEZ VPN!</b>\n\n"
                "🔒 Для использования бота подпишитесь на наши каналы:\n\n"
                "После подписки нажмите кнопку ниже 👇",
                reply_markup=await subscription_keyboard()
            )
        else:
            # Нет обязательных каналов - даём доступ сразу
            await grant_access(user_id)
            await show_welcome(message)
    else:
        # Доступ уже есть
        await show_welcome(message)

async def show_welcome(message: types.Message):
    """Показать приветствие с доступом"""
    welcome_text = (
        "🌐 <b>Добро пожаловать в WIXYEZ VPN!</b>\n\n"
        "🎮 Лучший сервис VPN-конфигов для <b>PUBG Mobile</b>\n\n"
        "⚡️ <b>Наши преимущества:</b>\n"
        "✅ Минимальный пинг для комфортной игры\n"
        "✅ Стабильный залёт в PUBG Mobile\n"
        "✅ Мгновенная автоматическая выдача\n"
        "✅ Поддержка 24/7\n"
        "✅ Стабильное соединение\n\n"
        "📱 Выберите действие ниже:"
    )
    
    await message.answer(welcome_text, reply_markup=main_menu())
    
    if message.from_user.id == ADMIN_ID:
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
    # Проверка доступа
    if not await has_access(call.from_user.id):
        channels = await get_active_channels()
        if channels:
            return await call.message.edit_text(
                "🔒 <b>Для доступа к боту подпишитесь на наши каналы:</b>\n\n"
                "После подписки нажмите кнопку ниже 👇",
                reply_markup=await subscription_keyboard()
            )
    
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

    payment_url = (
        f"https://yoomoney.ru/quickpay/confirm?"
        f"receiver={YOOMONEY_WALLET}"
        f"&quickpay-form=shop"
        f"&targets=WIXYEZ VPN - {name}"
        f"&paymentType=SB"
        f"&sum={price}"
        f"&label={label}"
    )

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
    # Проверка доступа
    if not await has_access(call.from_user.id):
        channels = await get_active_channels()
        if channels:
            return await call.message.edit_text(
                "🔒 <b>Для доступа к боту подпишитесь на наши каналы:</b>\n\n"
                "После подписки нажмите кнопку ниже 👇",
                reply_markup=await subscription_keyboard()
            )
    
    user_id = call.from_user.id
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("""
            SELECT c.name, c.filename, c.original_filename, p.purchased_at 
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
    for name, filename, original_filename, _ in purchases:
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
    
    # Получаем оригинальное имя файла
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT original_filename FROM configs WHERE filename = ?",
            (filename,)
        ) as cursor:
            result = await cursor.fetchone()
            original_filename = result[0] if result else filename
    
    # Отправляем с оригинальным именем
    try:
        await call.message.answer_document(
            FSInputFile(filepath, filename=original_filename),
            caption=(
                "📥 <b>Ваш VPN-конфиг</b>\n\n"
                "✅ Просто импортируйте файл в WireGuard\n"
                "🎮 Наслаждайтесь игрой без лагов!"
            )
        )
        await call.answer("✅ Конфиг отправлен")
    except Exception as e:
        logger.error(f"Ошибка при отправке конфига: {e}")
        await call.answer("❌ Ошибка при отправке файла", show_alert=True)

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
        "   • Стабильный залёт в PUBG Mobile\n\n"
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
                            "SELECT filename, original_filename, name FROM configs WHERE id = ?",
                            (config_id,)
                        ) as cursor:
                            config = await cursor.fetchone()
                        
                        if config:
                            filename, original_filename, conf_name = config
                            filepath = f"configs/{filename}"
                            
                            if os.path.exists(filepath):
                                try:
                                    await bot.send_document(
                                        user_id,
                                        FSInputFile(filepath, filename=original_filename),
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

# === ДОБАВЛЕНИЕ КОНФИГА ===
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
    original_filename = message.document.file_name  # Сохраняем оригинальное имя
    filename = f"{uuid.uuid4()}.conf"  # Уникальное имя для хранения
    filepath = f"configs/{filename}"

    await bot.download(message.document, destination=filepath)

    async with aiosqlite.connect("vpn_shop.db") as db:
        await db.execute(
            "INSERT INTO configs (name, price, description, filename, original_filename, created_at) VALUES (?, ?, ?, ?, ?, ?)",
            (data["name"], data["price"], data["description"], filename, original_filename, datetime.now().isoformat())
        )
        await db.commit()

    await message.answer(
        f"✅ <b>Конфиг успешно добавлен!</b>\n\n"
        f"📦 Название: {data['name']}\n"
        f"💰 Цена: {int(data['price'])}₽\n"
        f"📝 Описание: {data['description']}\n"
        f"📄 Файл: {original_filename}\n\n"
        f"Конфиг уже доступен для покупки!",
        reply_markup=admin_menu()
    )
    await state.clear()
    logger.info(f"➕ Добавлен новый конфиг: {data['name']} ({original_filename})")

# === СПИСОК КОНФИГОВ ===
@dp.callback_query(F.data == "list_configs")
async def list_all_configs(call: types.CallbackQuery):
    """Список всех конфигов"""
    if call.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("SELECT id, name, price, original_filename, created_at FROM configs ORDER BY id DESC") as cursor:
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
    for config_id, name, price, original_filename, created_at in configs:
        text += f"🆔 <code>{config_id}</code> | {name} — {int(price)}₽\n"
        text += f"   └ 📄 {original_filename}\n\n"

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
        ])
    )

# === ПОЛНАЯ СТАТИСТИКА ===
@dp.callback_query(F.data == "full_stats")
async def show_full_stats(call: types.CallbackQuery):
    """Показать полную статистику"""
    if call.from_user.id != ADMIN_ID:
        return
    
    try:
        async with aiosqlite.connect("vpn_shop.db") as db:
            # Всего пользователей
            async with db.execute("SELECT COUNT(*) FROM users") as cursor:
                total_users = (await cursor.fetchone())[0]
            
            # Пользователи с доступом
            async with db.execute("SELECT COUNT(*) FROM users WHERE has_access = 1") as cursor:
                users_with_access = (await cursor.fetchone())[0]
            
            # Пользователи за сегодня
            today = datetime.now().date().isoformat()
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE DATE(joined_at) = ?", (today,)
            ) as cursor:
                users_today = (await cursor.fetchone())[0]
            
            # Пользователи за неделю
            async with db.execute(
                "SELECT COUNT(*) FROM users WHERE DATE(joined_at) >= DATE('now', '-7 days')"
            ) as cursor:
                users_week = (await cursor.fetchone())[0]
            
            # Продажи
            async with db.execute("SELECT COUNT(*) FROM purchases") as cursor:
                total_sales = (await cursor.fetchone())[0]
            
            # Выручка
            async with db.execute("SELECT SUM(amount) FROM payments WHERE status = 'succeeded'") as cursor:
                total_revenue = (await cursor.fetchone())[0] or 0
            
            # Уникальные покупатели
            async with db.execute("SELECT COUNT(DISTINCT user_id) FROM purchases") as cursor:
                unique_buyers = (await cursor.fetchone())[0]
            
            # Средний чек
            avg_check = int(total_revenue / total_sales) if total_sales > 0 else 0
            
            # Конверсия
            conversion = round((unique_buyers / total_users * 100), 2) if total_users > 0 else 0

        stats_text = (
            f"📊 <b>ПОЛНАЯ СТАТИСТИКА WIXYEZ VPN</b>\n\n"
            f"👥 <b>ПОЛЬЗОВАТЕЛИ:</b>\n"
            f"├ Всего зарегистрировано: <b>{total_users}</b>\n"
            f"├ С доступом к боту: <b>{users_with_access}</b>\n"
            f"├ Новых за сегодня: <b>{users_today}</b>\n"
            f"└ Новых за неделю: <b>{users_week}</b>\n\n"
            f"💰 <b>ФИНАНСЫ:</b>\n"
            f"├ Общая выручка: <b>{int(total_revenue)}₽</b>\n"
            f"├ Продано конфигов: <b>{total_sales}</b>\n"
            f"├ Средний чек: <b>{avg_check}₽</b>\n"
            f"└ Уникальных покупателей: <b>{unique_buyers}</b>\n\n"
            f"📈 <b>КОНВЕРСИЯ:</b>\n"
            f"└ Из посетителей в покупатели: <b>{conversion}%</b>"
        )

        await call.message.edit_text(
            stats_text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="full_stats")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
            ])
        )
    except Exception as e:
        if "message is not modified" in str(e):
            await call.answer("✅ Статистика актуальна", show_alert=False)
        else:
            logger.error(f"❌ Ошибка в статистике: {e}")
            await call.answer("❌ Ошибка при загрузке статистики", show_alert=True)

# === УПРАВЛЕНИЕ КАНАЛАМИ ===
@dp.callback_query(F.data == "manage_channels")
async def manage_channels_menu(call: types.CallbackQuery):
    """Меню управления каналами"""
    if call.from_user.id != ADMIN_ID:
        return
    
    await call.message.edit_text(
        "👥 <b>Управление обязательными каналами</b>\n\n"
        "Пользователь получит доступ только после подписки на все активные каналы.\n\n"
        "Выберите действие:",
        reply_markup=channels_menu()
    )

@dp.callback_query(F.data == "add_channel")
async def start_add_channel(call: types.CallbackQuery, state: FSMContext):
    """Начать добавление канала"""
    if call.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(AddChannel.channel_id)
    await call.message.edit_text(
        "➕ <b>Добавление обязательного канала</b>\n\n"
        "Введите ID или username канала:\n"
        "<i>Например: @your_channel или -1001234567890</i>\n\n"
        "⚠️ <b>Важно:</b> Бот должен быть админом канала!"
    )

@dp.message(AddChannel.channel_id)
async def process_channel_id(message: types.Message, state: FSMContext):
    """Обработка ID канала"""
    channel_id = message.text.strip()
    
    # Проверяем, что бот админ канала
    try:
        chat = await bot.get_chat(channel_id)
        await state.update_data(channel_id=channel_id)
        await state.set_state(AddChannel.channel_name)
        await message.answer(
            f"✅ Канал найден: <b>{chat.title}</b>\n\n"
            f"Введите название для отображения пользователям:\n"
            f"<i>Например: Основной канал</i>"
        )
    except Exception as e:
        await message.answer(
            f"❌ Ошибка: {e}\n\n"
            "Убедитесь, что:\n"
            "• ID/username введён правильно\n"
            "• Бот добавлен в канал как администратор\n"
            "• Канал не является приватным чатом"
        )
        await state.clear()

@dp.message(AddChannel.channel_name)
async def process_channel_name(message: types.Message, state: FSMContext):
    """Сохранение канала"""
    data = await state.get_data()
    channel_name = message.text.strip()
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        try:
            await db.execute(
                "INSERT INTO channels (channel_id, channel_name, added_at) VALUES (?, ?, ?)",
                (data["channel_id"], channel_name, datetime.now().isoformat())
            )
            await db.commit()
            
            await message.answer(
                f"✅ <b>Канал успешно добавлен!</b>\n\n"
                f"ID: <code>{data['channel_id']}</code>\n"
                f"Название: {channel_name}\n\n"
                f"Теперь все новые пользователи должны будут подписаться на этот канал для получения доступа к боту.",
                reply_markup=admin_menu()
            )
            logger.info(f"➕ Добавлен канал: {channel_name} ({data['channel_id']})")
        except Exception as e:
            await message.answer(f"❌ Ошибка при добавлении: {e}\n\nВозможно канал уже добавлен.")
    
    await state.clear()

@dp.callback_query(F.data == "list_channels")
async def list_all_channels(call: types.CallbackQuery):
    """Список всех каналов"""
    if call.from_user.id != ADMIN_ID:
        return
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT id, channel_id, channel_name, is_active FROM channels ORDER BY id"
        ) as cursor:
            channels = await cursor.fetchall()

    if not channels:
        return await call.message.edit_text(
            "📋 <b>Список каналов пуст</b>\n\n"
            "Добавьте первый канал!\n"
            "Пока нет обязательных каналов - бот доступен всем без подписки.",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="◀️ Назад", callback_data="manage_channels")]
            ])
        )

    text = "📋 <b>Обязательные каналы для подписки:</b>\n\n"
    keyboard = []
    
    for ch_id, channel_id, channel_name, is_active in channels:
        status = "✅ Активен" if is_active else "❌ Отключён"
        text += f"{status} | <code>{ch_id}</code> | {channel_name}\n"
        text += f"   └ ID: <code>{channel_id}</code>\n\n"
        
        toggle_text = "❌ Отключить" if is_active else "✅ Включить"
        keyboard.append([
            InlineKeyboardButton(
                text=f"{toggle_text}: {channel_name}",
                callback_data=f"toggle_channel_{ch_id}"
            )
        ])
    
    keyboard.append([InlineKeyboardButton(text="◀️ Назад", callback_data="manage_channels")])

    await call.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(inline_keyboard=keyboard)
    )

@dp.callback_query(F.data.startswith("toggle_channel_"))
async def toggle_channel(call: types.CallbackQuery):
    """Включить/отключить канал"""
    if call.from_user.id != ADMIN_ID:
        return
    
    channel_db_id = int(call.data.split("_")[2])
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute(
            "SELECT is_active, channel_name FROM channels WHERE id = ?", (channel_db_id,)
        ) as cursor:
            result = await cursor.fetchone()
            if not result:
                return await call.answer("❌ Канал не найден", show_alert=True)
            
            is_active, channel_name = result
        
        new_status = 0 if is_active else 1
        await db.execute(
            "UPDATE channels SET is_active = ? WHERE id = ?",
            (new_status, channel_db_id)
        )
        await db.commit()
    
    status_text = "включён" if new_status else "отключён"
    await call.answer(f"✅ Канал '{channel_name}' {status_text}", show_alert=True)
    
    # Обновляем список
    await list_all_channels(call)

# === РАССЫЛКА ===
@dp.callback_query(F.data == "broadcast")
async def start_broadcast(call: types.CallbackQuery, state: FSMContext):
    """Начать рассылку"""
    if call.from_user.id != ADMIN_ID:
        return
    
    await state.set_state(BroadcastState.message)
    await call.message.edit_text(
        "📢 <b>Массовая рассылка</b>\n\n"
        "Отправьте сообщение для рассылки всем пользователям с доступом:\n"
        "<i>(Можно отправить текст, фото, видео или документ)</i>"
    )

@dp.message(BroadcastState.message)
async def process_broadcast_message(message: types.Message, state: FSMContext):
    """Обработка сообщения для рассылки"""
    await state.update_data(message_id=message.message_id, chat_id=message.chat.id)
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("SELECT COUNT(*) FROM users WHERE has_access = 1") as cursor:
            total_users = (await cursor.fetchone())[0]
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"✅ Отправить {total_users} пользователям", callback_data="confirm_broadcast")],
        [InlineKeyboardButton(text="❌ Отменить", callback_data="back_admin")]
    ])
    
    await message.answer(
        f"📢 <b>Подтвердите рассылку</b>\n\n"
        f"Сообщение будет отправлено <b>{total_users}</b> пользователям с доступом к боту",
        reply_markup=kb
    )
    await state.set_state(BroadcastState.confirm)

@dp.callback_query(F.data == "confirm_broadcast")
async def confirm_broadcast(call: types.CallbackQuery, state: FSMContext):
    """Подтверждение и выполнение рассылки"""
    if call.from_user.id != ADMIN_ID:
        return
    
    data = await state.get_data()
    message_id = data.get("message_id")
    chat_id = data.get("chat_id")
    
    await call.message.edit_text("📤 <b>Рассылка началась...</b>")
    
    async with aiosqlite.connect("vpn_shop.db") as db:
        async with db.execute("SELECT user_id FROM users WHERE has_access = 1") as cursor:
            users = await cursor.fetchall()
    
    success = 0
    failed = 0
    
    for (user_id,) in users:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=chat_id,
                message_id=message_id
            )
            success += 1
            await asyncio.sleep(0.05)  # Защита от флуда
        except Exception as e:
            failed += 1
            logger.error(f"Ошибка рассылки пользователю {user_id}: {e}")
    
    await call.message.edit_text(
        f"✅ <b>Рассылка завершена!</b>\n\n"
        f"Успешно: <b>{success}</b>\n"
        f"Ошибок: <b>{failed}</b>",
        reply_markup=admin_menu()
    )
    
    await state.clear()
    logger.info(f"📢 Рассылка: {success} успешно, {failed} ошибок")

# === ПОСЛЕДНИЕ ПЛАТЕЖИ ===
@dp.callback_query(F.data == "recent_payments")
async def show_recent_payments(call: types.CallbackQuery):
    """Показать последние платежи"""
    if call.from_user.id != ADMIN_ID:
        return
    
    try:
        async with aiosqlite.connect("vpn_shop.db") as db:
            async with db.execute("""
                SELECT p.username, c.name, p.amount, p.status, p.created_at
                FROM payments p
                JOIN configs c ON p.config_id = c.id
                ORDER BY p.created_at DESC
                LIMIT 15
            """) as cursor:
                payments = await cursor.fetchall()

        if not payments:
            return await call.message.edit_text(
                "💳 <b>Платежей пока нет</b>",
                reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                    [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
                ])
            )

        text = "💳 <b>Последние 15 платежей:</b>\n\n"
        for username, conf_name, amount, status, created_at in payments:
            status_emoji = "✅" if status == "succeeded" else "⏳"
            date = created_at[:16].replace('T', ' ')
            text += f"{status_emoji} @{username}\n"
            text += f"   └ {conf_name} | {int(amount)}₽ | {date}\n\n"

        await call.message.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Обновить", callback_data="recent_payments")],
                [InlineKeyboardButton(text="◀️ Назад", callback_data="back_admin")]
            ])
        )
    except Exception as e:
        if "message is not modified" in str(e):
            await call.answer("✅ Данные актуальны", show_alert=False)
        else:
            logger.error(f"❌ Ошибка в платежах: {e}")
            await call.answer("❌ Ошибка при загрузке платежей", show_alert=True)

@dp.callback_query(F.data == "back_admin")
async def back_to_admin(call: types.CallbackQuery):
    """Вернуться в админ-панель"""
    try:
        await call.message.edit_text(
            "🛠 <b>Панель управления WIXYEZ VPN</b>\n\n"
            "Выберите нужное действие:",
            reply_markup=admin_menu()
        )
    except Exception as e:
        if "message is not modified" not in str(e):
            logger.error(f"Ошибка в back_to_admin: {e}")

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
