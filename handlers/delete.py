# handlers/delete.py - Видалення нагадувань (оновлена версія)

from datetime import date
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_db_connection
from utils import format_date


async def confirm_delete_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок видалення — показ підтвердження з деталями"""
    query = update.callback_query
    await query.answer()

    # Парсимо: confirm_delete_{id}_period_{period}_page_{page}
    data = query.data
    parts = data.split('_')
    reminder_id = int(parts[2])
    period = parts[4]
    page = int(parts[6])

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримуємо інформацію про нагадування
        cursor.execute("""
            SELECT r.*, g.name as group_name, g.group_id
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            WHERE r.reminder_id = ?
        """, (reminder_id,))

        reminder = cursor.fetchone()

        if not reminder:
            await query.edit_message_text(
                "❌ Нагадування не знайдено або вже видалено.",
                parse_mode="HTML"
            )
            return

        # Перевіряємо права на видалення
        can_delete = False

        if reminder['user_id'] == user_id:
            # Це своє нагадування
            can_delete = True
        elif reminder['group_id']:
            # Це групове нагадування — перевіримо чи користувач адмін
            cursor.execute("""
                SELECT is_admin FROM group_members 
                WHERE group_id = ? AND user_id = ?
            """, (reminder['group_id'], user_id))
            member = cursor.fetchone()
            if member and member['is_admin']:
                can_delete = True

        if not can_delete:
            await query.edit_message_text(
                "❌ У вас немає прав для видалення цього нагадування.\n"
                "Видалити може тільки автор або адміністратор групи.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад до списку",
                        callback_data=f"back_to_list_{period}_{page}")
                ]])
            )
            return

        # Конвертуємо дату
        next_date = reminder['next_date']
        if isinstance(next_date, str):
            next_date = date.fromisoformat(next_date)

        # Формуємо текст підтвердження
        type_names = {
            'once': '🔔 Разове',
            'monthly': '🔄 Щомісячне',
            'yearly': '📅 Щорічне'
        }

        group_text = ""
        if reminder['group_name']:
            group_text = f"\n👥 Група: {reminder['group_name']}"

        confirm_text = (
            f"🗑️ <b>Підтвердження видалення</b>\n\n"
            f"📅 Дата: {format_date(next_date)}\n"
            f"📝 Текст: {reminder['text']}\n"
            f"🔔 Тип: {type_names.get(reminder['type'], reminder['type'])}"
            f"{group_text}\n\n"
            f"⚠️ Ви впевнені, що хочете видалити це нагадування?"
        )

        # Кнопки підтвердження
        keyboard = [
            [
                InlineKeyboardButton("✅ Так, видалити",
                    callback_data=f"execute_delete_{reminder_id}_period_{period}_page_{page}"),
                InlineKeyboardButton("❌ Ні, скасувати",
                    callback_data=f"back_to_list_{period}_{page}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            confirm_text,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


async def execute_delete(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Виконання видалення"""
    query = update.callback_query
    await query.answer()

    # Парсимо: execute_delete_{id}_period_{period}_page_{page}
    data = query.data
    parts = data.split('_')
    reminder_id = int(parts[2])
    period = parts[4]
    page = int(parts[6])

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Перевіряємо ще раз права
        cursor.execute("""
            SELECT r.user_id, r.group_id, r.text, g.name as group_name
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            WHERE r.reminder_id = ?
        """, (reminder_id,))

        reminder = cursor.fetchone()

        if not reminder:
            await query.edit_message_text(
                "❌ Нагадування вже видалено.",
                parse_mode="HTML"
            )
            return

        # Видаляємо нагадування
        cursor.execute("DELETE FROM reminders WHERE reminder_id = ?", (reminder_id,))
        conn.commit()

        # Формуємо повідомлення про успіх
        group_text = ""
        if reminder['group_name']:
            group_text = f" з групи \"{reminder['group_name']}\""

        await query.edit_message_text(
            f"✅ <b>Нагадування видалено!</b>\n\n"
            f"📝 \"{reminder['text']}\"{group_text}",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Повернутися до списку",
                    callback_data=f"back_to_list_{period}_{page}")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )

    finally:
        conn.close()


# Список обробників для імпорту в main.py
delete_handlers = [
    CallbackQueryHandler(confirm_delete_start, pattern="^confirm_delete_"),
    CallbackQueryHandler(execute_delete, pattern="^execute_delete_"),
]