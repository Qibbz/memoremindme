# database.py - Робота з базою даних (SQLite + PostgreSQL)

import sqlite3
import os
import logging
from datetime import datetime
from telegram import Bot

logger = logging.getLogger(__name__)

# Глобальна змінна для бота (для сповіщень адміна)
_bot_instance = None


def set_bot_instance(bot: Bot):
    """Встановлює екземпляр бота для сповіщень адміна"""
    global _bot_instance
    _bot_instance = bot


# Шлях до бази даних для SQLite (локальна розробка)
DB_PATH = "memoremindme.db"

# Перевіряємо чи використовуємо PostgreSQL (Railway) чи SQLite (локально)
USE_POSTGRES = os.getenv('DATABASE_URL') is not None


def get_db_connection():
    """Повертає з'єднання з базою даних (PostgreSQL або SQLite)"""

    if USE_POSTGRES:
        # PostgreSQL (Railway)
        import psycopg2
        from psycopg2.extras import RealDictCursor

        database_url = os.getenv('DATABASE_URL')
        conn = psycopg2.connect(database_url)
        return conn
    else:
        # SQLite (локальна розробка)
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn


def init_db():
    """Створення таблиць при першому запуску"""

    conn = get_db_connection()
    cursor = conn.cursor()

    if USE_POSTGRES:
        # ========== POSTGRESQL СХЕМА ==========

        # Таблиця користувачів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                chat_id BIGINT UNIQUE NOT NULL,
                username TEXT,
                is_authorized BOOLEAN DEFAULT FALSE,
                timezone TEXT DEFAULT 'Europe/Kyiv',
                reminder_time TEXT DEFAULT '09:00',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблиця груп
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS groups (
                group_id SERIAL PRIMARY KEY,
                name TEXT NOT NULL,
                code TEXT UNIQUE NOT NULL,
                created_by BIGINT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Таблиця учасників груп
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS group_members (
                group_id INTEGER REFERENCES groups(group_id) ON DELETE CASCADE,
                user_id BIGINT REFERENCES users(user_id) ON DELETE CASCADE,
                is_admin BOOLEAN DEFAULT FALSE,
                joined_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (group_id, user_id)
            )
        """)

        # Таблиця нагадувань
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                reminder_id SERIAL PRIMARY KEY,
                user_id BIGINT NOT NULL REFERENCES users(user_id) ON DELETE CASCADE,
                group_id INTEGER REFERENCES groups(group_id) ON DELETE CASCADE,
                text TEXT NOT NULL,
                next_date DATE NOT NULL,
                original_day INTEGER,
                type TEXT CHECK(type IN ('once', 'monthly', 'yearly')) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Індекси для PostgreSQL
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_next_date ON reminders(next_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_group_id ON reminders(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_code ON groups(code)")

    else:
        # ========== SQLITE СХЕМА (для локальної розробки) ==========

        # Таблиця користувачів
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                chat_id INTEGER UNIQUE NOT NULL,
                username TEXT,
                is_authorized BOOLEAN DEFAULT 0,
                timezone TEXT DEFAULT 'Europe/Kyiv',
                reminder_time TEXT DEFAULT '09:00',
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

        # Індекси для SQLite
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_next_date ON reminders(next_date)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_user_id ON reminders(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_reminders_group_id ON reminders(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_user_id ON group_members(user_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_group_members_group_id ON group_members(group_id)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_groups_code ON groups(code)")

    conn.commit()
    conn.close()

    db_type = "PostgreSQL (Railway)" if USE_POSTGRES else "SQLite (локально)"
    print(f"✅ База даних ініціалізована: {db_type}")


# ============ Функції для роботи з користувачами ============

def add_user(user_id, chat_id, username=None):
    """Додавання нового користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if USE_POSTGRES:
            cursor.execute("""
                INSERT INTO users (user_id, chat_id, username)
                VALUES (%s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
            """, (user_id, chat_id, username))
        else:
            cursor.execute("""
                INSERT OR IGNORE INTO users (user_id, chat_id, username)
                VALUES (?, ?, ?)
            """, (user_id, chat_id, username))
        conn.commit()
    finally:
        conn.close()


def authorize_user(user_id):
    """Авторизація користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE users SET is_authorized = TRUE WHERE user_id = %s
            """, (user_id,))
        else:
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
        if USE_POSTGRES:
            cursor.execute("""
                SELECT is_authorized FROM users WHERE user_id = %s
            """, (user_id,))
        else:
            cursor.execute("""
                SELECT is_authorized FROM users WHERE user_id = ?
            """, (user_id,))
        result = cursor.fetchone()

        if USE_POSTGRES:
            return result and result[0] == True
        else:
            return result and result['is_authorized'] == 1
    finally:
        conn.close()


def unauthorize_user(user_id):
    """Розавторизація користувача (вихід)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE users SET is_authorized = FALSE WHERE user_id = %s
            """, (user_id,))
        else:
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
        if USE_POSTGRES:
            cursor.execute("""
                SELECT * FROM users WHERE user_id = %s
            """, (user_id,))
            result = cursor.fetchone()
            if result:
                # Конвертуємо tuple в dict для PostgreSQL
                columns = [desc[0] for desc in cursor.description]
                return dict(zip(columns, result))
            return None
        else:
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
        if USE_POSTGRES:
            cursor.execute("""
                SELECT timezone, reminder_time FROM users WHERE user_id = %s
            """, (user_id,))
            result = cursor.fetchone()
            if result:
                return {
                    'timezone': result[0] or 'Europe/Kyiv',
                    'reminder_time': result[1] or '09:00'
                }
        else:
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


def update_user_timezone(user_id, timezone):
    """Оновлення часового поясу користувача"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE users SET timezone = %s WHERE user_id = %s
            """, (timezone, user_id))
        else:
            cursor.execute("""
                UPDATE users SET timezone = ? WHERE user_id = ?
            """, (timezone, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()


def update_user_reminder_time(user_id, time_str):
    """Оновлення часу нагадувань користувача (формат HH:MM)"""
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if USE_POSTGRES:
            cursor.execute("""
                UPDATE users SET reminder_time = %s WHERE user_id = %s
            """, (time_str, user_id))
        else:
            cursor.execute("""
                UPDATE users SET reminder_time = ? WHERE user_id = ?
            """, (time_str, user_id))
        conn.commit()
        return cursor.rowcount > 0
    finally:
        conn.close()