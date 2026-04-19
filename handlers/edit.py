# handlers/edit.py - Редагування тексту нагадувань

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, MessageHandler, filters, ConversationHandler, CommandHandler

from database import get_db_connection
from utils import format_date
from datetime import date

# Стани розмови для редагування
WAITING_FOR_NEW_TEXT = 1


async def start_edit_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок редагування тексту — показуємо поточний текст і просимо новий"""
    query = update.callback_query
    await query.answer()

    # Парсимо: edit_text_{id}_period_{period}_page_{page}
    data = query.data
    parts = data.split('_')
    reminder_id = int(parts[2])
    period = parts[4]
    page = int(parts[6])

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримуємо нагадування з перевіркою прав
        cursor.execute("""
            SELECT r.*, g.name as group_name
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            WHERE r.reminder_id = ?
        """, (reminder_id,))

        reminder = cursor.fetchone()

        if not reminder:
            await query.edit_message_text(
                "❌ Нагадування не знайдено.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        # Перевіряємо права (тільки автор може редагувати)
        if reminder['user_id'] != user_id:
            await query.edit_message_text(
                "❌ Редагувати може тільки автор нагадування.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад до списку",
                        callback_data=f"back_to_list_{period}_{page}")
                ]])
            )
            return ConversationHandler.END

        # Зберігаємо дані в контексті
        context.user_data['edit_reminder_id'] = reminder_id
        context.user_data['edit_period'] = period
        context.user_data['edit_page'] = page
        context.user_data['edit_old_text'] = reminder['text']

        # Показуємо запит на новий текст
        await query.edit_message_text(
            f"✏️ <b>Редагування тексту</b>\n\n"
            f"Поточний текст:\n"
            f"<code>{reminder['text']}</code>\n\n"
            f"Введіть новий текст (максимум 200 символів):\n"
            f"Або /cancel для скасування",
            parse_mode="HTML"
        )

        return WAITING_FOR_NEW_TEXT

    finally:
        conn.close()


async def process_new_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка нового тексту"""
    new_text = update.message.text.strip()
    user_id = update.effective_user.id

    # Перевірка довжини
    from config import MAX_TEXT_LENGTH
    if len(new_text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(
            f"❌ <b>Текст занадто довгий!</b>\n\n"
            f"Максимум {MAX_TEXT_LENGTH} символів.\n"
            f"Ви ввели {len(new_text)} символів.\n"
            f"Спробуйте ще раз або /cancel:",
            parse_mode="HTML"
        )
        return WAITING_FOR_NEW_TEXT

    # Отримуємо дані з контексту
    reminder_id = context.user_data.get('edit_reminder_id')
    period = context.user_data.get('edit_period')
    page = context.user_data.get('edit_page')

    if not reminder_id:
        await update.message.reply_text(
            "❌ Помилка: дані не знайдено. Почніть спочатку.",
            parse_mode="HTML"
        )
        return ConversationHandler.END

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Оновлюємо текст в БД
        cursor.execute("""
            UPDATE reminders SET text = ? WHERE reminder_id = ? AND user_id = ?
        """, (new_text, reminder_id, user_id))

        conn.commit()

        # Отримуємо оновлені дані для показу
        cursor.execute("""
            SELECT r.*, g.name as group_name
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            WHERE r.reminder_id = ?
        """, (reminder_id,))

        reminder = cursor.fetchone()

        if not reminder:
            await update.message.reply_text(
                "❌ Помилка: нагадування не знайдено після оновлення.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        # Формуємо повідомлення про успіх
        type_names = {
            'once': '🔔 Разове',
            'monthly': '🔄 Щомісячне',
            'yearly': '📅 Щорічне'
        }

        rem_date = reminder['next_date']
        if isinstance(rem_date, str):
            rem_date = date.fromisoformat(rem_date)

        context_type = f"👥 Група: {reminder['group_name']}" if reminder['group_id'] else "👤 Особисте"

        message = (
            f"✅ <b>Текст оновлено!</b>\n\n"
            f"📅 <b>Дата:</b> {format_date(rem_date)}\n"
            f"📝 <b>Текст:</b> {reminder['text']}\n"
            f"🔔 <b>Тип:</b> {type_names.get(reminder['type'], reminder['type'])}\n"
            f"{context_type}"
        )

        keyboard = [
            [InlineKeyboardButton("✏️ Редагувати ще раз",
                callback_data=f"edit_text_{reminder_id}_period_{period}_page_{page}")],
            [InlineKeyboardButton("🔙 Назад до списку",
                callback_data=f"back_to_list_{period}_{page}")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
        ]

        await update.message.reply_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    finally:
        conn.close()
        # Очищаємо контекст
        for key in ['edit_reminder_id', 'edit_period', 'edit_page', 'edit_old_text']:
            if key in context.user_data:
                del context.user_data[key]

    return ConversationHandler.END


async def cancel_edit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування редагування"""
    # Очищаємо контекст
    for key in ['edit_reminder_id', 'edit_period', 'edit_page', 'edit_old_text']:
        if key in context.user_data:
            del context.user_data[key]

    await update.message.reply_text(
        "❌ Редагування скасовано.",
        parse_mode="HTML"
    )
    return ConversationHandler.END


# ConversationHandler для редагування
edit_text_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(start_edit_text, pattern="^edit_text_")
    ],
    states={
        WAITING_FOR_NEW_TEXT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_new_text)
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel_edit)
    ],
    per_message=False
)

# Список обробників для імпорту в main.py
edit_handlers = [edit_text_conv]