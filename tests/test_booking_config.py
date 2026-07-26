import os
from datetime import timedelta
from zoneinfo import ZoneInfo
import booking_config


def test_defaults(monkeypatch):
    for k in ["BOOKING_HOLD_MINUTES", "BOOKING_HORIZON_DAYS", "BOOKING_LEAD_HOURS",
              "WORK_TIMES", "WORK_WEEKDAYS"]:
        monkeypatch.delenv(k, raising=False)
    cfg = booking_config.load()
    assert cfg.work_times == ["12:00", "14:00", "16:00"]
    assert cfg.work_weekdays == {0, 1, 2, 3, 4}
    assert cfg.horizon_days == 30
    assert cfg.lead == timedelta(hours=3)
    assert cfg.hold == timedelta(minutes=30)
    assert cfg.tz == ZoneInfo("Europe/Prague")


def test_overrides(monkeypatch):
    monkeypatch.setenv("WORK_TIMES", "10:00,18:00")
    monkeypatch.setenv("WORK_WEEKDAYS", "0,2,4")
    monkeypatch.setenv("BOOKING_LEAD_HOURS", "6")
    cfg = booking_config.load()
    assert cfg.work_times == ["10:00", "18:00"]
    assert cfg.work_weekdays == {0, 2, 4}
    assert cfg.lead == timedelta(hours=6)
