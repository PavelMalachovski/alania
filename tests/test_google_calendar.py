import pytest
from datetime import datetime, timezone
from google_calendar import GoogleCalendar


class FakeExec:
    def __init__(self, result): self._result = result
    def execute(self): return self._result


class FakeFreebusy:
    def __init__(self, store): self.store = store
    def query(self, body=None):
        self.store["freebusy_body"] = body
        return FakeExec({
            "calendars": {
                "cal_b": {"busy": [{"start": "2026-07-27T12:00:00Z", "end": "2026-07-27T13:00:00Z"}]},
                "cal_p": {"busy": [{"start": "2026-07-27T16:00:00Z", "end": "2026-07-27T17:00:00Z"}]},
            }
        })


class FakeEvents:
    def __init__(self, store): self.store = store
    def insert(self, calendarId=None, body=None, conferenceDataVersion=None):
        self.store["insert"] = {"calendarId": calendarId, "body": body}
        return FakeExec({"id": "evt_123"})
    def delete(self, calendarId=None, eventId=None):
        self.store["delete"] = {"calendarId": calendarId, "eventId": eventId}
        return FakeExec("")


class FakeService:
    def __init__(self): self.store = {}
    def freebusy(self): return FakeFreebusy(self.store)
    def events(self): return FakeEvents(self.store)


@pytest.mark.asyncio
async def test_busy_merges_two_calendars():
    svc = FakeService()
    gc = GoogleCalendar(svc, "cal_b", "cal_p")
    got = await gc.busy(datetime(2026, 7, 27, tzinfo=timezone.utc),
                         datetime(2026, 7, 28, tzinfo=timezone.utc))
    assert (datetime(2026, 7, 27, 12, tzinfo=timezone.utc),
            datetime(2026, 7, 27, 13, tzinfo=timezone.utc)) in got
    assert (datetime(2026, 7, 27, 16, tzinfo=timezone.utc),
            datetime(2026, 7, 27, 17, tzinfo=timezone.utc)) in got
    # оба календаря попали в запрос
    ids = {c["id"] for c in svc.store["freebusy_body"]["items"]}
    assert ids == {"cal_b", "cal_p"}


@pytest.mark.asyncio
async def test_create_event_returns_id_and_targets_bookings_calendar():
    svc = FakeService()
    gc = GoogleCalendar(svc, "cal_b", "cal_p")
    eid = await gc.create_event(
        datetime(2026, 7, 27, 10, tzinfo=timezone.utc), "Марина", "запрос: выгорание")
    assert eid == "evt_123"
    assert svc.store["insert"]["calendarId"] == "cal_b"
    assert "Марина" in svc.store["insert"]["body"]["summary"]


@pytest.mark.asyncio
async def test_delete_event_targets_bookings_calendar():
    svc = FakeService()
    gc = GoogleCalendar(svc, "cal_b", "cal_p")
    await gc.delete_event("evt_123")
    assert svc.store["delete"] == {"calendarId": "cal_b", "eventId": "evt_123"}
