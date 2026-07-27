from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from slots import free_slots

TZ = ZoneInfo("Europe/Prague")
CFG = dict(
    work_times=["12:00", "14:00", "16:00"],
    work_weekdays={0, 1, 2, 3, 4},
    horizon_days=30,
    lead=timedelta(hours=3),
    tz=TZ,
)


def _utc(y, mo, d, h, mi=0):
    # локальное пражское время -> UTC
    return datetime(y, mo, d, h, mi, tzinfo=TZ).astimezone(timezone.utc)


def test_empty_calendar_weekday_has_three_slots():
    now = _utc(2026, 7, 27, 6)  # Пн 06:00 Прага
    got = free_slots(now, [], [], **CFG)
    monday = [s for s in got if s.astimezone(TZ).date() == datetime(2026, 7, 27).date()]
    assert [s.astimezone(TZ).strftime("%H:%M") for s in monday] == ["12:00", "14:00", "16:00"]


def test_weekend_excluded():
    now = _utc(2026, 7, 27, 6)
    got = free_slots(now, [], [], **CFG)
    weekdays = {s.astimezone(TZ).weekday() for s in got}
    assert weekdays <= {0, 1, 2, 3, 4}


def test_busy_interval_removes_overlapping_slot():
    now = _utc(2026, 7, 27, 6)
    busy = [(_utc(2026, 7, 27, 12), _utc(2026, 7, 27, 13))]  # занял 12:00
    got = free_slots(now, busy, [], **CFG)
    monday = [s.astimezone(TZ).strftime("%H:%M") for s in got
              if s.astimezone(TZ).date() == datetime(2026, 7, 27).date()]
    assert monday == ["14:00", "16:00"]


def test_hold_removes_slot():
    now = _utc(2026, 7, 27, 6)
    hold = _utc(2026, 7, 27, 14)
    got = free_slots(now, [], [hold], **CFG)
    monday = [s.astimezone(TZ).strftime("%H:%M") for s in got
              if s.astimezone(TZ).date() == datetime(2026, 7, 27).date()]
    assert monday == ["12:00", "16:00"]


def test_lead_time_hides_too_soon_slot():
    now = _utc(2026, 7, 27, 10)  # 10:00 Прага, lead 3ч → 12:00 отсекается (до 13:00 нельзя)
    got = free_slots(now, [], [], **CFG)
    monday = [s.astimezone(TZ).strftime("%H:%M") for s in got
              if s.astimezone(TZ).date() == datetime(2026, 7, 27).date()]
    assert monday == ["14:00", "16:00"]


def test_horizon_cutoff():
    now = _utc(2026, 7, 27, 6)
    got = free_slots(now, [], [], **CFG)
    assert max(got) <= now + timedelta(days=30)


def test_results_sorted_and_utc():
    now = _utc(2026, 7, 27, 6)
    got = free_slots(now, [], [], **CFG)
    assert got == sorted(got)
    assert all(s.tzinfo == timezone.utc for s in got)
