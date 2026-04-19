# database.py - Робота з базою даних SQLite

import sqlite3
import os
from datetime import datetime

import functools
import logging
from telegram import Bot

logger = logging.getLogger(__name__)

# Глобальна змінна для бота (для сповіщень адміна)
_bot_instance = None

def set_bot_instance(bot: Bot):
    """Встановлює екземпляр бота для сповіщень адміна"""
    global _bot_instance
    _bot_instance = bot

DB_PATH = "memoremindme.db"

# ДОДАЙ на початку файлу після імпортів
from datetime import datetime, timedelta

# Словник для rate limiting алертів: error_hash -> last_sent_time
_alert_cooldown = {}
ALERT_COOLDOWN_MINUTES = 5  # Не спамити однаковими помилками частіше ніж раз в 5 хв


def _get_error_hash(error_message: str) -> str:
    """Створює простий хеш помилки для групування схожих"""
    # Беремо перші 50 символів + тип помилки
    return error_message[:50].lower().strip()


async def notify_admin_on_error(error_message: str, exception_details: str = ""):
    """
    Надсилає сповіщення адміністратору про помилку в базі даних
    З rate limiting — не спамить однаковими помилками
    """
    from config import ADMIN_ID

    if _bot_instance is None:
        logger.warning("Бот не ініціалізовано, не можу надіслати сповіщення адміну")
        return

    # Перевіряємо cooldown для цієї помилки
    error_hash = _get_error_hash(error_message)
    now = datetime.now()
    last_sent = _alert_cooldown.get(error_hash)

    if last_sent and (now - last_sent).total_seconds() < ALERT_COOLDOWN_MINUTES * 60:
        logger.info(f"⏱ Алерт для помилки '{error_hash}' пропущено (cooldown)")
        return

    try:
        full_message = (
            f"🚨 <b>Помилка в базі даних!</b>\n\n"
            f"❌ {error_message}\n"
        )

        if exception_details:
            # Обмежуємо довжину деталей
            if len(exception_details) > 400:
                exception_details = exception_details[:400] + "..."
            full_message += f"\n📝 Деталі:\n<code>{exception_details}</code>"

        await _bot_instance.send_message(
            chat_id=ADMIN_ID,
            text=full_message,
            parse_mode="HTML"
        )

        # Записуємо час відправки
        _alert_cooldown[error_hash] = now
        logger.info("✅ Адміністратора повідомлено про помилку")

    except Exception as e:
        logger.error(f"Не вдалося надіслати сповіщення адміну: {e}")


def with_error_notification(func):
    """
    Декоратор для автоматичного сповіщення адміна про помилки SQL
    """

    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_msg = f"Помилка в {func.__name__}: {str(e)}"
            logger.error(error_msg)

            # Асинхронно сповіщаємо адміна (не блокуємо основний код)
            if _bot_instance:
                import asyncio
                try:
                    loop = asyncio.get_event_loop()
                    if loop.is_running():
                        loop.create_task(notify_admin_on_error(error_msg, str(e)))
                except Exception as async_error:
                    logger.error(f"Помилка при створенні async задачі: {async_error}")

            # Перекидаємо виняток далі
            raise

    return wrapper

def init_db():
    """Створення таблиць при першому запуску"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # Таблиця користувачів — ДОДАЄМО НОВІ ПОЛЯ
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            chat_id INTEGER UNIQUE NOT NULL,
            username TEXT,
            is_authorized BOOLEAN DEFAULT 0,
            timezone TEXT DEFAULT 'Europe/Kyiv',
            reminder_time TEXT DEFAULT '09:00',  -- ✅ НОВЕ: час нагадувань (HH:MM)
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # Таблиця груп
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS groups (
            group_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            code TEXT UNIQUE NOT NULL,
            created_by INTEGER NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (created_by) REFERENCES users (user_id)
        )
    """)

    # Таблиця учасників груп
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS group_members (
            group_id INTEGER,
            user_id INTEGER,
            is_admin BOOLEAN DEFAULT 0,
            joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (group_id, user_id),
            FOREIGN KEY (group_id) REFERENCES groups (group_id),
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
    """)

    # Таблиця нагадувань
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            reminder_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            group_id INTEGER,
            text TEXT NOT NULL,
            next_date DATE NOT NULL,
            original_day INTEGER,
            type TEXT CHECK(type IN ('once', 'monthly', 'yearly')) NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (user_id),
            FOREIGN KEY (group_id) REFERENCES groups (group_id)
        )
    """)

    # Індекси
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_next_date ON reminders(next_date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_group_id ON reminders(group_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_code ON groups(code)")

    conn.commit()
    conn.close()
    print("✅ База даних ініціалізована (з індексами та налаштуваннями користувача)")


def get_db_connection():
    """Повертає з'єднання з базою даних"""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# Функції для роботи з користувачами
@with_error_notification
def add_user(user_id, chat_id, username=None):
    """Додавання нового користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT OR IGNORE INTO users (user_id, chat_id, username)
            VALUES (?, ?, ?)
        """, (user_id, chat_id, username))
        conn.commit()
    finally:
        conn.close()


@with_error_notification
def authorize_user(user_id):
    """Авторизація користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users SET is_authorized = 1 WHERE user_id = ?
        """, (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def is_user_authorized(user_id):
    """Перевірка чи авторизований користувач"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT is_authorized FROM users WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()
        return result and result['is_authorized'] == 1
    finally:
        conn.close()

@with_error_notification
def unauthorize_user(user_id):
    """Розавторизація користувача (вихід)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users SET is_authorized = 0 WHERE user_id = ?
        """, (user_id,))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()

def get_user(user_id):
    """Отримання інформації про користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT * FROM users WHERE user_id = ?
        """, (user_id,))
        return cursor.fetchone()
    finally:
        conn.close()


def get_user_settings(user_id):
    """Отримання налаштувань користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT timezone, reminder_time FROM users WHERE user_id = ?
        """, (user_id,))
        result = cursor.fetchone()

        if result:
            return {
                'timezone': result['timezone'] or 'Europe/Kyiv',
                'reminder_time': result['reminder_time'] or '09:00'
            }
        return {'timezone': 'Europe/Kyiv', 'reminder_time': '09:00'}
    finally:
        conn.close()


@with_error_notification
def update_user_timezone(user_id, timezone):
    """Оновлення часового поясу користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users SET timezone = ? WHERE user_id = ?
        """, (timezone, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


@with_error_notification
def update_user_reminder_time(user_id, time_str):
    """Оновлення часу нагадувань користувача (формат HH:MM)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users SET reminder_time = ? WHERE user_id = ?
        """, (time_str, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()