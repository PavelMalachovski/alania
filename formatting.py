from datetime import datetime
from zoneinfo import ZoneInfo

PRICE_TEXT = "100 € / 10000 ₽"

TZ_PRAGUE = ZoneInfo("Europe/Prague")
TZ_MOSCOW = ZoneInfo("Europe/Moscow")
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def format_slot_human(dt_utc: datetime) -> str:
    prague = dt_utc.astimezone(TZ_PRAGUE)
    moscow = dt_utc.astimezone(TZ_MOSCOW)
    wd = _WEEKDAYS_RU[prague.weekday()]
    return (
        f"{wd} {prague:%d.%m} · {prague:%H:%M} Прага "
        f"({moscow:%H:%M} Мск)"
    )
