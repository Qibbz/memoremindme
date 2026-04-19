# utils.py - Допоміжні функції (ОНОВЛЕНО з natural language)

import re
from datetime import datetime, date, timedelta
from calendar import monthrange

# ============ АНТИСПАМ ДЛЯ КНОПОК ============

from datetime import datetime, timedelta

# Словник: user_id -> {callback_name: last_time}
_user_cooldown = {}


def check_cooldown(user_id: int, action: str, cooldown_seconds: int = 2) -> bool:
    """
    Перевіряє чи користувач не спамить однією кнопкою
    Повертає True якщо ДОЗВОЛЕНО, False якщо СПАМ
    """
    now = datetime.now()

    if user_id not in _user_cooldown:
        _user_cooldown[user_id] = {}

    last_time = _user_cooldown[user_id].get(action)

    if last_time and (now - last_time).total_seconds() < cooldown_seconds:
        return False  # Спам! Заборонено

    _user_cooldown[user_id][action] = now
    return True  # Дозволено


def clear_old_cooldowns(max_age_minutes: int = 10):
    """Очищає старі записи кулдауну щоб не засмічувати пам'ять"""
    now = datetime.now()
    to_remove_users = []

    for user_id, actions in _user_cooldown.items():
        to_remove_actions = []
        for action, last_time in actions.items():
            if (now - last_time).total_seconds() > max_age_minutes * 60:
                to_remove_actions.append(action)

        for action in to_remove_actions:
            del actions[action]

        if not actions:
            to_remove_users.append(user_id)

    for user_id in to_remove_users:
        del _user_cooldown[user_id]

# Словник українських чисел для заміни слів на цифри
UKRAINIAN_NUMBERS = {
    "один": 1, "одна": 1, "одне": 1,
    "два": 2, "дві": 2,
    "три": 3,
    "чотири": 4,
    "п'ять": 5, "пять": 5,
    "шість": 6,
    "сім": 7,
    "вісім": 8,
    "дев'ять": 9, "девять": 9,
    "десять": 10,
    "одинадцять": 11,
    "дванадцять": 12,
    "тринадцять": 13,
    "чотирнадцять": 14,
    "п'ятнадцять": 15, "пятнадцять": 15,
    "шістнадцять": 16,
    "сімнадцять": 17,
    "вісімнадцять": 18,
    "дев'ятнадцять": 19, "девятнадцять": 19,
    "двадцять": 20,
    "тридцять": 30,
}

# Словник місяців
UKRAINIAN_MONTHS = {
    "січня": 1, "січень": 1,
    "лютого": 2, "лютий": 2,
    "березня": 3, "березень": 3,
    "квітня": 4, "квітень": 4,
    "травня": 5, "травень": 5,
    "червня": 6, "червень": 6,
    "липня": 7, "липень": 7,
    "серпня": 8, "серпень": 8,
    "вересня": 9, "вересень": 9,
    "жовтня": 10, "жовтень": 10,
    "листопада": 11, "листопад": 11,
    "грудня": 12, "грудень": 12,
}

# Словник днів тижня
UKRAINIAN_WEEKDAYS = {
    "понеділок": 0,
    "вівторок": 1,
    "середа": 2,
    "четвер": 3,
    "п'ятниця": 4, "пятниця": 4,
    "субота": 5,
    "неділя": 6,
}


def replace_words_with_numbers(text: str) -> str:
    """Замінює українські числа словами на цифри"""
    result = text.lower()
    for word, number in UKRAINIAN_NUMBERS.items():
        result = re.sub(rf"\b{re.escape(word)}\b", str(number), result)
    return result


def parse_relative_days(text: str):
    """
    Парсинг відносних дат: "через N днів", "за 3 дні", "через три дні"
    """
    patterns = [
        r"через\s+(\d+)\s+д(ень|ні|нів|ня)(?:\s+)?(.*)?",
        r"за\s+(\d+)\s+д(ень|ні|нів|ня)(?:\s+)?(.*)?",
    ]

    text_processed = replace_words_with_numbers(text.lower().strip())

    for pattern in patterns:
        match = re.match(pattern, text_processed)
        if match:
            days = int(match.group(1))
            remaining = match.group(3) if match.group(3) else ""
            target_date = date.today() + timedelta(days=days)
            return target_date, remaining.strip()

    return None, None


def parse_tomorrow(text: str):
    """Парсинг 'завтра' та 'післязавтра'"""
    text_lower = text.lower().strip()

    # Завтра
    match = re.match(r"завтра(?:\s+)?(.*)?", text_lower)
    if match:
        target_date = date.today() + timedelta(days=1)
        remaining = match.group(1) if match.group(1) else ""
        return target_date, remaining.strip()

    # Післязавтра
    match = re.match(r"післязавтра(?:\s+)?(.*)?", text_lower)
    if match:
        target_date = date.today() + timedelta(days=2)
        remaining = match.group(1) if match.group(1) else ""
        return target_date, remaining.strip()

    return None, None


def parse_weekday(text: str):
    """
    Парсинг 'наступний понеділок', 'у вівторок', 'в суботу'
    """
    text_lower = text.lower().strip()

    # Патерни для днів тижня
    patterns = [
        r"наступний\s+(\w+)(?:\s+)?(.*)?",
        r"у\s+(\w+)(?:\s+)?(.*)?",
        r"в\s+(\w+)(?:\s+)?(.*)?",
        r"цього\s+(\w+)(?:\s+)?(.*)?",
    ]

    for pattern in patterns:
        match = re.match(pattern, text_lower)
        if match:
            day_word = match.group(1)
            remaining = match.group(2) if match.group(2) else ""

            # Перевіряємо чи це день тижня
            for weekday_name, weekday_num in UKRAINIAN_WEEKDAYS.items():
                if day_word == weekday_name:
                    today = date.today()
                    days_ahead = weekday_num - today.weekday()

                    if days_ahead <= 0:  # Цей день вже був цього тижня
                        days_ahead += 7

                    target_date = today + timedelta(days=days_ahead)
                    return target_date, remaining.strip()

    return None, None


def parse_month_day(text: str):
    """
    Парсинг '15 травня', '1 січня', '3 березня день народження'
    """
    text_lower = text.lower().strip()

    # Патерн: число + місяць
    month_names = "|".join(re.escape(m) for m in UKRAINIAN_MONTHS.keys())
    pattern = rf"^(\d{{1,2}})\s+({month_names})(?:\s+)?(.*)?$"

    match = re.match(pattern, text_lower)
    if match:
        day = int(match.group(1))
        month_word = match.group(2)
        remaining = match.group(3) if match.group(3) else ""

        month = UKRAINIAN_MONTHS.get(month_word)
        if month and 1 <= day <= 31:
            today = date.today()
            year = today.year

            # Якщо дата вже пройшла цього року — беремо наступний рік
            try:
                target_date = date(year, month, day)
                if target_date < today:
                    target_date = date(year + 1, month, day)
                return target_date, remaining.strip()
            except ValueError:
                # Неправильна дата (наприклад 31 лютого)
                pass

    return None, None


def parse_natural_date(text: str):
    """
    Головна функція парсингу природної мови
    Спробує всі методи по черзі
    """
    text = text.strip()

    # 1. Спробуємо "завтра", "післязавтра"
    result = parse_tomorrow(text)
    if result[0]:
        return result

    # 2. Спробуємо "через N днів"
    result = parse_relative_days(text)
    if result[0]:
        return result

    # 3. Спробуємо день тижня
    result = parse_weekday(text)
    if result[0]:
        return result

    # 4. Спробуємо "15 травня"
    result = parse_month_day(text)
    if result[0]:
        return result

    return None, None


def looks_like_reminder(text: str) -> bool:
    """
    Перевіряє чи текст схожий на нагадування
    """
    text_lower = text.lower().strip()

    # Якщо це команда — не нагадування
    if text.startswith("/"):
        return False

    # Ключові слова дат
    date_keywords = [
        "завтра", "післязавтра", "сьогодні",
        "понеділок", "вівторок", "середа", "четвер",
        "п'ятниця", "пятниця", "субота", "неділя",
        "січня", "лютого", "березня", "квітня", "травня", "червня",
        "липня", "серпня", "вересня", "жовтня", "листопада", "грудня",
        "через", "за", "наступний", "у ", "в ",
    ]

    # Перевіряємо ключові слова
    has_keyword = any(keyword in text_lower for keyword in date_keywords)

    # Перевіряємо числа
    has_numbers = bool(re.search(r"\d+", text))

    # Класичний формат ДД.ММ
    has_classic_format = bool(re.match(r"^\d{1,2}[./]\d{1,2}", text))

    return has_keyword or has_numbers or has_classic_format


def parse_date_input(text: str):
    """
    Головна функція парсингу дати
    Підтримує natural language та класичний формат
    """
    text = text.strip()

    # СПОЧАТКУ пробуємо natural language
    nat_date, nat_text = parse_natural_date(text)
    if nat_date:
        return nat_date, nat_text

    # Fallback на класичний формат

    # Формат: ДД.ММ.РРРР
    pattern1 = r"^(\d{1,2})\.(\d{1,2})\.(\d{4})\s*(.*)$"
    match = re.match(pattern1, text)

    if match:
        day, month, year, remaining = match.groups()
        try:
            date_obj = date(int(year), int(month), int(day))
            return date_obj, remaining.strip()
        except ValueError:
            return None, None

    # Формат: ДД.ММ (поточний рік)
    pattern2 = r"^(\d{1,2})\.(\d{1,2})\s*(.*)$"
    match = re.match(pattern2, text)

    if match:
        day, month, remaining = match.groups()
        current_year = datetime.now().year
        try:
            date_obj = date(current_year, int(month), int(day))
            return date_obj, remaining.strip()
        except ValueError:
            return None, None

    return None, None


# ============ Існуючі функції (без змін) ============

def get_next_month_date(current_date: date, original_day: int = None):
    """Отримання дати наступного місяця для щомісячних нагадувань"""
    if current_date.month == 12:
        next_year = current_date.year + 1
        next_month = 1
    else:
        next_year = current_date.year
        next_month = current_date.month + 1

    days_in_next = monthrange(next_year, next_month)[1]

    if original_day:
        day = min(original_day, days_in_next)
    else:
        day = min(current_date.day, days_in_next)

    return date(next_year, next_month, day)


def get_next_year_date(current_date: date):
    """Отримання дати наступного року для щорічних нагадувань"""
    next_year = current_date.year + 1

    if current_date.month == 2 and current_date.day == 29:
        try:
            return date(next_year, 2, 29)
        except ValueError:
            return date(next_year, 2, 28)

    return date(next_year, current_date.month, current_date.day)


def format_date(date_obj: date) -> str:
    """Форматування дати українською"""
    months = {
        1: "січня", 2: "лютого", 3: "березня", 4: "квітня",
        5: "травня", 6: "червня", 7: "липня", 8: "серпня",
        9: "вересня", 10: "жовтня", 11: "листопада", 12: "грудня"
    }
    return f"{date_obj.day} {months[date_obj.month]} {date_obj.year}"


def get_week_dates(date_obj: date):
    """Отримання дат тижня (понеділок-неділя)"""
    monday = date_obj - timedelta(days=date_obj.weekday())
    week_dates = [monday + timedelta(days=i) for i in range(7)]
    return week_dates


def get_next_monday(current_date: date):
    """Отримання дати наступного понеділка"""
    days_until_monday = 7 - current_date.weekday()
    if days_until_monday == 0:
        days_until_monday = 7
    return current_date + timedelta(days=days_until_monday)


def get_next_month_first_day(current_date: date):
    """Отримання першого числа наступного місяця"""
    if current_date.month == 12:
        return date(current_date.year + 1, 1, 1)
    else:
        return date(current_date.year, current_date.month + 1, 1)