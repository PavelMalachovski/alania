from datetime import datetime, timezone
from formatting import PRICE_TEXT, format_slot_human


def test_price_text():
    assert PRICE_TEXT == "100 € / 10000 ₽"


def test_format_slot_summer_cest():
    # 10:00 UTC = 12:00 Прага (CEST, UTC+2) = 13:00 Мск (Мск всегда UTC+3, летом разница 1ч)
    dt = datetime(2026, 7, 27, 10, 0, tzinfo=timezone.utc)
    assert format_slot_human(dt) == "Пн 27.07 · 12:00 Прага (13:00 Мск)"


def test_format_slot_winter_cet():
    # 11:00 UTC = 12:00 Прага (CET, UTC+1 зимой) = 14:00 Мск (Мск всегда UTC+3)
    dt = datetime(2026, 1, 12, 11, 0, tzinfo=timezone.utc)
    assert format_slot_human(dt) == "Пн 12.01 · 12:00 Прага (14:00 Мск)"
