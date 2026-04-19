# handlers/reminders.py - Обробники нагадувань (ВИПРАВЛЕНО)

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ContextTypes,
    ConversationHandler,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from database import get_db_connection
from utils import parse_date_input, format_date, looks_like_reminder
from datetime import date

import logging

logger = logging.getLogger(__name__)

# Стани розмови
WAITING_FOR_REMINDER_TEXT = 1
WAITING_FOR_REMINDER_TYPE = 2
WAITING_FOR_CONFIRMATION = 3

# ❌ ВИДАЛЕНО: user_data = {} — тепер використовуємо context.user_data


async def add_reminder_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок додавання нагадування"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "➕ <b>Додати нагадування</b>\n\n"
            "Введіть дату та текст у форматі:\n"
            "<code>ДД.ММ Текст нагадування</code>\n\n"
            "Приклад: <code>15.05 Оплатити інтернет</code>\n"
            "Або: <code>15.05.2026 Зустріч з лікарем</code>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "➕ <b>Додати нагадування</b>\n\n"
            "Введіть дату та текст у форматі:\n"
            "<code>ДД.ММ Текст нагадування</code>\n\n"
            "Приклад: <code>15.05 Оплатити інтернет</code>\n"
            "Або: <code>15.05.2026 Зустріч з лікарем</code>",
            parse_mode="HTML"
        )
    return WAITING_FOR_REMINDER_TEXT


async def process_reminder_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка введеної дати та тексту"""
    user_id = update.effective_user.id
    text = update.message.text

    # Парсимо дату
    date_obj, reminder_text = parse_date_input(text)

    # Перевірка довжини тексту
    from config import MAX_TEXT_LENGTH
    if len(reminder_text) > MAX_TEXT_LENGTH:
        await update.message.reply_text(
            f"❌ <b>Текст занадто довгий!</b>\n\n"
            f"Максимум {MAX_TEXT_LENGTH} символів.\n"
            f"Ви ввели {len(reminder_text)} символів.\n"
            f"Спробуйте скоротити текст:",
            parse_mode="HTML"
        )
        return WAITING_FOR_REMINDER_TEXT

    if not date_obj or not reminder_text:
        await update.message.reply_text(
            "❌ <b>Невірний формат!</b>\n\n"
            "Використовуйте:\n"
            "<code>ДД.ММ Текст</code> (наприклад: 15.05 Оплатити інтернет)\n"
            "Спробуйте ще раз:",
            parse_mode="HTML"
        )
        return WAITING_FOR_REMINDER_TEXT

    # Перевірка чи дата не в минулому
    today = date.today()
    if date_obj < today:
        await update.message.reply_text(
            "❌ <b>Дата в минулому!</b>\n"
            f"Ви ввели: {format_date(date_obj)}\n"
            "Введіть майбутню дату:",
            parse_mode="HTML"
        )
        return WAITING_FOR_REMINDER_TEXT

    # ✅ ЗБЕРІГАЄМО В context.user_data ЗАМІСТЬ ГЛОБАЛЬНОЇ ЗМІННОЇ
    context.user_data['reminder_date'] = date_obj
    context.user_data['reminder_text'] = reminder_text

    # Питаємо тип нагадування
    keyboard = [
        [InlineKeyboardButton("🔔 Разове", callback_data="type_once")],
        [InlineKeyboardButton("🔄 Щомісячне", callback_data="type_monthly")],
        [InlineKeyboardButton("📅 Щорічне", callback_data="type_yearly")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📅 <b>Дата:</b> {format_date(date_obj)}\n"
        f"📝 <b>Текст:</b> {reminder_text}\n\n"
        f"Оберіть тип нагадування:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    return WAITING_FOR_REMINDER_TYPE


async def process_reminder_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору типу нагадування"""
    query = update.callback_query
    await query.answer()

    reminder_type = query.data.replace("type_", "")

    # ✅ ЗБЕРІГАЄМО В context.user_data
    context.user_data['reminder_type'] = reminder_type

    # Завжди запитуємо куди зберегти
    active_group = context.user_data.get('active_group')

    # Отримуємо список груп користувача
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT g.group_id, g.name 
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE gm.user_id = ?
            ORDER BY g.name
        """, (update.effective_user.id,))

        user_groups = cursor.fetchall()
    finally:
        conn.close()

    # Формуємо кнопки вибору
    keyboard = []

    # Завжди є опція "Особисте"
    keyboard.append([InlineKeyboardButton("👤 Особисте нагадування", callback_data="save_personal")])

    # Додаємо активну групу (якщо є)
    if active_group:
        keyboard.append([InlineKeyboardButton(f"👥 {active_group['name']} (активна група)",
                                              callback_data=f"save_group_{active_group['id']}")])

    # Додаємо інші групи користувача (крім активної)
    for group in user_groups:
        if not active_group or group['group_id'] != active_group['id']:
            keyboard.append(
                [InlineKeyboardButton(f"👥 {group['name']}", callback_data=f"save_group_{group['group_id']}")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Формуємо текст
    group_info = ""
    if active_group:
        group_info = f"\n👥 Активна група: {active_group['name']}"

    await query.edit_message_text(
        f"📅 <b>Дата:</b> {format_date(context.user_data['reminder_date'])}\n"
        f"📝 <b>Текст:</b> {context.user_data['reminder_text']}\n"
        f"🔔 <b>Тип:</b> {get_type_name(reminder_type)}"
        f"{group_info}\n\n"
        f"<b>Куди зберегти?</b>",
        parse_mode="HTML",
        reply_markup=reply_markup
    )
    return WAITING_FOR_CONFIRMATION


async def save_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id=None, group_id=None):
    """Збереження нагадування в базу"""
    query = update.callback_query

    if not user_id:
        user_id = update.effective_user.id

    # ✅ ОТРИМУЄМО ДАНІ З context.user_data
    data = {
        'date': context.user_data.get('reminder_date'),
        'text': context.user_data.get('reminder_text'),
        'type': context.user_data.get('reminder_type')
    }

    if not data['date'] or not data['text'] or not data['type']:
        if query:
            await query.edit_message_text("❌ Помилка: дані не знайдено. Почніть спочатку /add")
        return ConversationHandler.END

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Для щомісячних зберігаємо original_day
        original_day = data['date'].day if data['type'] == 'monthly' else None

        cursor.execute("""
            INSERT INTO reminders (user_id, group_id, text, next_date, original_day, type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            group_id,
            data['text'],
            data['date'],
            original_day,
            data['type']
        ))

        conn.commit()

        group_text = ""
        if group_id:
            cursor.execute("SELECT name FROM groups WHERE group_id = ?", (group_id,))
            group_name = cursor.fetchone()['name']
            group_text = f"\n👥 Група: {group_name}"

        type_names = {
            'once': '🔔 Разове',
            'monthly': '🔄 Щомісячне',
            'yearly': '📅 Щорічне'
        }

        message = (
            f"✅ <b>Нагадування збережено!</b>\n\n"
            f"📅 Дата: {format_date(data['date'])}\n"
            f"📝 Текст: {data['text']}\n"
            f"🔔 Тип: {type_names.get(data['type'])}{group_text}"
        )

        # Кнопки після створення
        keyboard = [
            [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

    finally:
        conn.close()
        # ✅ ОЧИЩУЄМО context.user_data
        for key in ['reminder_date', 'reminder_text', 'reminder_type']:
            if key in context.user_data:
                del context.user_data[key]


async def process_save_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка вибору куди зберегти"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id
    data = query.data

    if data == "save_personal":
        # Особисте нагадування
        await save_reminder(update, context, user_id, None)
    elif data.startswith("save_group_"):
        # Групове нагадування — отримуємо ID групи з callback_data
        group_id = int(data.replace("save_group_", ""))
        await save_reminder(update, context, user_id, group_id)

    return ConversationHandler.END


def get_type_name(type_code):
    """Отримання назви типу"""
    names = {
        'once': 'Разове',
        'monthly': 'Щомісячне',
        'yearly': 'Щорічне'
    }
    return names.get(type_code, type_code)


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування командою /cancel"""
    # ✅ ОЧИЩУЄМО context.user_data
    for key in ['reminder_date', 'reminder_text', 'reminder_type']:
        if key in context.user_data:
            del context.user_data[key]

    await update.message.reply_text("❌ Додавання скасовано.")
    return ConversationHandler.END


async def cancel_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування при натисканні інших кнопок"""
    query = update.callback_query
    await query.answer()

    # ✅ ОЧИЩУЄМО context.user_data
    for key in ['reminder_date', 'reminder_text', 'reminder_type']:
        if key in context.user_data:
            del context.user_data[key]

    # Повертаємося в меню
    await query.edit_message_text(
        "❌ Додавання скасовано.\n\n"
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
            [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
            [InlineKeyboardButton("👥 Особисті ▼", callback_data="switch_context")],
            [InlineKeyboardButton("⚙️ Налаштування", callback_data="settings")],
        ])
    )
    return ConversationHandler.END


async def quick_add_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Швидке додавання: /add 18.04 Текст нагадування"""
    user_id = update.effective_user.id

    # Отримуємо аргументи команди
    args = context.args

    if not args or len(args) < 2:
        await update.message.reply_text(
            "❌ <b>Невірний формат!</b>\n\n"
            "Використовуйте:\n"
            "<code>/add ДД.ММ Текст нагадування</code>\n\n"
            "Приклад:\n"
            "<code>/add 15.05 Оплатити інтернет</code>\n"
            "<code>/add 15.05.2026 Зустріч з лікарем</code>",
            parse_mode="HTML"
        )
        return

    # З'єднуємо всі аргументи в один текст
    full_text = " ".join(args)

    # Парсимо дату
    date_obj, reminder_text = parse_date_input(full_text)

    if not date_obj or not reminder_text:
        await update.message.reply_text(
            "❌ <b>Не вдалося розпізнати дату!</b>\n\n"
            "Використовуйте формат:\n"
            "<code>/add ДД.ММ Текст</code>\n"
            "Приклад: <code>/add 15.05 Оплатити інтернет</code>",
            parse_mode="HTML"
        )
        return

    # Перевірка чи дата не в минулому
    from datetime import date
    today = date.today()
    if date_obj < today:
        await update.message.reply_text(
            "❌ <b>Дата в минулому!</b>\n"
            f"Ви ввели: {format_date(date_obj)}\n"
            "Введіть майбутню дату.",
            parse_mode="HTML"
        )
        return

    # ✅ ЗБЕРІГАЄМО В context.user_data
    context.user_data['reminder_date'] = date_obj
    context.user_data['reminder_text'] = reminder_text

    # Питаємо тип нагадування
    keyboard = [
        [InlineKeyboardButton("🔔 Разове", callback_data="type_once")],
        [InlineKeyboardButton("🔄 Щомісячне", callback_data="type_monthly")],
        [InlineKeyboardButton("📅 Щорічне", callback_data="type_yearly")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.message.reply_text(
        f"📅 <b>Дата:</b> {format_date(date_obj)}\n"
        f"📝 <b>Текст:</b> {reminder_text}\n\n"
        f"Оберіть тип нагадування:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

    # Важливо: повертаємо стан для ConversationHandler
    return WAITING_FOR_REMINDER_TYPE


# ==================== ШВИДКЕ ДОДАВАННЯ ТЕКСТОМ (Фаза 3) ====================

async def process_quick_reminder(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Швидке додавання нагадування з тексту
    Спочатку розпізнає дату, потім питає: особисте чи групове
    """
    from utils import parse_date_input, format_date
    from database import get_db_connection
    from datetime import date

    # Перевіряємо чи це взагалі схоже на нагадування
    if not looks_like_reminder(text):
        return False

    # Парсимо дату та текст
    date_obj, reminder_text = parse_date_input(text)

    if not date_obj or not reminder_text:
        return False

    # Перевірка що дата не в минулому
    today = date.today()
    if date_obj < today:
        await update.message.reply_text(
            f"❌ <b>Дата в минулому!</b>\n"
            f"Ви ввели: {format_date(date_obj)}\n"
            f"Введіть майбутню дату.",
            parse_mode="HTML"
        )
        return True  # Повертаємо True бо це було нагадування, просто невірна дата

    # ✅ ЗБЕРІГАЄМО ДАНІ В КОНТЕКСТІ для наступного кроку
    context.user_data['quick_date'] = date_obj
    context.user_data['quick_text'] = reminder_text

    # Отримуємо список груп користувача
    user_id = update.effective_user.id
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT g.group_id, g.name 
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE gm.user_id = ?
            ORDER BY g.name
        """, (user_id,))

        user_groups = cursor.fetchall()
    finally:
        conn.close()

    # Формуємо кнопки вибору
    keyboard = []

    # Завжди є опція "Особисте"
    keyboard.append([InlineKeyboardButton("👤 Особисте нагадування", callback_data="quick_personal")])

    # Додаємо групи користувача
    for group in user_groups:
        keyboard.append(
            [InlineKeyboardButton(f"👥 {group['name']}", callback_data=f"quick_group_{group['group_id']}")])

    # Кнопка скасування
    keyboard.append([InlineKeyboardButton("❌ Скасувати", callback_data="quick_cancel")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    # Показуємо запит на вибір
    await update.message.reply_text(
        f"📅 <b>Дата:</b> {format_date(date_obj)}\n"
        f"📝 <b>Текст:</b> {reminder_text}\n\n"
        f"<b>Куди зберегти?</b>",
        parse_mode="HTML",
        reply_markup=reply_markup
    )

    return True

async def process_quick_personal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження швидкого нагадування як особистого"""
    query = update.callback_query
    await query.answer()

    # Отримуємо дані з контексту
    date_obj = context.user_data.get('quick_date')
    reminder_text = context.user_data.get('quick_text')

    if not date_obj or not reminder_text:
        await query.edit_message_text("❌ Помилка: дані не знайдено. Спробуйте ще раз.")
        return

    user_id = update.effective_user.id

    # Зберігаємо в БД
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO reminders (user_id, group_id, text, next_date, original_day, type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            None,  # Особисте
            reminder_text,
            date_obj,
            None,
            'once'
        ))
        conn.commit()

        await query.edit_message_text(
            f"✅ <b>Нагадування додано!</b>\n\n"
            f"📅 Дата: {format_date(date_obj)}\n"
            f"📝 Текст: {reminder_text}\n"
            f"👤 Особисте | 🔔 Разове",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )

    finally:
        conn.close()
        # Очищаємо контекст
        for key in ['quick_date', 'quick_text']:
            if key in context.user_data:
                del context.user_data[key]


async def process_quick_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Збереження швидкого нагадування в групу"""
    query = update.callback_query
    await query.answer()

    # Отримуємо ID групи з callback_data
    data = query.data
    group_id = int(data.replace("quick_group_", ""))

    # Отримуємо дані з контексту
    date_obj = context.user_data.get('quick_date')
    reminder_text = context.user_data.get('quick_text')

    if not date_obj or not reminder_text:
        await query.edit_message_text("❌ Помилка: дані не знайдено. Спробуйте ще раз.")
        return

    user_id = update.effective_user.id

    # Знаходимо назву групи
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("SELECT name FROM groups WHERE group_id = ?", (group_id,))
        group = cursor.fetchone()

        if not group:
            await query.edit_message_text("❌ Помилка: групу не знайдено.")
            return

        # Зберігаємо в БД
        cursor.execute("""
            INSERT INTO reminders (user_id, group_id, text, next_date, original_day, type)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            group_id,
            reminder_text,
            date_obj,
            None,
            'once'
        ))
        conn.commit()

        await query.edit_message_text(
            f"✅ <b>Нагадування додано!</b>\n\n"
            f"📅 Дата: {format_date(date_obj)}\n"
            f"📝 Текст: {reminder_text}\n"
            f"👥 Група: {group['name']} | 🔔 Разове",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Нагадування групи", callback_data="my_reminders")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )

    finally:
        conn.close()
        # Очищаємо контекст
        for key in ['quick_date', 'quick_text']:
            if key in context.user_data:
                del context.user_data[key]


async def process_quick_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування швидкого додавання"""
    query = update.callback_query
    await query.answer()

    # Очищаємо контекст
    for key in ['quick_date', 'quick_text']:
        if key in context.user_data:
            del context.user_data[key]

    await query.edit_message_text(
        "❌ Додавання скасовано.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
        ])
    )

# ConversationHandler для додавання нагадування
add_reminder_conv = ConversationHandler(
    entry_points=[
        CommandHandler("add", quick_add_command),
        CallbackQueryHandler(add_reminder_start, pattern="^add_reminder$")
    ],
    states={
        WAITING_FOR_REMINDER_TEXT: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_reminder_text),
            CallbackQueryHandler(add_reminder_start, pattern="^add_reminder$")
        ],
        WAITING_FOR_REMINDER_TYPE: [
            CallbackQueryHandler(process_reminder_type, pattern="^type_"),
            CallbackQueryHandler(add_reminder_start, pattern="^add_reminder$")
        ],
        WAITING_FOR_CONFIRMATION: [
            CallbackQueryHandler(process_save_location, pattern="^save_personal$"),
            CallbackQueryHandler(process_save_location, pattern="^save_group_"),
            CallbackQueryHandler(add_reminder_start, pattern="^add_reminder$")
        ],
    },
    fallbacks=[
        CommandHandler("cancel", cancel),
        CallbackQueryHandler(cancel_callback, pattern="^(back_to_menu|my_reminders|settings|switch_context)$")
    ],
    per_message=False
)