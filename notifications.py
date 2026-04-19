# notifications.py - Система нагадувань о ~8:00 за Києвом (6:00 UTC)

import logging
from datetime import date, time, timedelta
from telegram.error import TelegramError
from database import get_db_connection
from utils import format_date, get_next_month_date, get_next_year_date, get_week_dates
from config import BACKUP_TIME, BACKUP_DAYS
from handlers.backup import auto_backup_job


logger = logging.getLogger(__name__)


async def check_and_send_reminders(context):
    """
    Перевіряє нагадування на сьогодні і надсилає їх
    """
    from database import USE_POSTGRES, get_db_connection

    bot = context.bot
    today = date.today()
    logger.info(f"🔍 Перевірка нагадувань на {today}")

    conn = get_db_connection()
    cursor = conn.cursor()

    # Вибираємо placeholder залежно від бази
    ph = "%s" if USE_POSTGRES else "?"

    try:
        # === ЗБИРАЄМО ВСІ НАГАДУВАННЯ ДЛЯ КОЖНОГО КОРИСТУВАЧА ===
        user_reminders = {}

        # 1. ОСОБИСТІ НАГАДУВАННЯ (group_id IS NULL)
        cursor.execute(f"""
            SELECT r.*, u.chat_id, NULL as group_name, u.user_id as receiver_id
            FROM reminders r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.next_date = {ph}
            AND r.group_id IS NULL
            AND u.is_authorized = {'TRUE' if USE_POSTGRES else '1'}
        """, (today,))

        for row in cursor.fetchall():
            if USE_POSTGRES:
                # PostgreSQL повертає tuple, конвертуємо в dict
                columns = [desc[0] for desc in cursor.description]
                row_dict = dict(zip(columns, row))
            else:
                row_dict = dict(row)

            user_id = row_dict['receiver_id']
            if user_id not in user_reminders:
                user_reminders[user_id] = {
                    'chat_id': row_dict['chat_id'],
                    'reminders': []
                }
            user_reminders[user_id]['reminders'].append({
                'text': row_dict['text'],
                'type': row_dict['type'],
                'group_name': None,
                'is_personal': True,
                'date_str': None
            })

        # 2. ГРУПОВІ НАГАДУВАННЯ
        cursor.execute(f"""
            SELECT r.*, g.name as group_name, g.group_id
            FROM reminders r
            JOIN groups g ON r.group_id = g.group_id
            WHERE r.next_date = {ph}
            AND r.group_id IS NOT NULL
        """, (today,))

        group_reminders = cursor.fetchall()

        for reminder in group_reminders:
            if USE_POSTGRES:
                columns = [desc[0] for desc in cursor.description]
                reminder = dict(zip(columns, reminder))
            else:
                reminder = dict(reminder)

            group_id = reminder['group_id']

            cursor.execute(f"""
                SELECT u.user_id, u.chat_id
                FROM users u
                JOIN group_members gm ON u.user_id = gm.user_id
                WHERE gm.group_id = {ph} AND u.is_authorized = {'TRUE' if USE_POSTGRES else '1'}
            """, (group_id,))

            members = cursor.fetchall()

            for member in members:
                if USE_POSTGRES:
                    member = dict(zip([desc[0] for desc in cursor.description], member))
                else:
                    member = dict(member)

                user_id = member['user_id']
                if user_id not in user_reminders:
                    user_reminders[user_id] = {
                        'chat_id': member['chat_id'],
                        'reminders': []
                    }
                user_reminders[user_id]['reminders'].append({
                    'text': reminder['text'],
                    'type': reminder['type'],
                    'group_name': reminder['group_name'],
                    'is_personal': False,
                    'date_str': None
                })

        # === ВІДПРАВЛЯЄМО ===
        logger.info(f"📋 Знайдено нагадування для {len(user_reminders)} користувачів")

        for user_id, data in user_reminders.items():
            try:
                title = f"📅 Нагадування на {format_date(today)}"
                await send_combined_reminders(bot, data['chat_id'], data['reminders'], title, today)
            except Exception as e:
                logger.error(f"❌ Помилка відправки нагадувань користувачу {user_id}: {e}")

        # === ОНОВЛЮЄМО ДАТИ ===
        cursor.execute(f"""
            SELECT r.* FROM reminders r
            JOIN users u ON r.user_id = u.user_id
            WHERE r.next_date = {ph} AND r.group_id IS NULL AND u.is_authorized = {'TRUE' if USE_POSTGRES else '1'}
        """, (today,))

        for reminder in cursor.fetchall():
            if USE_POSTGRES:
                reminder = dict(zip([desc[0] for desc in cursor.description], reminder))
            else:
                reminder = dict(reminder)
            await update_reminder_date(cursor, conn, reminder, USE_POSTGRES)

        cursor.execute(f"""
            SELECT r.* FROM reminders r
            JOIN groups g ON r.group_id = g.group_id
            WHERE r.next_date = {ph} AND r.group_id IS NOT NULL
        """, (today,))

        for reminder in cursor.fetchall():
            if USE_POSTGRES:
                reminder = dict(zip([desc[0] for desc in cursor.description], reminder))
            else:
                reminder = dict(reminder)
            await update_reminder_date(cursor, conn, reminder, USE_POSTGRES)

    finally:
        conn.close()


async def send_combined_reminders(bot, chat_id, reminders, title, date_obj=None, max_per_message=10):
    """
    Універсальна функція для відправки об'єднаних нагадувань
    """
    if not reminders:
        empty_message = f"{title}\n\n✅ Немає запланованих нагадувань."
        try:
            await bot.send_message(
                chat_id=chat_id,
                text=empty_message,
                parse_mode="HTML"
            )
        except TelegramError as e:
            logger.error(f"❌ Не вдалося надіслати: {e}")
        return

    type_emoji = {
        'once': '🔔',
        'monthly': '🔄',
        'yearly': '📅'
    }

    total = len(reminders)
    chunks = []
    for i in range(0, total, max_per_message):
        chunk = reminders[i:i + max_per_message]
        chunks.append(chunk)

    for chunk_index, chunk in enumerate(chunks):
        start_num = chunk_index * max_per_message + 1
        end_num = min((chunk_index + 1) * max_per_message, total)

        if len(chunks) == 1:
            message = f"{title}\n\n"
        else:
            message = f"{title} ({start_num}-{end_num} з {total})\n\n"

        for reminder in chunk:
            icon = type_emoji.get(reminder.get('type', 'once'), '🔔')

            # Додаємо дату якщо є
            date_prefix = ""
            if reminder.get('date_str'):
                date_prefix = f"{reminder['date_str']}: "

            message += f"{icon} {date_prefix}{reminder['text']}"

            # Додаємо позначку особисте/групове
            if reminder.get('is_personal'):
                message += "\n👤 Особисте"
            elif reminder.get('group_name'):
                message += f"\n👥 {reminder['group_name']}"

            message += "\n\n"

        try:
            await bot.send_message(
                chat_id=chat_id,
                text=message,
                parse_mode="HTML"
            )
            logger.info(f"✅ Надіслано частину {chunk_index + 1}/{len(chunks)}")
        except TelegramError as e:
            logger.error(f"❌ Не вдалося надіслати: {e}")


async def update_reminder_date(cursor, conn, reminder, use_postgres=False):
    """
    Оновлює дату нагадування (переносить на наступний раз)
    """
    ph = "%s" if use_postgres else "?"

    if reminder['type'] == 'once':
        cursor.execute(
            f"DELETE FROM reminders WHERE reminder_id = {ph}",
            (reminder['reminder_id'],)
        )
        logger.info(f"🗑️ Разове нагадування {reminder['reminder_id']} видалено")

    elif reminder['type'] == 'monthly':
        current_date = date.fromisoformat(str(reminder['next_date']))
        original_day = reminder['original_day'] or current_date.day
        next_date = get_next_month_date(current_date, original_day)

        cursor.execute(
            f"UPDATE reminders SET next_date = {ph} WHERE reminder_id = {ph}",
            (next_date, reminder['reminder_id'])
        )
        logger.info(f"🔄 Щомісячне нагадування {reminder['reminder_id']} перенесено на {next_date}")

    elif reminder['type'] == 'yearly':
        current_date = date.fromisoformat(str(reminder['next_date']))
        next_date = get_next_year_date(current_date)

        cursor.execute(
            f"UPDATE reminders SET next_date = {ph} WHERE reminder_id = {ph}",
            (next_date, reminder['reminder_id'])
        )
        logger.info(f"📅 Щорічне нагадування {reminder['reminder_id']} перенесено на {next_date}")

    conn.commit()


async def send_weekly_report(context):
    """Надсилає звіт на тиждень щопонеділка"""
    bot = context.bot
    today = date.today()

    # Тільки в понеділок
    if today.weekday() != 0:
        return

    week_dates = get_week_dates(today)
    monday = week_dates[0]
    sunday = week_dates[6]

    logger.info(f"📊 Формування тижневого звіту: {monday} - {sunday}")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT user_id, chat_id FROM users WHERE is_authorized = 1
        """)
        users = cursor.fetchall()

        for user in users:
            user_id = user['user_id']
            chat_id = user['chat_id']

            # Отримуємо нагадування
            cursor.execute("""
                SELECT r.*, g.name as group_name
                FROM reminders r
                LEFT JOIN groups g ON r.group_id = g.group_id
                WHERE (
                    r.user_id = ?
                    OR (
                        r.group_id IS NOT NULL 
                        AND r.group_id IN (
                            SELECT group_id FROM group_members WHERE user_id = ?
                        )
                    )
                )
                AND r.next_date BETWEEN ? AND ?
                ORDER BY r.next_date
            """, (user_id, user_id, monday, sunday))

            rows = cursor.fetchall()

            # Конвертуємо в формат для send_combined_reminders
            weekdays = {
                0: 'понеділок',
                1: 'вівторок',
                2: 'середа',
                3: 'четвер',
                4: 'пʼятниця',
                5: 'субота',
                6: 'неділя'
            }

            reminders = []
            for rem in rows:
                rem_date = date.fromisoformat(rem['next_date'])
                weekday_name = weekdays[rem_date.weekday()]
                date_str = format_date(rem_date)

                # Визначаємо чи особисте чи групове
                is_personal = rem['group_id'] is None

                reminders.append({
                    'text': rem['text'],
                    'type': rem['type'],
                    'date_str': f"{date_str} ({weekday_name})",
                    'group_name': rem['group_name'] if not is_personal else None,
                    'is_personal': is_personal
                })

            # Формуємо заголовок
            title = f"📆 <b>Звіт на тиждень</b>\n{format_date(monday)} — {format_date(sunday)}"

            # Відправляємо
            try:
                await send_combined_reminders(bot, chat_id, reminders, title, max_per_message=10)
                logger.info(f"📨 Тижневий звіт надіслано користувачу {user_id}")
            except Exception as e:
                logger.error(f"❌ Помилка відправки тижневого звіту користувачу {user_id}: {e}")

    finally:
        conn.close()


async def send_monthly_report(context):
    """Надсилає звіт на місяць 1-го числа"""
    bot = context.bot
    today = date.today()

    # Тільки 1-го числа
    if today.day != 1:
        return

    first_day = today.replace(day=1)
    if today.month == 12:
        last_day = today.replace(day=31)
    else:
        next_month = today.replace(month=today.month + 1, day=1)
        last_day = next_month - timedelta(days=1)

    logger.info(f"📊 Формування місячного звіту: {first_day} - {last_day}")

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            SELECT user_id, chat_id FROM users WHERE is_authorized = 1
        """)
        users = cursor.fetchall()

        months = {
            1: 'Січень', 2: 'Лютий', 3: 'Березень', 4: 'Квітень',
            5: 'Травень', 6: 'Червень', 7: 'Липень', 8: 'Серпень',
            9: 'Вересень', 10: 'Жовтень', 11: 'Листопад', 12: 'Грудень'
        }
        month_name = months[today.month]

        for user in users:
            user_id = user['user_id']
            chat_id = user['chat_id']

            # Отримуємо нагадування
            cursor.execute("""
                SELECT r.*, g.name as group_name
                FROM reminders r
                LEFT JOIN groups g ON r.group_id = g.group_id
                WHERE (
                    r.user_id = ?
                    OR (
                        r.group_id IS NOT NULL 
                        AND r.group_id IN (
                            SELECT group_id FROM group_members WHERE user_id = ?
                        )
                    )
                )
                AND r.next_date BETWEEN ? AND ?
                ORDER BY r.next_date
            """, (user_id, user_id, first_day, last_day))

            rows = cursor.fetchall()

            # Конвертуємо в формат для send_combined_reminders
            reminders = []
            for rem in rows:
                rem_date = date.fromisoformat(rem['next_date'])
                date_str = format_date(rem_date)

                # Визначаємо чи особисте чи групове
                is_personal = rem['group_id'] is None

                reminders.append({
                    'text': rem['text'],
                    'type': rem['type'],
                    'date_str': date_str,
                    'group_name': rem['group_name'] if not is_personal else None,
                    'is_personal': is_personal
                })

            # Формуємо заголовок
            title = f"🗓️ <b>Звіт на {month_name} {today.year}</b>"

            # Відправляємо
            try:
                await send_combined_reminders(bot, chat_id, reminders, title, max_per_message=10)
                logger.info(f"📨 Місячний звіт надіслано користувачу {user_id}")
            except Exception as e:
                logger.error(f"❌ Помилка відправки місячного звіту користувачу {user_id}: {e}")

    finally:
        conn.close()


def setup_reminder_jobs(application):
    """
    Налаштовує автоматичну перевірку нагадувань
    """
    from telegram.ext import JobQueue

    job_queue = application.job_queue

    # 1. Місячний звіт — 6:01 UTC (1-го числа)
    job_queue.run_daily(
        callback=monthly_report_job,
        time=time(hour=6, minute=1),
        name="monthly_report"
    )

    # 2. Тижневий звіт — 6:02 UTC (щопонеділка)
    job_queue.run_daily(
        callback=weekly_report_job,
        time=time(hour=6, minute=2),
        days=(0,),  # Понеділок
        name="weekly_report"
    )

    # 3. Щоденні нагадування — 6:03 UTC
    job_queue.run_daily(
        callback=daily_reminders_job,
        time=time(hour=6, minute=3),
        name="daily_reminders"
    )

    # 4. Backup — 6:04 UTC
    job_queue.run_daily(
        callback=auto_backup_job,
        time=time(hour=6, minute=4),
        days=BACKUP_DAYS,
        name="daily_backup"
    )

    # Перша перевірка зараз (для тесту)
    job_queue.run_once(
        callback=daily_reminders_job,
        when=0,
        name="initial_check"
    )

    logger.info("✅ Система нагадувань налаштована:")
    logger.info("   • Місячний звіт 1-го числа о 6:01 UTC")
    logger.info("   • Тижневий звіт щопонеділка о 6:02 UTC")
    logger.info("   • Щоденні нагадування о 6:03 UTC")
    logger.info("   • Backup о 6:04 UTC")


# Job-обгортки з обробкою помилок
async def daily_reminders_job(context):
    """Job для щоденних нагадувань"""
    try:
        await check_and_send_reminders(context)
    except Exception as e:
        logger.error(f"❌ Помилка в daily_reminders_job: {e}")


async def weekly_report_job(context):
    """Job для тижневого звіту"""
    try:
        await send_weekly_report(context)
    except Exception as e:
        logger.error(f"❌ Помилка в weekly_report_job: {e}")


async def monthly_report_job(context):
    """Job для місячного звіту"""
    try:
        await send_monthly_report(context)
    except Exception as e:
        logger.error(f"❌ Помилка в monthly_report_job: {e}")