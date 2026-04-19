# handlers/list.py - Перегляд нагадувань з пагінацією

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler

from database import get_db_connection
from utils import format_date, get_week_dates
from datetime import date, timedelta
from utils import check_cooldown  # ← ДОДАНО імпорт

REMINDERS_PER_PAGE = 5  # Кількість нагадувань на сторінці


async def list_reminders(update: Update, context: ContextTypes.DEFAULT_TYPE, period="all", page=0):
    """Показ нагадувань за період з пагінацією та компактними кнопками"""
    user_id = update.effective_user.id
    active_group = context.user_data.get('active_group')

    query = update.callback_query
    if query:
        await query.answer()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        today = date.today()

        # Формуємо умову для дати
        if period == "today":
            date_filter = "AND r.next_date = ?"
            params = [today]
            title = "📅 Сьогодні"
        elif period == "week":
            week_dates = get_week_dates(today)
            date_filter = "AND r.next_date BETWEEN ? AND ?"
            params = [week_dates[0], week_dates[6]]
            title = "📆 Цей тиждень"
        elif period == "month":
            first_day = today.replace(day=1)
            if today.month == 12:
                last_day = today.replace(day=31)
            else:
                next_month = today.replace(month=today.month + 1, day=1)
                last_day = next_month - timedelta(days=1)
            date_filter = "AND r.next_date BETWEEN ? AND ?"
            params = [first_day, last_day]
            title = "🗓️ Цей місяць"
        else:
            date_filter = ""
            params = []
            title = "📋 Всі нагадування"

        # Формуємо базовий запит
        if active_group:
            base_params = [active_group['id']]
            group_filter = "AND r.group_id = ?"
        else:
            base_params = [user_id, user_id]
            group_filter = """
                AND (
                    (r.group_id IS NULL AND r.user_id = ?)
                    OR 
                    (r.group_id IN (
                        SELECT group_id FROM group_members WHERE user_id = ?
                    ))
                )
            """

        all_params = base_params + params

        # Отримуємо всі нагадування
        cursor.execute(f"""
            SELECT r.*, g.name as group_name, u.username as creator_name
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE 1=1 {group_filter} {date_filter}
            ORDER BY r.next_date
        """, all_params)

        all_reminders = cursor.fetchall()

        # Конвертуємо дати
        converted_reminders = []
        for rem in all_reminders:
            rem_dict = dict(rem)
            if isinstance(rem_dict['next_date'], str):
                rem_dict['next_date'] = date.fromisoformat(rem_dict['next_date'])
            converted_reminders.append(rem_dict)

        reminders = converted_reminders
        total = len(reminders)

        if not reminders:
            # Порожній список
            if active_group:
                message = f"{title} — {active_group['name']}\n\nНемає нагадувань у цій групі."
            else:
                message = f"{title}\n\nНемає нагадувань."

            keyboard = [
                [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
                [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)

            if query:
                await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
            else:
                await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
            return

        # === ПАГІНАЦІЯ ===
        total_pages = (total + REMINDERS_PER_PAGE - 1) // REMINDERS_PER_PAGE

        if page < 0:
            page = 0
        if page >= total_pages:
            page = total_pages - 1

        start_idx = page * REMINDERS_PER_PAGE
        end_idx = start_idx + REMINDERS_PER_PAGE
        page_reminders = reminders[start_idx:end_idx]

        # === ФОРМУВАННЯ ПОВІДОМЛЕННЯ З НОМЕРАМИ ===
        type_emoji = {
            'once': '🔔',
            'monthly': '🔄',
            'yearly': '📅'
        }

        # Дні тижня
        weekdays = {
            0: 'пн', 1: 'вт', 2: 'ср', 3: 'чт',
            4: 'пт', 5: 'сб', 6: 'нд'
        }

        # Заголовок
        if active_group:
            header = f"{title} — {active_group['name']} ({total})"
        else:
            header = f"{title} ({total})"

        message = f"<b>{header}</b>\n"
        message += f"📄 Сторінка {page + 1} з {total_pages}\n\n"

        # Формуємо список з номерами 1️⃣-5️⃣
        for idx, rem in enumerate(page_reminders, start=1):
            icon = type_emoji.get(rem['type'], '🔔')
            rem_date = rem['next_date']
            date_str = f"{rem_date.day:02d}.{rem_date.month:02d}"

            # Додаємо день тижня для тижневого перегляду
            if period == "week":
                weekday = weekdays[rem_date.weekday()]
                date_str = f"{date_str} ({weekday})"

            # Основний рядок: "1️⃣ 15.04: Текст нагадування"
            global_num = start_idx + idx
            line = f"{idx}️⃣ {date_str}: {rem['text']}"

            # Додаємо позначку групи якщо потрібно
            if rem.get('group_name') and not active_group:
                line += f"\n   👥 {rem['group_name']}"
            elif not rem.get('group_name') and not active_group:
                line += f"\n   👤 Особисте"

            message += line + "\n\n"

        # === ФОРМУВАННЯ КНОПОК ===
        keyboard = []

        # Рядок з номерами нагадувань [1️⃣] [2️⃣] [3️⃣] [4️⃣] [5️⃣]
        number_buttons = []
        for idx, rem in enumerate(page_reminders, start=1):
            global_num = start_idx + idx
            number_buttons.append(
                InlineKeyboardButton(
                    f"{idx}️⃣",
                    callback_data=f"view_reminder_{rem['reminder_id']}_period_{period}_page_{page}"
                )
            )
        keyboard.append(number_buttons)

        # Рядок навігації по сторінках
        nav_buttons = []
        if page > 0:
            nav_buttons.append(InlineKeyboardButton(
                f"◀️ Сторінка {page}",
                callback_data=f"page_{period}_{page - 1}"
            ))
        if page < total_pages - 1:
            nav_buttons.append(InlineKeyboardButton(
                f"Сторінка {page + 2} ▶️",
                callback_data=f"page_{period}_{page + 1}"
            ))

        if nav_buttons:
            # Якщо одна кнопка — розтягуємо, якщо дві — поруч
            keyboard.append(nav_buttons)

        # Рядок додавання та меню
        keyboard.append([InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")])
        keyboard.append([InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        if query:
            await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
        else:
            await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)

    finally:
        conn.close()


async def list_today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Сьогодні"""
    # Отримуємо сторінку з callback_data, якщо є
    query = update.callback_query
    if query and query.data.startswith("page_today_"):
        page = int(query.data.split("_")[-1])
    else:
        page = 0
    await list_reminders(update, context, "today", page)


async def list_week(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Цей тиждень"""
    query = update.callback_query
    if query and query.data.startswith("page_week_"):
        page = int(query.data.split("_")[-1])
    else:
        page = 0
    await list_reminders(update, context, "week", page)


async def list_month(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Цей місяць"""
    query = update.callback_query
    if query and query.data.startswith("page_month_"):
        page = int(query.data.split("_")[-1])
    else:
        page = 0
    await list_reminders(update, context, "month", page)


async def list_all(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Всі"""
    query = update.callback_query
    if query and query.data.startswith("page_all_"):
        page = int(query.data.split("_")[-1])
    else:
        page = 0
    await list_reminders(update, context, "all", page)


# ==================== ОБРОБНИКИ ДЕТАЛЬНОГО ПЕРЕГЛЯДУ ====================

# ← ВИПРАВЛЕНО: Прибрано зайвий відступ перед async def
async def view_reminder_detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ детальної інформації про нагадування"""
    query = update.callback_query
    user_id = update.effective_user.id

    # Антиспам
    if not check_cooldown(user_id, "view_reminder", cooldown_seconds=1):
        await query.answer("⏱ Занадто швидко!", show_alert=False)
        return

    await query.answer()

    # Парсимо callback_data: view_reminder_{id}_period_{period}_page_{page}
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
            SELECT r.*, g.name as group_name, u.username as creator_name
            FROM reminders r
            LEFT JOIN groups g ON r.group_id = g.group_id
            LEFT JOIN users u ON r.user_id = u.user_id
            WHERE r.reminder_id = ?
        """, (reminder_id,))

        reminder = cursor.fetchone()

        if not reminder:
            await query.edit_message_text(
                "❌ Нагадування не знайдено.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
                ]])
            )
            return

        # Перевіряємо права доступу
        has_access = False
        is_creator = reminder['user_id'] == user_id

        if reminder['group_id'] is None:
            # Особисте нагадування — тільки автор
            has_access = is_creator
        else:
            # Групове — перевіряємо чи є в групі
            cursor.execute("""
                SELECT 1 FROM group_members 
                WHERE group_id = ? AND user_id = ?
            """, (reminder['group_id'], user_id))
            has_access = cursor.fetchone() is not None

        if not has_access:
            await query.edit_message_text(
                "❌ У вас немає доступу до цього нагадування.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")
                ]])
            )
            return

        # Формуємо детальне повідомлення
        type_names = {
            'once': '🔔 Разове',
            'monthly': '🔄 Щомісячне',
            'yearly': '📅 Щорічне'
        }

        rem_date = reminder['next_date']
        if isinstance(rem_date, str):
            rem_date = date.fromisoformat(rem_date)

        # Визначаємо тип (особисте/групове)
        if reminder['group_id']:
            context_type = f"👥 Група: {reminder['group_name']}"
        else:
            context_type = "👤 Особисте"

        message = (
            f"📝 <b>Деталі нагадування</b>\n\n"
            f"📅 <b>Дата:</b> {format_date(rem_date)}\n"
            f"📝 <b>Текст:</b> {reminder['text']}\n"
            f"🔔 <b>Тип:</b> {type_names.get(reminder['type'], reminder['type'])}\n"
            f"{context_type}"
        )

        # Формуємо кнопки
        keyboard = [
            [InlineKeyboardButton("✏️ Редагувати текст",
                callback_data=f"edit_text_{reminder_id}_period_{period}_page_{page}")],
            [InlineKeyboardButton("🗑️ Видалити",
                callback_data=f"confirm_delete_{reminder_id}_period_{period}_page_{page}")],
            [InlineKeyboardButton("🔙 Назад до списку",
                callback_data=f"back_to_list_{period}_{page}")]
        ]

        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)

    finally:
        conn.close()


async def back_to_reminders_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Повернення до списку нагадувань зі збереженням сторінки"""
    query = update.callback_query
    await query.answer()

    # Парсимо: back_to_list_{period}_{page}
    data = query.data
    parts = data.split('_')
    period = parts[3]
    page = int(parts[4])

    # Викликаємо list_reminders з збереженою сторінкою
    await list_reminders(update, context, period, page)


# Оновлений список обробників
list_handlers = [
    # Перегляд списків
    CallbackQueryHandler(list_today, pattern="^list_today$"),
    CallbackQueryHandler(list_today, pattern="^page_today_"),
    CallbackQueryHandler(list_week, pattern="^list_week$"),
    CallbackQueryHandler(list_week, pattern="^page_week_"),
    CallbackQueryHandler(list_month, pattern="^list_month$"),
    CallbackQueryHandler(list_month, pattern="^page_month_"),
    CallbackQueryHandler(list_all, pattern="^list_all$"),
    CallbackQueryHandler(list_all, pattern="^page_all_"),
    # Детальний перегляд та навігація
    CallbackQueryHandler(view_reminder_detail, pattern="^view_reminder_"),
    CallbackQueryHandler(back_to_reminders_list, pattern="^back_to_list_"),
]