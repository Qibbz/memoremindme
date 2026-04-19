#!/usr/bin/env python3
# test_natural_language.py - Тестування парсингу природної мови

from utils import parse_natural_date, looks_like_reminder, parse_date_input, format_date
from datetime import date, timedelta


def test_case(description, input_text, expected_date=None, expected_text=""):
    """Допоміжна функція для тестування"""
    print(f"\n📝 Тест: {description}")
    print(f"   Ввід: '{input_text}'")

    date_obj, text = parse_date_input(input_text)

    if date_obj:
        print(f"   ✅ Дата: {format_date(date_obj)}")
        print(f"   📝 Текст: '{text}'")

        if expected_date:
            if date_obj == expected_date:
                print("   🎯 Дата вірна!")
            else:
                print(f"   ⚠️ Очікувалось: {format_date(expected_date)}")
    else:
        print("   ❌ Дату не розпізнано")

    is_reminder = looks_like_reminder(input_text)
    print(f"   🔍 looks_like_reminder: {is_reminder}")


def main():
    print("=" * 50)
    print("ТЕСТУВАННЯ NATURAL LANGUAGE ПАРСИНГУ")
    print("=" * 50)

    today = date.today()
    tomorrow = today + timedelta(days=1)
    day_after = today + timedelta(days=2)
    in_3_days = today + timedelta(days=3)

    # Тести
    test_case("Завтра", "завтра тест", tomorrow, "тест")
    test_case("Післязавтра", "післязавтра зустріч", day_after, "зустріч")
    test_case("Через 3 дні", "через 3 дні подорож", in_3_days, "подорож")
    test_case("Через три дні (словами)", "через три дні подорож", in_3_days, "подорож")
    test_case("15 травня", "15 травня день народження", None, "день народження")
    test_case("Класичний формат", "15.05 Оплатити інтернет", None, "Оплатити інтернет")
    test_case("З роком", "15.05.2026 Зустріч з лікарем", date(2026, 5, 15), "Зустріч з лікарем")
    test_case("Просто текст", "привіт як справи", None, "")

    print("\n" + "=" * 50)
    print("Тестування завершено!")
    print("=" * 50)


if __name__ == "__main__":
    main()