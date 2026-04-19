# main.py - Головний файл бота MemoremindMe (спрощена версія)

import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
)

from config import BOT_TOKEN, ACCESS_PASSWORD, ADMIN_ID
from database import init_db, add_user, authorize_user, is_user_authorized
from handlers.reminders import add_reminder_conv
from handlers.list import list_handlers
from handlers.groups import groups_handlers
from handlers.delete import delete_handlers
from handlers.edit import edit_handlers
from notifications import setup_reminder_jobs
from handlers.backup import backup_handler, auto_backup_job
from database import set_bot_instance
from utils import looks_like_reminder, check_cooldown  # ← ДОДАНО check_cooldown
from handlers.reminders import process_quick_reminder, process_quick_personal, process_quick_group, process_quick_cancel

# Налаштування логування
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)


# ==================== КОМАНДИ ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start - початок роботи з ботом"""
    user = update.effective_user
    user_id = user.id
    chat_id = update.effective_chat.id
    username = user.username

    # Додаємо користувача в БД (якщо немає)
    add_user(user_id, chat_id, username)

    # Перевіряємо авторизацію
    if is_user_authorized(user_id):
        # Вже авторизований - показуємо меню
        await show_main_menu(update, context)
    else:
        # Потрібна авторизація
        await update.message.reply_text(
            "🔐 <b>Вітаю в MemoremindMe!</b>\n\n"
            "Це бот для нагадування важливих дат.\n"
            "Для продовження введіть пароль доступу:",
            parse_mode="HTML"
        )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help або /about — довідка про бота"""
    await show_about(update, context)


async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Скасування будь-якої операції"""
    # Очищаємо всі тимчасові дані
    keys_to_clear = ['reminder_date', 'reminder_text', 'reminder_type', 'delete_reminder_id', 'delete_is_admin']
    for key in keys_to_clear:
        if key in context.user_data:
            del context.user_data[key]

    await update.message.reply_text(
        "❌ Операцію скасовано.\n\n"
        "🏠 <b>Головне меню</b>\n\nОберіть дію:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
            [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
            [InlineKeyboardButton("👥 Групи", callback_data="groups_menu")],
            [InlineKeyboardButton("⚙️ Налаштування", callback_data="settings")],
        ])
    )


async def menu_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /menu - показати головне меню"""
    await show_main_menu(update, context)


# ==================== МЕНЮ ====================

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ головного меню"""
    keyboard = [
        [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
        [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
        [InlineKeyboardButton("👥 Групи", callback_data="groups_menu")],
        [InlineKeyboardButton("⚙️ Налаштування", callback_data="settings")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    message_text = "🏠 <b>Головне меню</b>\n\nОберіть дію:"

    if update.callback_query:
        await update.callback_query.edit_message_text(
            message_text, parse_mode="HTML", reply_markup=reply_markup
        )
    else:
        await update.message.reply_text(
            message_text, parse_mode="HTML", reply_markup=reply_markup
        )


async def show_reminders_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ меню перегляду нагадувань"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("📅 Сьогодні", callback_data="list_today")],
        [InlineKeyboardButton("📆 Цей тиждень", callback_data="list_week")],
        [InlineKeyboardButton("🗓️ Цей місяць", callback_data="list_month")],
        [InlineKeyboardButton("📋 Всі", callback_data="list_all")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "📋 <b>Мої нагадування</b>\n\nОберіть період:",
        parse_mode="HTML",
        reply_markup=reply_markup,
    )


async def show_groups_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ меню управління групами"""
    query = update.callback_query
    await query.answer()

    keyboard = [
        [InlineKeyboardButton("➕ Створити групу", callback_data="create_group")],
        [InlineKeyboardButton("🔗 Приєднатися до групи", callback_data="join_group")],
        [InlineKeyboardButton("📋 Мої групи", callback_data="my_groups")],
        [InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")],
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    await query.edit_message_text(
        "👥 <b>Групи</b>\n\n"
        "Оберіть дію:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def show_settings_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ меню налаштувань"""
    user_id = update.effective_user.id

    # Формуємо базові кнопки
    keyboard = [
        [InlineKeyboardButton("ℹ️ Про бота", callback_data="about_bot")],  # ← НОВА КНОПКА
        [InlineKeyboardButton("🚪 Вийти з акаунта", callback_data="logout")],
    ]

    # Додаємо кнопку backup тільки для адміна
    if user_id == ADMIN_ID:
        keyboard.insert(0, [InlineKeyboardButton("🗄 Скачати backup", callback_data="download_backup")])

    keyboard.append([InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu")])

    reply_markup = InlineKeyboardMarkup(keyboard)

    await update.callback_query.edit_message_text(
        "⚙️ <b>Налаштування</b>\n\n"
        "Оберіть дію:",
        parse_mode="HTML",
        reply_markup=reply_markup
    )


async def show_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Показ детальної інформації про бота"""
    query = update.callback_query

    about_text = (
        "🤖 <b>MemoRemindMe — твій помічник з нагадуваннями</b>\n\n"

        "📌 <b>Що вміє бот:</b>\n"
        "• Створювати разові, щомісячні та щорічні нагадування\n"
        "• Розпізнавати дати українською: «завтра», «через 3 дні», «15 травня»\n"
        "• Працювати з групами — спільні нагадування для сім'ї, роботи, друзів\n"
        "• Надсилати щоденні нагадування о 8:00 ранку\n"
        "• Формувати тижневі та місячні звіти\n\n"

        "⚡ <b>Швидкі команди:</b>\n"
        "• <code>завтра тест</code> — нагадування на завтра\n"
        "• <code>через 3 дні зустріч</code> — через 3 дні\n"
        "• <code>15 травня день народження</code> — конкретна дата\n"
        "• <code>15.05 Оплатити інтернет</code> — класичний формат\n\n"

        "📝 <b>Команди:</b>\n"
        "/start — почати роботу\n"
        "/menu — головне меню\n"
        "/add — додати нагадування\n"
        "/today — сьогодні\n"
        "/week — цей тиждень\n"
        "/month — цей місяць\n"
        "/all — всі нагадування\n"
        "/help або /about — ця довідка\n"
        "/cancel — скасувати дію\n\n"

        "👥 <b>Групи:</b>\n"
        "• Створіть групу та поділіться кодом запрошення\n"
        "• До 10 учасників у групі\n"
        "• Спільні нагадування для всіх учасників\n"
        "• Адмін керує групою та може видаляти її\n\n"

        "🔔 <b>Типи нагадувань:</b>\n"
        "🔔 Разове — одноразове нагадування\n"
        "🔄 Щомісячне — повторюється щомісяця (наприклад, оплата рахунків)\n"
        "📅 Щорічне — повторюється щороку (наприклад, дні народження)\n\n"

        "💡 <b>Порада:</b> Просто напишіть мені дату та подію — "
        "я все зрозумію і запитаю, куди зберегти!\n\n"

        "🆕 <b>Версія:</b> 1.0 | 2026"
    )

    keyboard = [
        [InlineKeyboardButton("🔙 Назад до налаштувань", callback_data="settings")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)

    if query:
        await query.answer()
        await query.edit_message_text(about_text, parse_mode="HTML", reply_markup=reply_markup)
    else:
        await update.message.reply_text(about_text, parse_mode="HTML", reply_markup=reply_markup)

# ==================== ОБРОБНИКИ ПОВІДОМЛЕНЬ ====================

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка текстових повідомлень від користувача"""

    # Перевіряємо чи є текст
    if not update.message or not update.message.text:
        return

    text = update.message.text.strip()
    user_id = update.effective_user.id

    # Якщо користувач не авторизований - перевіряємо пароль
    if not is_user_authorized(user_id):
        if text == ACCESS_PASSWORD:
            # Правильний пароль
            authorize_user(user_id)
            await update.message.reply_text(
                "✅ <b>Авторизація успішна!</b>\n\n"
                "Тепер ви можете користуватися ботом.\n\n"
                "Просто напишіть: <code>завтра тест</code> або <code>15 травня день народження</code>",
                parse_mode="HTML"
            )
            await show_main_menu(update, context)
        else:
            # Неправильний пароль
            await update.message.reply_text(
                "❌ <b>Невірний пароль!</b>\n\n"
                "Спробуйте ще раз або зверніться до адміністратора.",
                parse_mode="HTML"
            )
        return

    # === ШВИДКЕ ДОДАВАННЯ ТЕКСТОМ ===
    # Перевіряємо чи це нагадування (завтра, через 3 дні, 15 травня, тощо)
    if looks_like_reminder(text):
        success = await process_quick_reminder(update, context, text)
        if success:
            return  # Оброблено як нагадування

    # === ЗВИЧАЙНИЙ ЧАТ ===
    # Не схоже на нагадування — обробляємо як звичайне повідомлення
    await handle_chat_message(update, context, text)


async def handle_chat_message(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    """
    Обробка звичайних повідомлень (не нагадувань)
    Відповіді на привітання, допомога, тощо
    """
    text_lower = text.lower().strip()

    # Привітання
    if any(word in text_lower for word in
           ["привіт", "hello", "hi", "hey", "добрий день", "добрий вечір", "доброго ранку"]):
        await update.message.reply_text(
            "Привіт! 👋\n\n"
            "Я бот для нагадувань важливих дат.\n"
            "Просто напиши мені: <code>завтра тест</code> або <code>15 травня день народження</code>\n\n"
            "Або використовуй /menu для навігації",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
                [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )
        return

    # Допомога
    if any(word in text_lower for word in ["допомога", "help", "помощь", "підказка", "як користуватися"]):
        await help_command(update, context)
        return

    # Меню
    if any(word in text_lower for word in ["меню", "menu", "панель", "команды", "команди"]):
        await show_main_menu(update, context)
        return

    # Подяка
    if any(word in text_lower for word in ["дякую", "спасибі", "спасибо", "дякую тобі", "thanks", "thank you"]):
        await update.message.reply_text(
            "Завжди радий допомогти! 😊\n\n"
            "Напиши нагадування прямо в чат або використовуй меню.",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
                [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
            ])
        )
        return

    # Невідомий текст — пропонуємо меню
    await update.message.reply_text(
        "🤔 Я не зрозумів це повідомлення...\n\n"
        "Якщо ти хочеш додати нагадування, спробуй:\n"
        "• <code>завтра тест</code>\n"
        "• <code>через 3 дні зустріч</code>\n"
        "• <code>15 травня день народження</code>\n"
        "• <code>15.05 оплатити інтернет</code>\n\n"
        "Або використовуй меню:",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 Мої нагадування", callback_data="my_reminders")],
            [InlineKeyboardButton("➕ Додати нагадування", callback_data="add_reminder")],
            [InlineKeyboardButton("🏠 Головне меню", callback_data="back_to_menu")]
        ])
    )


# ==================== ОБРОБНИКИ КНОПОК ====================

async def logout_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Вихід користувача з акаунта"""
    from database import unauthorize_user

    user_id = update.effective_user.id
    unauthorize_user(user_id)

    # Очищаємо контекст
    context.user_data.clear()

    await update.callback_query.edit_message_text(
        "🚪 <b>Ви вийшли з акаунта</b>\n\n"
        "Для повторного входу введіть пароль:",
        parse_mode="HTML"
    )


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обробка натискання кнопок"""
    query = update.callback_query
    data = query.data
    user_id = update.effective_user.id

    # Антиспам для всіх загальних кнопок
    if not check_cooldown(user_id, f"btn_{data}", cooldown_seconds=1):
        await query.answer("⏱ Занадто швидко!", show_alert=False)
        return

    await query.answer()

    if data == "back_to_menu":
        await show_main_menu(update, context)
    elif data == "my_reminders":
        await show_reminders_menu(update, context)
    elif data == "settings":
        await show_settings_menu(update, context)
    elif data == "about_bot":
        await show_about(update, context)
    elif data == "logout":
        await logout_user(update, context)
    elif data == "groups_menu":
        await show_groups_menu(update, context)

    # Якщо кнопка не відома — НЕ відповідаємо, нехай оброблять інші handlers


# ==================== ЗАПУСК ====================

def main():
    """Головна функція запуску бота"""
    # Ініціалізуємо базу даних
    print("🔄 Ініціалізація бази даних...")
    init_db()

    # Створюємо додаток
    print("🔄 Запуск бота...")
    application = Application.builder().token(BOT_TOKEN).build()

    # ← ДОДАНО: Отримуємо job_queue
    job_queue = application.job_queue

    # Встановлюємо бота для сповіщень адміна про помилки БД
    set_bot_instance(application.bot)

    # Додаємо обробники
    # 1. ConversationHandler для додавання нагадувань (ВАЖЛИВО: додати першим!)
    application.add_handler(add_reminder_conv)

    # 2. Команди
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("about", help_command))
    application.add_handler(CommandHandler("menu", menu_command))
    application.add_handler(CommandHandler("cancel", cancel_command))

    # 3. Обробники списків нагадувань (конкретні pattern — мають бути ДО загального handler)
    for handler in list_handlers:
        application.add_handler(handler)

    # 4. Обробники груп (ВАЖЛИВО: додати ДО загального обробника кнопок!)
    for handler in groups_handlers:
        application.add_handler(handler)

    # 4.1 Обробник інформації про групу (окремо, бо не в groups_handlers)
    from handlers.groups import group_info
    application.add_handler(CallbackQueryHandler(group_info, pattern="^group_info_"))

    # 5. Обробники видалення (додаємо перед загальним обробником)
    for handler in delete_handlers:
        application.add_handler(handler)

    # 5.5 Обробник backup (додаємо перед загальним обробником)
    application.add_handler(backup_handler)

    # 5.6 Обробники редагування (додаємо перед загальним обробником)
    for handler in edit_handlers:
        application.add_handler(handler)

    # 6. Обробники швидкого додавання (вибір особисте/група)
    application.add_handler(CallbackQueryHandler(process_quick_personal, pattern="^quick_personal$"))
    application.add_handler(CallbackQueryHandler(process_quick_group, pattern="^quick_group_"))
    application.add_handler(CallbackQueryHandler(process_quick_cancel, pattern="^quick_cancel$"))

    # 7. Загальний обробник кнопок (тільки для конкретних кнопок)
    application.add_handler(
        CallbackQueryHandler(button_handler, pattern="^(back_to_menu|my_reminders|settings|about_bot|logout|groups_menu)$"))

    # 8. Обробник текстових повідомлень (для пароля і швидкого додавання)
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Налаштовуємо систему нагадувань
    setup_reminder_jobs(application)

    # ← ДОДАНО: Очистка старих кулдаунів кожні 10 хвилин
    from utils import clear_old_cooldowns

    job_queue.run_repeating(
        callback=lambda context: clear_old_cooldowns(),
        interval=600,  # 10 хвилин
        first=600,
        name="cleanup_cooldowns"
    )

    # Запускаємо бота
    print("✅ Бот запущений! Натисніть Ctrl+C для зупинки.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()