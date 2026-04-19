#!/usr/bin/env python3
import sys
import traceback

print("🔄 Починаємо діагностику...")

try:
    print("1️⃣ Імпорт config...")
    from config import BOT_TOKEN, ACCESS_PASSWORD

    print(f"   ✅ BOT_TOKEN: {BOT_TOKEN[:20]}...")

    print("2️⃣ Імпорт database...")
    from database import init_db, add_user, authorize_user, is_user_authorized

    print("   ✅ database OK")

    print("3️⃣ Імпорт utils...")
    from utils import parse_date_input, format_date

    print("   ✅ utils OK")

    print("4️⃣ Імпорт handlers.reminders...")
    from handlers.reminders import add_reminder_conv

    print("   ✅ reminders OK")

    print("5️⃣ Імпорт handlers.list...")
    from handlers.list import list_handlers, list_all

    print("   ✅ list OK")

    print("6️⃣ Імпорт telegram...")
    from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup

    print("   ✅ telegram OK")

    print("7️⃣ Імпорт telegram.ext...")
    from telegram.ext import (
        Application,
        CommandHandler,
        ContextTypes,
        ConversationHandler,
        MessageHandler,
        CallbackQueryHandler,
        filters,
    )

    print("   ✅ telegram.ext OK")

    print("\n✅ Всі імпорти успішні!")
    print("🚀 Можна запускати main.py")

except Exception as e:
    print(f"\n❌ ПОМИЛКА: {e}")
    traceback.print_exc()
    sys.exit(1)