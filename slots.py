from datetime import datetime, date, time, timedelta, timezone
from zoneinfo import ZoneInfo


def _overlaps(start: datetime, end: datetime,
              busy: list[tuple[datetime, datetime]]) -> bool:
    return any(b_start < end and start < b_end for b_start, b_end in busy)


def free_slots(
    now: datetime,
    busy: list[tuple[datetime, datetime]],
    holds: list[datetime],
    *,
    work_times: list[str],
    work_weekdays: set[int],
    horizon_days: int,
    lead: timedelta,
    tz: ZoneInfo,
) -> list[datetime]:
    now = now.astimezone(timezone.utc)
    earliest = now + lead
    horizon_end = now + timedelta(days=horizon_days)
    hold_set = {h.astimezone(timezone.utc) for h in holds}
    slot_len = timedelta(hours=1)  # длительность для проверки пересечения

    result: list[datetime] = []
    start_day = now.astimezone(tz).date()
    for offset in range(horizon_days + 1):
        d = start_day + timedelta(days=offset)
        if d.weekday() not in work_weekdays:
            continue
        for hhmm in work_times:
            hh, mm = (int(x) for x in hhmm.split(":"))
            local = datetime.combine(d, time(hh, mm), tzinfo=tz)
            start = local.astimezone(timezone.utc)
            if start < earliest or start > horizon_end:
                continue
            if start in hold_set:
                continue
            if _overlaps(start, start + slot_len, busy):
                continue
            result.append(start)
    return sorted(result)
