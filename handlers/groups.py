# handlers/groups.py - Управління групами

import random
import string
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
from config import MAX_GROUPS_PER_USER, MAX_MEMBERS_PER_GROUP, MAX_GROUP_NAME_LENGTH
from utils import check_cooldown  # ← ДОДАНО імпорт

# Стани розмови для створення групи
WAITING_FOR_GROUP_NAME = 1
WAITING_FOR_JOIN_CODE = 2

# Тимчасове сховище для створення групи
group_creation_data = {}


def generate_group_code():
    """Генерація випадкового коду групи (6 символів: літери + цифри)"""
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))


# ==================== СТВОРЕННЯ ГРУПИ ====================

async def create_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок створення групи"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "➕ <b>Створення групи</b>\n\n"
            "Введіть назву групи (до 30 символів):\n"
            "Наприклад: <code>Сім'я</code> або <code>Робочі завдання</code>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "➕ <b>Створення групи</b>\n\n"
            "Введіть назву групи (до 30 символів):",
            parse_mode="HTML"
        )
    return WAITING_FOR_GROUP_NAME


async def process_group_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка назви групи та показ головного меню"""
    user_id = update.effective_user.id
    name = update.message.text.strip()

    # Перевірка довжини
    if len(name) > MAX_GROUP_NAME_LENGTH:
        await update.message.reply_text(
            f"❌ Назва занадто довга (максимум {MAX_GROUP_NAME_LENGTH} символів).\n"
            f"Ви ввели {len(name)} символів. Спробуйте ще раз:",
            parse_mode="HTML"
        )
        return WAITING_FOR_GROUP_NAME

    if len(name) < 2:
        await update.message.reply_text(
            "❌ Назва занадто коротка (мінімум 2 символи).\n"
            "Спробуйте ще раз:",
            parse_mode="HTML"
        )
        return WAITING_FOR_GROUP_NAME

    # Перевірка ліміту груп для користувача
    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT COUNT(*) as count FROM groups WHERE created_by = ?
        """, (user_id,))
        result = cursor.fetchone()

        if result['count'] >= MAX_GROUPS_PER_USER:
            await update.message.reply_text(
                f"❌ Ви вже створили максимальну кількість груп ({MAX_GROUPS_PER_USER}).\n"
                f"Видаліть існуючу групу, щоб створити нову.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        # Генеруємо унікальний код
        code = generate_group_code()
        while True:
            cursor.execute("SELECT 1 FROM groups WHERE code = ?", (code,))
            if not cursor.fetchone():
                break
            code = generate_group_code()

        # Створюємо групу
        cursor.execute("""
            INSERT INTO groups (name, code, created_by)
            VALUES (?, ?, ?)
        """, (name, code, user_id))

        group_id = cursor.lastrowid

        # Додаємо створювача як адміна групи
        cursor.execute("""
            INSERT INTO group_members (group_id, user_id, is_admin)
            VALUES (?, ?, 1)
        """, (group_id, user_id))

        conn.commit()

        # === ВІДПРАВЛЯЄМО ПОВІДОМЛЕННЯ ПРО УСПІХ ===
        await update.message.reply_text(
            f"✅ <b>Групу створено!</b>\n\n"
            f"📛 <b>Назва:</b> {name}\n"
            f"🔑 <b>Код для приєднання:</b> <code>{code}</code>\n\n"
            f"Поділіться цим кодом з тими, кого хочете запросити.\n"
            f"Вони можуть приєднатися через меню груп.",
            parse_mode="HTML"
        )

        # === АВТОМАТИЧНО ВІДКРИВАЄМО ГОЛОВНЕ МЕНЮ ===
        # Імпортуємо функцію показу меню з main.py
        from main import show_main_menu

        await show_main_menu(update, context)

    finally:
        conn.close()

    return ConversationHandler.END


# ==================== ПРИЄДНАННЯ ДО ГРУПИ ====================

async def join_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок приєднання до групи"""
    query = update.callback_query
    if query:
        await query.answer()
        await query.edit_message_text(
            "🔗 <b>Приєднання до групи</b>\n\n"
            "Введіть код групи (6 символів):\n"
            "Наприклад: <code>ABC123</code>",
            parse_mode="HTML"
        )
    else:
        await update.message.reply_text(
            "🔗 <b>Приєднання до групи</b>\n\n"
            "Введіть код групи (6 символів):",
            parse_mode="HTML"
        )
    return WAITING_FOR_JOIN_CODE


async def process_join_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка коду приєднання та показ головного меню"""
    user_id = update.effective_user.id
    code = update.message.text.strip().upper()

    # Перевірка формату коду
    if len(code) != 6:
        await update.message.reply_text(
            "❌ Код має містити рівно 6 символів (літери та цифри).\n"
            "Спробуйте ще раз:",
            parse_mode="HTML"
        )
        return WAITING_FOR_JOIN_CODE

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Шукаємо групу за кодом
        cursor.execute("""
            SELECT * FROM groups WHERE code = ?
        """, (code,))
        group = cursor.fetchone()

        if not group:
            await update.message.reply_text(
                "❌ Групу з таким кодом не знайдено.\n"
                "Перевірте код і спробуйте ще раз:",
                parse_mode="HTML"
            )
            return WAITING_FOR_JOIN_CODE

        group_id = group['group_id']

        # Перевірка чи вже є в групі
        cursor.execute("""
            SELECT 1 FROM group_members WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))
        if cursor.fetchone():
            await update.message.reply_text(
                f"❌ Ви вже є учасником групи <b>{group['name']}</b>!",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        # Перевірка ліміту учасників
        cursor.execute("""
            SELECT COUNT(*) as count FROM group_members WHERE group_id = ?
        """, (group_id,))
        member_count = cursor.fetchone()['count']

        if member_count >= MAX_MEMBERS_PER_GROUP:
            await update.message.reply_text(
                f"❌ Група <b>{group['name']}</b> заповнена (максимум {MAX_MEMBERS_PER_GROUP} учасників).\n"
                f"Зверніться до адміністратора групи.",
                parse_mode="HTML"
            )
            return ConversationHandler.END

        # Додаємо користувача до групи
        cursor.execute("""
            INSERT INTO group_members (group_id, user_id, is_admin)
            VALUES (?, ?, 0)
        """, (group_id, user_id))

        conn.commit()

        # === ВІДПРАВЛЯЄМО ПОВІДОМЛЕННЯ ПРО УСПІХ ===
        await update.message.reply_text(
            f"✅ <b>Ви приєдналися до групи!</b>\n\n"
            f"📛 <b>Назва:</b> {group['name']}\n"
            f"👥 Тепер ви можете додавати нагадування для цієї групи.",
            parse_mode="HTML"
        )

        # === АВТОМАТИЧНО ВІДКРИВАЄМО ГОЛОВНЕ МЕНЮ ===
        from main import show_main_menu

        await show_main_menu(update, context)

    finally:
        conn.close()

    return ConversationHandler.END


# ==================== ВИХІД З ГРУПИ ====================

async def leave_group_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Початок виходу з групи — показуємо список груп для виходу"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримуємо всі групи користувача (крім тих, де він адмін — їх не можна покинути, тільки видалити)
        cursor.execute("""
            SELECT g.group_id, g.name, g.code, gm.is_admin
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE gm.user_id = ? AND gm.is_admin = 0
            ORDER BY g.name
        """, (user_id,))

        groups = cursor.fetchall()

        if not groups:
            await query.edit_message_text(
                "❌ <b>Немає груп для виходу</b>\n\n"
                "Ви не є учасником жодної групи (крім тих, де ви адміністратор).\n"
                "Адміністратор не може просто вийти — тільки видалити групу.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="my_groups")]
                ])
            )
            return

        # Формуємо кнопки груп
        keyboard = []
        for group in groups:
            keyboard.append([
                InlineKeyboardButton(
                    f"🚪 {group['name']}",
                    callback_data=f"leave_group_{group['group_id']}"
                )
            ])

        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="my_groups")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🚪 <b>Вихід з групи</b>\n\n"
            "Оберіть групу, з якої хочете вийти:\n"
            "(Групи, де ви адміністратор, не відображаються — їх можна тільки видалити)",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


async def confirm_leave_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Підтвердження виходу з групи"""
    query = update.callback_query
    await query.answer()

    # Отримуємо ID групи з callback_data (формат: leave_group_123)
    data = query.data
    group_id = int(data.replace("leave_group_", ""))

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Перевіряємо чи група існує і чи користувач є учасником (не адмін)
        cursor.execute("""
            SELECT g.name, gm.is_admin
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE g.group_id = ? AND gm.user_id = ?
        """, (group_id, user_id))

        group = cursor.fetchone()

        if not group:
            await query.edit_message_text(
                "❌ Групу не знайдено або ви не є її учасником.",
                parse_mode="HTML"
            )
            return

        if group['is_admin']:
            await query.edit_message_text(
                "❌ Ви адміністратор цієї групи. Адмін не може вийти — тільки видалити групу.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🗑️ Видалити групу", callback_data="delete_group_menu")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="my_groups")]
                ])
            )
            return

        # Видаляємо користувача з групи
        cursor.execute("""
            DELETE FROM group_members 
            WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))

        # Видаляємо всі нагадування цього користувача в цій групі
        cursor.execute("""
            DELETE FROM reminders 
            WHERE group_id = ? AND user_id = ?
        """, (group_id, user_id))

        conn.commit()

        # Якщо це була активна група — очищаємо контекст
        active_group = context.user_data.get('active_group')
        if active_group and active_group['id'] == group_id:
            del context.user_data['active_group']

        await query.edit_message_text(
            f"✅ <b>Ви вийшли з групи!</b>\n\n"
            f"📛 Група: {group['name']}\n\n"
            f"Ваші нагадування в цій групі також видалені.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Мої групи", callback_data="my_groups")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )

    finally:
        conn.close()


# ==================== ВИДАЛЕННЯ ГРУПИ (тільки для адміна) ====================

async def delete_group_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Меню видалення групи — показуємо групи, де користувач адмін"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримуємо групи, де користувач є адміністратором
        cursor.execute("""
            SELECT g.group_id, g.name, g.code,
                   (SELECT COUNT(*) FROM group_members WHERE group_id = g.group_id) as member_count
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE gm.user_id = ? AND gm.is_admin = 1
            ORDER BY g.name
        """, (user_id,))

        groups = cursor.fetchall()

        if not groups:
            await query.edit_message_text(
                "❌ <b>Немає груп для видалення</b>\n\n"
                "Ви не є адміністратором жодної групи.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔙 Назад", callback_data="my_groups")]
                ])
            )
            return

        # Формуємо кнопки груп
        keyboard = []
        for group in groups:
            keyboard.append([
                InlineKeyboardButton(
                    f"🗑️ {group['name']} ({group['member_count']} учасників)",
                    callback_data=f"delete_group_{group['group_id']}"
                )
            ])

        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="my_groups")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "🗑️ <b>Видалення групи</b>\n\n"
            "⚠️ <b>Увага!</b> Видалення групи призведе до:\n"
            "• Видалення ВСІХ нагадувань групи\n"
            "• Видалення ВСІХ учасників з групи\n"
            "• Групу не можна буде відновити!\n\n"
            "Оберіть групу для видалення:",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


async def confirm_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Підтвердження видалення групи — запитуємо підтвердження"""
    query = update.callback_query
    await query.answer()

    # Отримуємо ID групи
    data = query.data
    group_id = int(data.replace("delete_group_", ""))

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Перевіряємо чи користувач адмін цієї групи
        cursor.execute("""
            SELECT g.name, g.code
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE g.group_id = ? AND gm.user_id = ? AND gm.is_admin = 1
        """, (group_id, user_id))

        group = cursor.fetchone()

        if not group:
            await query.edit_message_text(
                "❌ Групу не знайдено або у вас немає прав для видалення.",
                parse_mode="HTML"
            )
            return

        # Зберігаємо ID групи в контексті для підтвердження
        context.user_data['delete_group_id'] = group_id

        # Кнопки підтвердження
        keyboard = [
            [
                InlineKeyboardButton("✅ Так, видалити", callback_data="confirm_delete_group_yes"),
                InlineKeyboardButton("❌ Ні, скасувати", callback_data="confirm_delete_group_no")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            f"🗑️ <b>Підтвердження видалення групи</b>\n\n"
            f"📛 Назва: {group['name']}\n"
            f"🔑 Код: {group['code']}\n\n"
            f"⚠️ Ця дія <b>НЕЗВОРОТНЯ</b>!\n"
            f"Всі нагадування та учасники будуть видалені.\n\n"
            f"Ви впевнені?",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


async def execute_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Виконання видалення групи"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    # Отримуємо ID групи з контексту
    group_id = context.user_data.get('delete_group_id')

    if not group_id:
        await query.edit_message_text(
            "❌ Помилка: не знайдено групу для видалення.",
            parse_mode="HTML"
        )
        return

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Перевіряємо ще раз права адміна
        cursor.execute("""
            SELECT g.name
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE g.group_id = ? AND gm.user_id = ? AND gm.is_admin = 1
        """, (group_id, user_id))

        group = cursor.fetchone()

        if not group:
            await query.edit_message_text(
                "❌ Помилка: групу не знайдено або недостатньо прав.",
                parse_mode="HTML"
            )
            return

        # Видаляємо нагадування групи
        cursor.execute("DELETE FROM reminders WHERE group_id = ?", (group_id,))

        # Видаляємо учасників групи
        cursor.execute("DELETE FROM group_members WHERE group_id = ?", (group_id,))

        # Видаляємо саму групу
        cursor.execute("DELETE FROM groups WHERE group_id = ?", (group_id,))

        conn.commit()

        # Якщо це була активна група — очищаємо контекст
        active_group = context.user_data.get('active_group')
        if active_group and active_group['id'] == group_id:
            del context.user_data['active_group']

        # Очищаємо контекст
        if 'delete_group_id' in context.user_data:
            del context.user_data['delete_group_id']

        await query.edit_message_text(
            f"✅ <b>Групу видалено!</b>\n\n"
            f"📛 {group['name']}\n\n"
            f"Всі нагадування та учасники видалені.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("👥 Мої групи", callback_data="my_groups")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )

    finally:
        conn.close()


async def cancel_delete_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування видалення групи"""
    query = update.callback_query
    await query.answer()

    # Очищаємо контекст
    if 'delete_group_id' in context.user_data:
        del context.user_data['delete_group_id']

    await query.edit_message_text(
        "❌ Видалення групи скасовано.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("👥 Мої групи", callback_data="my_groups")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
        ])
    )


# ← ВИПРАВЛЕНО: Прибрано зайвий відступ перед async def
async def group_info(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ інформації про групу"""
    query = update.callback_query

    # Отримуємо ID групи з callback_data (формат: group_info_123)
    data = query.data
    group_id = int(data.replace("group_info_", ""))

    user_id = update.effective_user.id

    # Антиспам
    if not check_cooldown(user_id, f"group_info_{group_id}", cooldown_seconds=2):
        await query.answer("⏱ Занадто швидко!", show_alert=False)
        return

    await query.answer()

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Перевіряємо чи група існує і чи користувач є в групі
        cursor.execute("""
            SELECT g.group_id, g.name, g.code, gm.is_admin
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE g.group_id = ? AND gm.user_id = ?
        """, (group_id, user_id))

        membership = cursor.fetchone()

        if not membership:
            await query.edit_message_text(
                "❌ Групу не знайдено або ви не є її учасником.",
                parse_mode="HTML"
            )
            return

        # Отримуємо кількість учасників
        cursor.execute("""
            SELECT COUNT(*) as count FROM group_members WHERE group_id = ?
        """, (group_id,))
        member_count = cursor.fetchone()['count']

        # Отримуємо список учасників з іменами
        cursor.execute("""
            SELECT u.user_id, u.username, u.first_name, u.last_name, gm.is_admin
            FROM users u
            JOIN group_members gm ON u.user_id = gm.user_id
            WHERE gm.group_id = ?
            ORDER BY gm.is_admin DESC, u.first_name, u.username
        """, (group_id,))

        members = cursor.fetchall()

        # Формуємо список учасників
        members_list = []
        for idx, member in enumerate(members, 1):
            # Формуємо ім'я для відображення
            if member['username']:
                name = f"@{member['username']}"
            elif member['first_name']:
                name = member['first_name']
                if member['last_name']:
                    name += f" {member['last_name']}"
            else:
                name = f"Користувач {member['user_id']}"

            # Додаємо позначку адміна
            admin_mark = " 👑" if member['is_admin'] else ""
            members_list.append(f"{idx}. {name}{admin_mark}")

        # Формуємо повідомлення
        admin_status = "✅ Так" if membership['is_admin'] else "❌ Ні"

        message = (
            f"👥 <b>Група: {membership['name']}</b>\n\n"
            f"🔑 <b>Код для запрошення:</b> <code>{membership['code']}</code>\n"
            f"👤 <b>Учасників:</b> {member_count}\n"
            f"👑 <b>Ви адмін:</b> {admin_status}\n\n"
            f"<b>📋 Список учасників:</b>\n"
        )

        # Додаємо список учасників
        if members_list:
            message += "\n".join(members_list)
        else:
            message += "Немає учасників"

        # Формуємо кнопки
        keyboard = []

        # Кнопка "Поділитися кодом" (тільки для адмінів)
        if membership['is_admin']:
            keyboard.append([
                InlineKeyboardButton("📤 Поділитися кодом",
                                     switch_inline_query=f"Приєднуйся до групи '{membership['name']}'! Код: {membership['code']}")
            ])

        # Кнопка перегляду нагадувань групи
        keyboard.append([
            InlineKeyboardButton("📋 Нагадування групи", callback_data=f"switch_to_group_{group_id}")
        ])

        # Кнопка виходу (для не-адмінів) або видалення (для адмінів)
        if membership['is_admin']:
            keyboard.append([
                InlineKeyboardButton("🗑️ Видалити групу", callback_data=f"delete_group_{group_id}")
            ])
        else:
            keyboard.append([
                InlineKeyboardButton("🚪 Вийти з групи", callback_data=f"leave_group_{group_id}")
            ])

        keyboard.append([InlineKeyboardButton("🔙 Назад до списку", callback_data="my_groups")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


async def my_groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ списку моїх груп з можливістю вийти/видалити"""
    query = update.callback_query
    await query.answer()

    user_id = update.effective_user.id

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Отримуємо всі групи користувача
        cursor.execute("""
            SELECT g.group_id, g.name, g.code, gm.is_admin
            FROM groups g
            JOIN group_members gm ON g.group_id = gm.group_id
            WHERE gm.user_id = ?
            ORDER BY g.name
        """, (user_id,))

        groups = cursor.fetchall()

        if not groups:
            await query.edit_message_text(
                "👥 <b>Мої групи</b>\n\n"
                "Ви не є учасником жодної групи.",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton("➕ Створити групу", callback_data="create_group")],
                    [InlineKeyboardButton("🔗 Приєднатися", callback_data="join_group")],
                    [InlineKeyboardButton("🔙 Назад", callback_data="groups_menu")]
                ])
            )
            return

        # Формуємо кнопки груп
        keyboard = []
        for group in groups:
            admin_mark = " 👑" if group['is_admin'] else ""
            keyboard.append([
                InlineKeyboardButton(
                    f"👥 {group['name']}{admin_mark}",
                    callback_data=f"group_info_{group['group_id']}"
                )
            ])

        # Кнопки управління
        keyboard.append([InlineKeyboardButton("🚪 Вийти з групи", callback_data="leave_group")])
        keyboard.append([InlineKeyboardButton("🗑️ Видалити групу", callback_data="delete_group_menu")])
        keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="groups_menu")])

        reply_markup = InlineKeyboardMarkup(keyboard)

        await query.edit_message_text(
            "👥 <b>Мої групи</b>\n\n"
            "Оберіть групу або дію:\n"
            "👑 — ви адміністратор",
            parse_mode="HTML",
            reply_markup=reply_markup
        )

    finally:
        conn.close()


# ==================== ConversationHandlers ====================

# ConversationHandler для створення групи
create_group_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(create_group_start, pattern="^create_group$")
    ],
    states={
        WAITING_FOR_GROUP_NAME: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_group_name)
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("❌ Скасовано."))],
    per_message=False
)

# ConversationHandler для приєднання до групи
join_group_conv = ConversationHandler(
    entry_points=[
        CallbackQueryHandler(join_group_start, pattern="^join_group$")
    ],
    states={
        WAITING_FOR_JOIN_CODE: [
            MessageHandler(filters.TEXT & ~filters.COMMAND, process_join_code)
        ],
    },
    fallbacks=[CommandHandler("cancel", lambda u, c: u.message.reply_text("❌ Скасовано."))],
    per_message=False
)

# Список обробників для імпорту в main.py
groups_handlers = [
    # Інформація про групу
    CallbackQueryHandler(group_info, pattern="^group_info_"),
    # Вихід з групи
    CallbackQueryHandler(leave_group_start, pattern="^leave_group$"),
    CallbackQueryHandler(confirm_leave_group, pattern="^leave_group_"),
    # Видалення групи
    CallbackQueryHandler(delete_group_menu, pattern="^delete_group_menu$"),
    CallbackQueryHandler(confirm_delete_group, pattern="^delete_group_"),
    CallbackQueryHandler(execute_delete_group, pattern="^confirm_delete_group_yes$"),
    CallbackQueryHandler(cancel_delete_group, pattern="^confirm_delete_group_no$"),
    CallbackQueryHandler(my_groups_menu, pattern="^my_groups$"),
    # ======================
    create_group_conv,
    join_group_conv,
]