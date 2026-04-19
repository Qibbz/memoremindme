# config.py - Конфігурація бота

import os
from dotenv import load_dotenv

# Завантажуємо змінні з файлу .env
load_dotenv()

# Отримуємо значення з змінних середовища
BOT_TOKEN = os.getenv("BOT_TOKEN")
ACCESS_PASSWORD = os.getenv("ACCESS_PASSWORD")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))

# Перевіряємо, чи всі дані завантажилися
if not BOT_TOKEN:
    raise ValueError("❌ BOT_TOKEN не знайдено! Перевірте файл .env")
if not ACCESS_PASSWORD:
    raise ValueError("❌ ACCESS_PASSWORD не знайдено! Перевірте файл .env")

# Часовий пояс
TIMEZONE = "Europe/Kyiv"

# Ліміти
MAX_GROUPS_PER_USER = 3
MAX_MEMBERS_PER_GROUP = 10
MAX_TEXT_LENGTH = 200
MAX_GROUP_NAME_LENGTH = 30

# Backup налаштування
BACKUP_TIME = (6, 30)  # 6:30 UTC (після нагадувань о 6:00)
BACKUP_DAYS = (0, 1, 2, 3, 4, 5, 6)  # Щодня (0=понеділок, 6=неділя)

# Шлях до бази даних для backup
DB_PATH = "memoremindme.db"