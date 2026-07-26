import asyncio
import json
import os
from datetime import datetime, timedelta, timezone

SCOPES = ["https://www.googleapis.com/auth/calendar"]
SESSION_MINUTES = 60


def _parse_dt(s: str) -> datetime:
    # Google отдаёт RFC3339, напр. "2026-07-27T12:00:00Z"
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


class GoogleCalendar:
    def __init__(self, service, cal_bookings: str, cal_personal: str) -> None:
        self._svc = service
        self._cal_bookings = cal_bookings
        self._cal_personal = cal_personal

    @classmethod
    def from_env(cls) -> "GoogleCalendar":
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        raw = os.environ["GOOGLE_SA_CREDENTIALS"]
        info = json.loads(raw) if raw.strip().startswith("{") else json.load(open(raw))
        creds = service_account.Credentials.from_service_account_info(info, scopes=SCOPES)
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return cls(
            service,
            os.environ["CALENDAR_ID_BOOKINGS"],
            os.environ["CALENDAR_ID_PERSONAL"],
        )

    async def busy(self, start: datetime, end: datetime) -> list[tuple[datetime, datetime]]:
        body = {
            "timeMin": start.astimezone(timezone.utc).isoformat(),
            "timeMax": end.astimezone(timezone.utc).isoformat(),
            "items": [{"id": self._cal_bookings}, {"id": self._cal_personal}],
        }
        resp = await asyncio.to_thread(
            lambda: self._svc.freebusy().query(body=body).execute()
        )
        intervals: list[tuple[datetime, datetime]] = []
        for cal in resp.get("calendars", {}).values():
            for slot in cal.get("busy", []):
                intervals.append((_parse_dt(slot["start"]), _parse_dt(slot["end"])))
        return intervals

    async def create_event(self, slot_utc: datetime, title: str, description: str) -> str:
        start = slot_utc.astimezone(timezone.utc)
        end = start + timedelta(minutes=SESSION_MINUTES)
        body = {
            "summary": f"Консультация — {title}",
            "description": description,
            "start": {"dateTime": start.isoformat(), "timeZone": "UTC"},
            "end": {"dateTime": end.isoformat(), "timeZone": "UTC"},
        }
        resp = await asyncio.to_thread(
            lambda: self._svc.events()
            .insert(calendarId=self._cal_bookings, body=body)
            .execute()
        )
        return resp["id"]

    async def delete_event(self, event_id: str) -> None:
        await asyncio.to_thread(
            lambda: self._svc.events()
            .delete(calendarId=self._cal_bookings, eventId=event_id)
            .execute()
        )
