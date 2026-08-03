from datetime import datetime
from zoneinfo import ZoneInfo

PRICE_TEXT = "100 € / 10000 ₽"

# Крипто-оплата: адрес и сумма фиксированные, живут здесь рядом с ценой —
# используются и в тексте экрана, и в кнопке копирования адреса.
CRYPTO_ADDRESS = "TWCyAwzPrnevmWPei4RdreuQCXbDD6JXhh"
CRYPTO_AMOUNT_TEXT = "116 USDT · сеть TRC20"

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
