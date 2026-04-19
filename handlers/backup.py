# handlers/backup.py - Автоматичний backup бази даних

import os
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import ContextTypes, CallbackQueryHandler

from config import ADMIN_ID, DB_PATH

logger = logging.getLogger(__name__)


async def auto_backup_job(context: ContextTypes.DEFAULT_TYPE):
    """
    Щоденний автоматичний backup бази даних
    Відправляє файл .db адміністратору о 6:30 UTC
    """
    try:
        # Перевіряємо чи існує файл БД
        if not os.path.exists(DB_PATH):
            logger.error(f"❌ Файл БД не знайдено: {DB_PATH}")
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🚨 <b>Помилка backup!</b>\n\n"
                     f"Файл бази даних не знайдено: {DB_PATH}\n"
                     f"Час: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
            return

        # Отримуємо інформацію про файл
        file_size = os.path.getsize(DB_PATH)
        file_size_mb = file_size / (1024 * 1024)
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")

        logger.info(f"📦 Створення backup: {DB_PATH} ({file_size_mb:.2f} MB)")

        # Відправляємо файл адміністратору
        with open(DB_PATH, 'rb') as db_file:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=db_file,
                filename=f"memoremindme_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
                caption=(
                    f"📦 <b>Автоматичний backup</b>\n\n"
                    f"📅 Дата: {current_time}\n"
                    f"📊 Розмір: {file_size_mb:.2f} MB\n"
                    f"✅ База даних успішно збережена"
                ),
                parse_mode="HTML"
            )

        logger.info("✅ Backup успішно відправлено адміністратору")

    except Exception as e:
        error_msg = f"❌ Помилка при створенні backup: {str(e)}"
        logger.error(error_msg)

        # Повідомляємо адміна про помилку
        try:
            await context.bot.send_message(
                chat_id=ADMIN_ID,
                text=f"🚨 <b>Помилка backup!</b>\n\n"
                     f"{error_msg}\n"
                     f"Час: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
                parse_mode="HTML"
            )
        except Exception as notify_error:
            logger.error(f"Не вдалося повідомити адміна про помилку backup: {notify_error}")


async def backup_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """
    Ручний backup за кнопкою в меню налаштувань
    Доступно тільки для адміністратора
    """
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Перевіряємо чи це адміністратор
    if user_id != ADMIN_ID:
        await query.edit_message_text(
            "❌ <b>Доступ заборонено!</b>\n\n"
            "Ця функція доступна тільки адміністратору.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
            ])
        )
        return

    try:
        # Перевіряємо чи існує файл
        if not os.path.exists(DB_PATH):
            await query.edit_message_text(
                "❌ <b>Помилка!</b>\n\n"
                f"Файл бази даних не знайдено: {DB_PATH}",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
                ])
            )
            return

        # Отримуємо інформацію про файл
        file_size = os.path.getsize(DB_PATH)
        file_size_mb = file_size / (1024 * 1024)
        current_time = datetime.now().strftime("%d.%m.%Y %H:%M")

        # Відправляємо файл
        with open(DB_PATH, 'rb') as db_file:
            await context.bot.send_document(
                chat_id=ADMIN_ID,
                document=db_file,
                filename=f"memoremindme_manual_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
                caption=(
                    f"🗄 <b>Ручний backup</b>\n\n"
                    f"👤 Запитано користувачем: {update.effective_user.username or user_id}\n"
                    f"📅 Дата: {current_time}\n"
                    f"📊 Розмір: {file_size_mb:.2f} MB"
                ),
                parse_mode="HTML"
            )

        # Повідомлення про успіх
        await query.edit_message_text(
            "✅ <b>Backup створено!</b>\n\n"
            f"📊 Розмір файлу: {file_size_mb:.2f} MB\n"
            f"📅 Час: {current_time}\n\n"
            f"Файл відправлено вам в особисті повідомлення.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад до налаштувань", callback_data="settings")]
            ])
        )

    except Exception as e:
        logger.error(f"Помилка ручного backup: {e}")
        await query.edit_message_text(
            f"❌ <b>Помилка при створенні backup!</b>\n\n"
            f"{str(e)}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Назад", callback_data="settings")]
            ])
        )


# Обробник для імпорту в main.py
backup_handler = CallbackQueryHandler(backup_button_handler, pattern="^download_backup$")