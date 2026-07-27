import os
from dataclasses import dataclass
from datetime import timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True)
class BookingConfig:
    work_times: list[str]
    work_weekdays: set[int]
    horizon_days: int
    lead: timedelta
    hold: timedelta
    tz: ZoneInfo


def load() -> BookingConfig:
    times = os.environ.get("WORK_TIMES", "12:00,14:00,16:00")
    weekdays = os.environ.get("WORK_WEEKDAYS", "0,1,2,3,4")
    return BookingConfig(
        work_times=[t.strip() for t in times.split(",") if t.strip()],
        work_weekdays={int(x) for x in weekdays.split(",") if x.strip()},
        horizon_days=int(os.environ.get("BOOKING_HORIZON_DAYS", "30")),
        lead=timedelta(hours=int(os.environ.get("BOOKING_LEAD_HOURS", "3"))),
        hold=timedelta(minutes=int(os.environ.get("BOOKING_HOLD_MINUTES", "30"))),
        tz=ZoneInfo(os.environ.get("TZ", "Europe/Prague")),
    )
