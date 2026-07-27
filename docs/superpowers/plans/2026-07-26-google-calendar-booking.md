# Запись через Google Calendar — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Переделать запись на консультацию так, чтобы источником правды о занятости был Google Calendar Ланы, слот занимали только оплатившие, а сессии автоматически попадали в её календарь — плюс попутно закрыть блокеры 1–5,7,8,9,12 из ревью.

**Architecture:** Три модуля по ответственности. `slots.py` — чистая функция расчёта доступности (без I/O, покрыта таблицей кейсов). `google_calendar.py` — тонкий async-клиент Google (синхронный `google-api-python-client` обёрнут в `asyncio.to_thread`). `handlers/booking.py` — тонкий UI поверх них и таблицы-зеркала `bookings`. Настоящее событие в календаре создаётся только после «Я оплатил(а)»; до этого слот держится 30-минутным холдом в нашей БД с ленивым истечением (фоновых задач нет).

**Tech Stack:** Python 3.12, aiogram 3.x, SQLAlchemy 2.0 async + aiosqlite/asyncpg, `google-auth`, `google-api-python-client`, pytest + pytest-asyncio.

## Global Constraints

- Python 3.12, aiogram 3.14, SQLAlchemy 2.0 async style (`Mapped`/`mapped_column`).
- Тайзмона Ланы: `Europe/Prague`. Московское время показываем как справку: `Europe/Moscow`.
- Все `datetime` в БД и во внутренних расчётах — **aware UTC**. Конвертация в пояса только на отображении.
- Тексты сообщений — модульные константы `UPPER_SNAKE` рядом с хендлером.
- Пользовательский текст в HTML-уведомления админам экранировать через `aiogram.html.quote(...)` (parse_mode=HTML включён глобально).
- Колбэки фильтровать через `F.data == "..."` / `F.data.startswith(...)`, не `lambda`.
- Хендлеры колбэков не вызывают `callback.answer()` вручную — это делает `CallbackSafetyMiddleware`. Исключение — ответ с текстом/алертом.
- Цена консультации везде: **100 € / 10000 ₽** (единая константа).
- Каждый `callback_data` в клавиатуре обязан иметь хендлер.
- Проверка компиляции: `python -m py_compile main.py database.py middlewares.py filters.py followup.py slots.py google_calendar.py handlers/*.py keyboards/inline.py`.
- Тесты на Windows-консоли запускать с `PYTHONIOENCODING=utf-8`.
- Env-переменные (новые): `GOOGLE_SA_CREDENTIALS`, `CALENDAR_ID_BOOKINGS`, `CALENDAR_ID_PERSONAL`, `BOOKING_HOLD_MINUTES=30`, `BOOKING_HORIZON_DAYS=30`, `BOOKING_LEAD_HOURS=3`, `WORK_TIMES=12:00,14:00,16:00`, `WORK_WEEKDAYS=0,1,2,3,4`.

---

## File Structure

- **Create** `slots.py` — чистый расчёт доступных слотов. Ответственность: только арифметика окон/занятости/холдов. Ноль I/O.
- **Create** `google_calendar.py` — async-клиент Google Calendar (freebusy + events). Единственное место с HTTP к Google.
- **Create** `formatting.py` — общие константы/хелперы отображения: `PRICE_TEXT`, `format_slot_human(dt_utc)`.
- **Create** `tests/test_slots.py`, `tests/test_google_calendar.py`, `tests/test_formatting.py`, `tests/test_booking_flow.py`, `tests/conftest.py` (фейковая сессия + фабрики апдейтов).
- **Modify** `database.py` — новая схема `Booking` (`slot_start`, `held_until`, `google_event_id`, `calendar_sync_failed`).
- **Modify** `handlers/booking.py` — переписать поверх `slots.py`/`google_calendar.py`.
- **Modify** `handlers/admin.py` — `/bookings`, подтверждение/отклонение оплаты (delete_event).
- **Modify** `handlers/consultation.py` — цена через `PRICE_TEXT`.
- **Modify** `handlers/quiz.py`, `handlers/lead.py` — не нужно; catch-all кладём в новый роутер.
- **Create** `handlers/fallback.py` — catch-all для потерянного FSM (блокер 4). Регистрируется **последним**.
- **Modify** `keyboards/inline.py` — `booking_*` клавиатуры, `quiz_result_kb` (+«Записаться»), экран «холд истёк»/«Google недоступен».
- **Modify** `followup.py` — напоминание за сутки до сессии.
- **Modify** `handlers/__init__.py` — подключить `fallback_router` последним.
- **Modify** `main.py` — прокинуть booking-конфиг и google-клиент в workflow data.
- **Modify** `requirements.txt`, `.env.example`, `README.md`.

---

## Task 1: Зависимости, схема Booking, тестовый каркас

**Files:**
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`
- Modify: `database.py:55-69` (класс `Booking`)
- Create: `tests/conftest.py`
- Modify: `.env.example`

**Interfaces:**
- Produces: модель `Booking(id, telegram_id, slot_start: datetime, status: str, held_until: datetime|None, google_event_id: str|None, calendar_sync_failed: bool, created_at)`. Статусы: `"held"`, `"pay_claimed"`, `"confirmed"`, `"cancelled"`.
- Produces: `tests/conftest.py` с фикстурой `db` (инициализирует sqlite in-memory через `init_db`) и хелперами.

- [ ] **Step 1: Добавить зависимости**

В `requirements.txt` добавить строки:
```
google-auth==2.35.0
google-api-python-client==2.149.0
```
В `requirements-dev.txt` добавить:
```
pytest-asyncio
```

- [ ] **Step 2: Установить**

Run: `pip install -r requirements.txt -r requirements-dev.txt`
Expected: успешная установка.

- [ ] **Step 3: Переписать модель Booking**

В `database.py` заменить класс `Booking` (строки 55–69) на:
```python
class Booking(Base):
    """Запись на слот. Статусы:
    held — слот держится за клиентом на время оплаты (held_until);
    pay_claimed — нажал «Я оплатил(а)», событие в календаре создано;
    confirmed — Лана подтвердила; cancelled — Лана отклонила / отменено."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, index=True)
    slot_start: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="held")
    held_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    google_event_id: Mapped[str | None] = mapped_column(String(1024))
    calendar_sync_failed: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
```
Удалить импорты `Date`, `UniqueConstraint` из `database.py`, если больше не используются (проверить: `Date` использовался только в `Booking.slot_date`). Оставить `DateTime`, `func`, `BigInteger`, `String`.

- [ ] **Step 4: Создать tests/conftest.py**

```python
import pytest
import pytest_asyncio

import database
from database import init_db, close_db


@pytest_asyncio.fixture
async def db():
    await init_db("sqlite+aiosqlite:///:memory:")
    yield
    await close_db()
    database.engine = None
    database.async_session = None
```

- [ ] **Step 5: Проверить, что схема создаётся**

Создать временный тест `tests/test_schema_smoke.py`:
```python
import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from database import Booking, get_session


@pytest.mark.asyncio
async def test_booking_roundtrip(db):
    async with get_session() as s:
        s.add(Booking(telegram_id=1, slot_start=datetime(2026, 7, 27, 10, tzinfo=timezone.utc)))
        await s.commit()
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "held"
    assert b.calendar_sync_failed is False
```

- [ ] **Step 6: Прогнать**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_schema_smoke.py -v`
Expected: PASS. Затем удалить `tests/test_schema_smoke.py` (был проверкой каркаса).

- [ ] **Step 7: Обновить .env.example**

Добавить в `.env.example`:
```
# Google Calendar (запись на консультацию)
GOOGLE_SA_CREDENTIALS=/path/to/service-account.json
CALENDAR_ID_BOOKINGS=xxxxx@group.calendar.google.com
CALENDAR_ID_PERSONAL=lana@gmail.com
BOOKING_HOLD_MINUTES=30
BOOKING_HORIZON_DAYS=30
BOOKING_LEAD_HOURS=3
WORK_TIMES=12:00,14:00,16:00
WORK_WEEKDAYS=0,1,2,3,4
```

- [ ] **Step 8: Commit**

```bash
git add requirements.txt requirements-dev.txt database.py tests/conftest.py .env.example
git commit -m "Схема Booking под холды+Google, зависимости, тестовый каркас"
```

---

## Task 2: formatting.py — цена и человекочитаемый слот (блокеры 1, 8)

**Files:**
- Create: `formatting.py`
- Create: `tests/test_formatting.py`

**Interfaces:**
- Produces: `PRICE_TEXT: str` = `"100 € / 10000 ₽"`.
- Produces: `format_slot_human(dt_utc: datetime) -> str` → напр. `"Пн 27.07 · 12:00 Прага (14:00 Мск)"`. Вход — aware UTC.

- [ ] **Step 1: Написать падающие тесты**

`tests/test_formatting.py`:
```python
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
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_formatting.py -v`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: Реализовать formatting.py**

```python
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
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_formatting.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add formatting.py tests/test_formatting.py
git commit -m "formatting.py: единая цена и слот в двух поясах (блокеры 1,8)"
```

---

## Task 3: slots.py — чистый расчёт доступности (сердце фичи, блокер 7)

**Files:**
- Create: `slots.py`
- Create: `tests/test_slots.py`

**Interfaces:**
- Consumes: ничего (чистая функция).
- Produces:
  `free_slots(now: datetime, busy: list[tuple[datetime, datetime]], holds: list[datetime], *, work_times: list[str], work_weekdays: set[int], horizon_days: int, lead: timedelta, tz: ZoneInfo) -> list[datetime]`
  Возвращает отсортированный список aware-UTC datetime — начал свободных слотов.
  - Слот = дата (в пределах `horizon_days` от `now`, только `work_weekdays`) × время из `work_times`, интерпретированное в `tz`, переведённое в UTC.
  - Исключается, если: раньше `now + lead`; пересекается с любым интервалом `busy`; совпадает с любым `holds` (холд — точное начало слота).

- [ ] **Step 1: Написать таблицу падающих тестов**

`tests/test_slots.py`:
```python
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
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_slots.py -v`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: Реализовать slots.py**

```python
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
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_slots.py -v`
Expected: PASS (7 тестов).

- [ ] **Step 5: Commit**

```bash
git add slots.py tests/test_slots.py
git commit -m "slots.py: чистый расчёт доступности с холдами и lead-буфером"
```

---

## Task 4: google_calendar.py — async-клиент Google

**Files:**
- Create: `google_calendar.py`
- Create: `tests/test_google_calendar.py`

**Interfaces:**
- Consumes: ничего из наших модулей.
- Produces: класс `GoogleCalendar`:
  - `GoogleCalendar(service, cal_bookings: str, cal_personal: str)` — конструктор принимает **готовый** Google API `service` (для тестов — подставной), чтобы клиент не зависел от авторизации.
  - `classmethod from_env() -> GoogleCalendar` — строит реальный service из env (не тестируется юнитом).
  - `async busy(start: datetime, end: datetime) -> list[tuple[datetime, datetime]]` — freebusy по двум календарям, объединённые интервалы (aware UTC).
  - `async create_event(slot_utc: datetime, title: str, description: str) -> str` — events.insert в `cal_bookings`, возвращает `event_id`. Длительность 60 мин.
  - `async delete_event(event_id: str) -> None` — events.delete из `cal_bookings`.
- Все методы гоняют блокирующий `google-api-python-client` через `asyncio.to_thread`.

- [ ] **Step 1: Написать падающие тесты с подставным service**

`tests/test_google_calendar.py`:
```python
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
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_google_calendar.py -v`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: Реализовать google_calendar.py**

```python
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
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_google_calendar.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add google_calendar.py tests/test_google_calendar.py
git commit -m "google_calendar.py: async-клиент freebusy/insert/delete через to_thread"
```

---

## Task 5: main.py + booking-конфиг в workflow data

**Files:**
- Modify: `main.py:36-55`
- Create: `booking_config.py`

**Interfaces:**
- Produces: `booking_config.load() -> BookingConfig` — dataclass с полями `work_times: list[str]`, `work_weekdays: set[int]`, `horizon_days: int`, `lead: timedelta`, `hold: timedelta`, `tz: ZoneInfo`. Читает env с дефолтами из Global Constraints.
- Produces: workflow data ключи `booking_config: BookingConfig` и `gcal: GoogleCalendar`, доступные в хендлерах как аргументы `booking_config`, `gcal`.

- [ ] **Step 1: Написать тест booking_config**

`tests/test_booking_config.py`:
```python
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
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_config.py -v`
Expected: FAIL (модуль не найден).

- [ ] **Step 3: Реализовать booking_config.py**

```python
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
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_config.py -v`
Expected: PASS.

- [ ] **Step 5: Прокинуть в main.py**

В `main.py` после `database_url = os.environ["DATABASE_URL"]` (строка ~34) добавить:
```python
    import booking_config
    from google_calendar import GoogleCalendar

    bcfg = booking_config.load()
    gcal = GoogleCalendar.from_env()
```
Изменить запуск polling (строка ~55) на:
```python
        await dp.start_polling(bot, admin_ids=admin_ids, booking_config=bcfg, gcal=gcal)
```

- [ ] **Step 6: Проверить компиляцию**

Run: `python -m py_compile main.py booking_config.py`
Expected: без ошибок.

- [ ] **Step 7: Commit**

```bash
git add booking_config.py tests/test_booking_config.py main.py
git commit -m "booking_config + прокидка gcal/конфига в workflow data"
```

---

## Task 6: booking.py — выбор слота (дни → времена → холд), ошибка Google (блокеры 2,3,4-booking)

**Files:**
- Modify: `handlers/booking.py` (переписать)
- Modify: `keyboards/inline.py` (booking-клавиатуры + экран ошибки)
- Create: `tests/test_booking_flow.py` (наполняется здесь и в Task 7)

**Interfaces:**
- Consumes: `slots.free_slots`, `GoogleCalendar.busy`, `BookingConfig`, `Booking`, `formatting.format_slot_human`, `PRICE_TEXT`.
- Produces: хендлеры колбэков `booking_start`/`consultation_pay` (алиас), `book_day:<iso-date>`, `book_slot:<iso-datetime-utc>`. `callback_data` слота несёт **UTC ISO** начала слота (напр. `book_slot:2026-07-27T10:00:00+00:00`), длина ≤64.
- Produces: helper `active_holds(session, cfg, now) -> list[datetime]` (список `slot_start` строк со `status=held` и `held_until > now`) и `user_has_active_booking(session, tg_id, now) -> bool`.

- [ ] **Step 1: Написать падающие тесты выбора слота**

Добавить в `tests/test_booking_flow.py` каркас фейковой сессии (переиспользуем из ревью) и тесты. Полный файл:
```python
import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser

import database
from database import Booking, get_session, init_db, close_db
from handlers import setup_routers
from middlewares import CallbackSafetyMiddleware, EventLoggingMiddleware
import booking_config

CLIENT_ID, ADMIN_ID = 501, 902
TZ = ZoneInfo("Europe/Prague")


class FakeGCal:
    """Подставной Google-клиент. Управляем busy/падениями из теста."""
    def __init__(self):
        self.busy_intervals = []
        self.raise_on_busy = False
        self.events = {}
        self._n = 0
        self.deleted = []
    async def busy(self, start, end):
        if self.raise_on_busy:
            raise RuntimeError("google down")
        return list(self.busy_intervals)
    async def create_event(self, slot_utc, title, description):
        self._n += 1
        eid = f"evt_{self._n}"
        self.events[eid] = slot_utc
        return eid
    async def delete_event(self, event_id):
        self.deleted.append(event_id)
        self.events.pop(event_id, None)


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.log = []
        self._mid = 1000
    async def close(self): pass
    async def stream_content(self, *a, **k):
        yield b""
    async def make_request(self, bot, method, timeout=None):
        self._mid += 1
        self.log.append((type(method).__name__, method.model_dump(exclude_none=True)))
        name = type(method).__name__
        if name in ("SendMessage", "EditMessageText", "SendDocument", "CopyMessage"):
            data = method.model_dump(exclude_none=True)
            return Message(message_id=self._mid, date=datetime.now(),
                           chat=Chat(id=data.get("chat_id", CLIENT_ID), type="private"),
                           from_user=TgUser(id=1, is_bot=True, first_name="bot"),
                           text=data.get("text") or data.get("caption") or "")
        return True


import pytest_asyncio


@pytest_asyncio.fixture
async def env():
    await init_db("sqlite+aiosqlite:///:memory:")
    session = FakeSession()
    bot = Bot(token="1:AA", session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    gcal = FakeGCal()
    dp = Dispatcher()
    dp.callback_query.outer_middleware(CallbackSafetyMiddleware())
    dp.callback_query.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(EventLoggingMiddleware())
    dp.include_router(setup_routers())
    cfg = booking_config.load()
    dp["admin_ids"] = [ADMIN_ID]
    dp["booking_config"] = cfg
    dp["gcal"] = gcal
    yield dp, bot, gcal, session
    await close_db()
    database.engine = None
    database.async_session = None


def _client():
    return TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина", username="marina")


async def press(dp, bot, data, user=None, chat_id=CLIENT_ID):
    user = user or _client()
    upd = Update(update_id=1, callback_query=CallbackQuery(
        id="1", from_user=user, chat_instance="ci", data=data,
        message=Message(message_id=777, date=datetime.now(),
                        chat=Chat(id=chat_id, type="private"),
                        from_user=TgUser(id=1, is_bot=True, first_name="bot"), text="x")))
    await dp.feed_update(bot, upd)


def last_kb(session, chat_id=CLIENT_ID):
    for name, d in reversed(session.log):
        if d.get("chat_id") == chat_id and d.get("reply_markup"):
            return d["reply_markup"]["inline_keyboard"]
    return []


def find_cb(session, prefix, chat_id=CLIENT_ID):
    for row in last_kb(session, chat_id):
        for b in row:
            if (b.get("callback_data") or "").startswith(prefix):
                return b["callback_data"]
    return None


@pytest.mark.asyncio
async def test_booking_shows_days_from_gcal(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "booking_start")
    assert find_cb(session, "book_day:") is not None


@pytest.mark.asyncio
async def test_google_down_shows_error_not_dead_button(env):
    dp, bot, gcal, session = env
    gcal.raise_on_busy = True
    await press(dp, bot, "booking_start")
    last_text = next(d for n, d in reversed(session.log)
                     if d.get("chat_id") == CLIENT_ID and d.get("text"))["text"]
    assert "недоступно" in last_text.lower()
    assert find_cb(session, "booking_start") is not None  # кнопка «попробовать снова»


@pytest.mark.asyncio
async def test_pick_time_creates_hold(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "booking_start")
    day = find_cb(session, "book_day:")
    await press(dp, bot, day)
    slot = find_cb(session, "book_slot:")
    await press(dp, bot, slot)
    async with get_session() as s:
        from sqlalchemy import select
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "held"
    assert b.held_until is not None
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v`
Expected: FAIL (старый booking.py не создаёт холдов / нет нужного поведения).

- [ ] **Step 3: Переписать keyboards/inline.py — booking-часть**

Заменить `booking_days_kb`, `booking_times_kb` (строки 48–64) и добавить экран ошибки. Клавиатуры принимают уже готовые списки:
```python
def booking_days_kb(days):
    """days — список (подпись «Пн 27.07», iso-дата)."""
    builder = InlineKeyboardBuilder()
    for label, iso in days:
        builder.button(text=label, callback_data=f"book_day:{iso}")
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(2)
    return builder.as_markup()


def booking_times_kb(day_iso: str, times):
    """times — список (подпись «12:00 Прага (14:00 Мск)», utc-iso начала слота)."""
    builder = InlineKeyboardBuilder()
    for label, slot_iso in times:
        builder.button(text=label, callback_data=f"book_slot:{slot_iso}")
    builder.button(text="⇦ К выбору дня", callback_data="booking_start")
    builder.adjust(1)
    return builder.as_markup()


def booking_error_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="↻ Попробовать снова", callback_data="booking_start")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В главное меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
```

> Проверка длины callback_data: `book_slot:2026-07-27T10:00:00+00:00` = 35 символов < 64. OK.

- [ ] **Step 4: Переписать handlers/booking.py**

```python
import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select

from booking_config import BookingConfig
from database import Booking, get_session
from formatting import PRICE_TEXT, format_slot_human, TZ_PRAGUE
from google_calendar import GoogleCalendar
from keyboards.inline import (
    admin_confirm_pay_kb,
    booking_days_kb,
    booking_error_kb,
    booking_pay_kb,
    booking_times_kb,
)
from slots import free_slots

router = Router()
logger = logging.getLogger(__name__)
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


async def _active_holds(session, now: datetime) -> list[datetime]:
    rows = (await session.execute(
        select(Booking.slot_start).where(
            Booking.status == "held", Booking.held_until > now
        )
    )).scalars()
    return [r if r.tzinfo else r.replace(tzinfo=timezone.utc) for r in rows]


async def _user_has_active(session, tg_id: int, now: datetime) -> bool:
    row = (await session.execute(
        select(Booking.id).where(
            Booking.telegram_id == tg_id,
            Booking.status.in_(["confirmed", "pay_claimed"])
            | ((Booking.status == "held") & (Booking.held_until > now)),
        ).limit(1)
    )).first()
    return row is not None


async def _load_free(gcal: GoogleCalendar, cfg: BookingConfig) -> list[datetime]:
    now = datetime.now(timezone.utc)
    horizon_end = now + timedelta(days=cfg.horizon_days)
    busy = await gcal.busy(now, horizon_end)
    async with get_session() as session:
        holds = await _active_holds(session, now)
    return free_slots(
        now, busy, holds,
        work_times=cfg.work_times, work_weekdays=cfg.work_weekdays,
        horizon_days=cfg.horizon_days, lead=cfg.lead, tz=cfg.tz,
    )


@router.callback_query(F.data.in_({"booking_start", "consultation_pay"}))
async def cb_booking_start(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google Calendar недоступен при показе слотов")
        await callback.message.edit_text(
            "○─── ☾ ───○\n\n"
            "Расписание сейчас недоступно 🤍 Попробуй через минуту "
            "или напиши Лане в личку — подберём время вручную.",
            reply_markup=booking_error_kb(),
        )
        return
    if not slots:
        await callback.message.edit_text(
            "○─── ☾ ───○\n\n"
            "Ближайшие две недели заняты 🤍 Напиши Лане в ЛС — "
            "подберём время индивидуально.",
            reply_markup=booking_error_kb(),
        )
        return
    days = sorted({s.astimezone(booking_config.tz).date() for s in slots})
    day_buttons = [
        (f"{_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}", d.isoformat())
        for d in days
    ]
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "<b>✦ Запись на консультацию</b>\n\n"
        "Сессии проходят по будням, время — Прага (в скобках московское).\n\n"
        "Выбери удобный день ⇩",
        reply_markup=booking_days_kb(day_buttons),
    )


@router.callback_query(F.data.startswith("book_day:"))
async def cb_book_day(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял день, выбери заново", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при показе времён")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    day_slots = [s for s in slots if s.astimezone(booking_config.tz).date() == d]
    if not day_slots:
        await callback.answer("На этот день уже нет свободного времени", show_alert=True)
        return
    time_buttons = [(format_slot_human(s).split("·", 1)[1].strip(), s.isoformat())
                    for s in day_slots]
    await callback.message.edit_text(
        f"<b>✦ {_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}</b>\n\n"
        "Выбери время ⇩",
        reply_markup=booking_times_kb(d.isoformat(), time_buttons),
    )


@router.callback_query(F.data.startswith("book_slot:"))
async def cb_book_slot(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        slot = datetime.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял слот, выбери заново", show_alert=True)
        return
    slot = slot.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)

    # слот всё ещё свободен?
    try:
        free = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при бронировании")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    if slot not in free:
        await callback.answer("Это время только что заняли 🤍 Выбери другое", show_alert=True)
        return

    async with get_session() as session:
        if await _user_has_active(session, callback.from_user.id, now):
            await callback.answer(
                "У тебя уже есть активная запись 🤍 Заверши её, прежде чем брать новую.",
                show_alert=True,
            )
            return
        booking = Booking(
            telegram_id=callback.from_user.id,
            slot_start=slot,
            status="held",
            held_until=now + booking_config.hold,
        )
        session.add(booking)
        await session.commit()
        booking_id = booking.id

    hold_local = (now + booking_config.hold).astimezone(booking_config.tz)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        f"<b>✦ Твой слот: {format_slot_human(slot)}</b>\n\n"
        f"● Стоимость: {PRICE_TEXT}\n\n"
        f"Время держим до {hold_local:%H:%M} (Прага). "
        "Оплати удобным способом и нажми «✓ Я оплатил(а)» ⇩\n"
        "Лана подтвердит запись, и тебе придёт сообщение.",
        reply_markup=booking_pay_kb(booking_id),
    )
```

> `cb_paid`, `_notify_admins`, `_client_line` — в Task 7 (они завязаны на create_event и уведомления). На этом шаге booking.py **временно** без `cb_paid`; тест `test_pick_time_creates_hold` от него не зависит.

- [ ] **Step 5: Прогнать тесты выбора слота**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k "days or google_down or hold"`
Expected: PASS (3 теста).

- [ ] **Step 6: Commit**

```bash
git add handlers/booking.py keyboards/inline.py tests/test_booking_flow.py
git commit -m "booking: выбор слота из Google, холд 30мин, лимит, обработка Google-down"
```

---

## Task 7: booking.py — оплата → событие в календаре; admin подтверждение/отклонение; /bookings (блокеры 5)

**Files:**
- Modify: `handlers/booking.py` (добавить `cb_paid`, `_notify_admins`, `_client_line`, `_event_description`)
- Modify: `handlers/admin.py` (confirm/reject pay, `/bookings`)
- Modify: `keyboards/inline.py` (`admin_confirm_pay_kb` → две кнопки)
- Modify: `tests/test_booking_flow.py` (добавить тесты)

**Interfaces:**
- Consumes: `GoogleCalendar.create_event/delete_event`, `Booking`, `format_slot_human`.
- Produces: колбэки `paid:<id>`, `confirm_pay:<id>`, `reject_pay:<id>`; команда `/bookings`.

- [ ] **Step 1: Написать падающие тесты оплаты/подтверждения**

Добавить в `tests/test_booking_flow.py`:
```python
async def _book_one(dp, bot, session):
    await press(dp, bot, "booking_start")
    await press(dp, bot, find_cb(session, "book_day:"))
    await press(dp, bot, find_cb(session, "book_slot:"))
    return find_cb(session, "paid:")


@pytest.mark.asyncio
async def test_paid_creates_event_and_notifies_admin(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "pay_claimed"
    assert b.google_event_id in gcal.events
    # админу ушло уведомление с кнопками подтвердить/отклонить
    admin_kb = last_kb(session, chat_id=ADMIN_ID)
    flat = [x.get("callback_data", "") for row in admin_kb for x in row]
    assert any(c.startswith("confirm_pay:") for c in flat)
    assert any(c.startswith("reject_pay:") for c in flat)


@pytest.mark.asyncio
async def test_double_paid_creates_single_event(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    await press(dp, bot, paid)  # второй клик
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_reject_pay_deletes_event_and_frees_slot(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    reject = find_cb(session, "reject_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, reject, user=admin, chat_id=ADMIN_ID)
    assert len(gcal.deleted) == 1
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "cancelled"


@pytest.mark.asyncio
async def test_confirm_pay_notifies_client(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "confirmed"


@pytest.mark.asyncio
async def test_calendar_sync_failure_still_records_payment(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    async def boom(*a, **k):
        raise RuntimeError("insert failed")
    gcal.create_event = boom
    await press(dp, bot, paid)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "pay_claimed"
    assert b.calendar_sync_failed is True
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k "paid or reject or confirm or sync"`
Expected: FAIL (нет `cb_paid`/`reject_pay`).

- [ ] **Step 3: Обновить admin_confirm_pay_kb (две кнопки)**

В `keyboards/inline.py` заменить `admin_confirm_pay_kb`:
```python
def admin_confirm_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить оплату", callback_data=f"confirm_pay:{booking_id}")
    builder.button(text="❌ Оплата не найдена", callback_data=f"reject_pay:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Добавить cb_paid и хелперы в handlers/booking.py**

Дописать в конец `handlers/booking.py`:
```python
def _client_line(callback: CallbackQuery) -> str:
    user = callback.from_user
    username = f"@{user.username}" if user.username else "нет username"
    return (
        f"<b>Клиент:</b> {html.quote(user.full_name)} — {username} "
        f'(<a href="tg://user?id={user.id}">открыть</a>, id {user.id})'
    )


def _event_description(callback: CallbackQuery) -> str:
    user = callback.from_user
    username = f"@{user.username}" if user.username else f"id {user.id}"
    return f"Клиент: {user.full_name} ({username})"


async def _notify_admins(bot: Bot, admin_ids, text: str, reply_markup=None) -> None:
    delivered = False
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
            delivered = True
        except TelegramAPIError:
            logger.warning("Не доставлено админу %s", admin_id)
    if not delivered:
        logger.error("Уведомление не доставлено НИ ОДНОМУ админу: %s", text[:80])


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(
    callback: CallbackQuery, bot: Bot, admin_ids: list[int], gcal: GoogleCalendar
) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял запись", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status != "held":
            await callback.answer("Уже принято 🤍 Ждём подтверждения Ланы", show_alert=True)
            return
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)

    # создаём событие в календаре
    event_id = None
    sync_failed = False
    try:
        event_id = await gcal.create_event(
            slot, callback.from_user.full_name, _event_description(callback)
        )
    except Exception:
        logger.exception("Не удалось создать событие в календаре для booking %s", booking_id)
        sync_failed = True

    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if booking.status != "held":  # гонка двойного клика
            if event_id:
                try:
                    await gcal.delete_event(event_id)
                except Exception:
                    logger.exception("Откат дубля события не удался")
            await callback.answer("Уже принято 🤍", show_alert=True)
            return
        booking.status = "pay_claimed"
        booking.google_event_id = event_id
        booking.calendar_sync_failed = sync_failed
        await session.commit()

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "🤍 Принято! Проверяем оплату.\n\n"
        f"Как только Лана подтвердит, придёт сообщение о записи на "
        f"<b>{format_slot_human(slot)}</b>."
    )
    warn = "\n\n⚠️ Событие в календаре не создалось — оформи вручную." if sync_failed else ""
    await _notify_admins(
        bot, admin_ids,
        "💳 <b>Клиент сообщил об оплате слота</b>\n\n"
        f"<b>Слот:</b> {format_slot_human(slot)}\n"
        f"{_client_line(callback)}\n\n"
        f"Проверь оплату в Tribute и подтверди ⇩{warn}",
        reply_markup=admin_confirm_pay_kb(booking_id),
    )
```
Добавить в импорты booking.py: `from keyboards.inline import admin_confirm_pay_kb` уже есть; убедиться, что `booking_pay_kb` импортирован.

- [ ] **Step 5: Перенести confirm_pay и добавить reject_pay + /bookings в handlers/admin.py**

В `handlers/admin.py` заменить `cb_confirm_pay` (строки 76–113) на версию с `format_slot_human` и добавить `reject_pay` и `/bookings`:
```python
from datetime import datetime, timezone
from formatting import format_slot_human
from google_calendar import GoogleCalendar


@router.callback_query(F.data.startswith("confirm_pay:"))
async def cb_confirm_pay(callback: CallbackQuery, bot: Bot) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status == "confirmed":
            await callback.answer("Уже подтверждено")
            return
        booking.status = "confirmed"
        await session.commit()
        user_id, slot = booking.telegram_id, booking.slot_start
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)
    try:
        await bot.send_message(
            user_id,
            "○─── ☾ ───○\n\n"
            "<b>✦ Вы оплатили, спасибо!</b> 🤍\n\n"
            f"Запись подтверждена: <b>{format_slot_human(slot)}</b>.\n\n"
            "Лана свяжется с тобой перед сессией и пришлёт ссылку на видеозвонок. "
            "До встречи ✦",
            reply_markup=lead_done_kb(),
        )
    except TelegramAPIError:
        await callback.message.answer(
            "⚠️ Оплата подтверждена, но сообщение клиенту не доставлено."
        )
    await callback.message.edit_text(
        callback.message.html_text + "\n\n✅ <b>Оплата подтверждена</b>"
    )


@router.callback_query(F.data.startswith("reject_pay:"))
async def cb_reject_pay(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status == "cancelled":
            await callback.answer("Уже отменено")
            return
        event_id = booking.google_event_id
        booking.status = "cancelled"
        await session.commit()
        user_id, slot = booking.telegram_id, booking.slot_start
    if event_id:
        try:
            await gcal.delete_event(event_id)
        except Exception:
            logger.exception("Не удалось удалить событие %s", event_id)
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)
    try:
        await bot.send_message(
            user_id,
            "○─── ☾ ───○\n\n"
            "К сожалению, оплату по этой записи мы не нашли, и слот освобождён.\n"
            "Если ты оплачивал(а) — напиши Лане в ЛС, разберёмся 🤍",
            reply_markup=lead_done_kb(),
        )
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        callback.message.html_text + "\n\n❌ <b>Оплата отклонена, слот освобождён</b>"
    )


@router.message(Command("bookings"))
async def cmd_bookings(message: Message) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Booking).where(
                Booking.status.in_(["pay_claimed", "confirmed"]),
                Booking.slot_start >= now,
            ).order_by(Booking.slot_start)
        )).scalars().all()
    if not rows:
        await message.answer("Ближайших оплаченных записей нет.")
        return
    lines = ["<b>Ближайшие записи:</b>\n"]
    for b in rows:
        slot = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
        mark = "✅" if b.status == "confirmed" else "💳"
        warn = " ⚠️календарь" if b.calendar_sync_failed else ""
        lines.append(f"{mark} {format_slot_human(slot)} — id {b.telegram_id}{warn}")
    await message.answer("\n".join(lines))
```
Добавить в импорты admin.py: `Booking` уже импортирован; добавить `from google_calendar import GoogleCalendar`, `from formatting import format_slot_human`, `from datetime import datetime, timezone`. Убедиться, что `select`, `Command`, `lead_done_kb` импортированы (они есть).
Добавить `/bookings` в текст `/admin` (cmd_admin).

- [ ] **Step 6: Прогнать все booking-тесты**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v`
Expected: PASS (все).

- [ ] **Step 7: Commit**

```bash
git add handlers/booking.py handlers/admin.py keyboards/inline.py tests/test_booking_flow.py
git commit -m "booking: оплата→событие, подтверждение/отклонение, /bookings (блокер 5)"
```

---

## Task 8: Цена в consultation.py + кнопка «Записаться» в результате теста (блокеры 1-остаток, 9)

**Files:**
- Modify: `handlers/consultation.py:31` (цена через PRICE_TEXT)
- Modify: `keyboards/inline.py:211-217` (`quiz_result_kb`)
- Create: `tests/test_texts.py`

**Interfaces:**
- Consumes: `PRICE_TEXT`.

- [ ] **Step 1: Тест на цену и кнопку**

`tests/test_texts.py`:
```python
from handlers.consultation import CONSULTATION_TEXT
from formatting import PRICE_TEXT
from keyboards.inline import quiz_result_kb


def test_consultation_price_is_canonical():
    assert PRICE_TEXT in CONSULTATION_TEXT
    assert "111" not in CONSULTATION_TEXT and "11111" not in CONSULTATION_TEXT


def test_quiz_result_has_booking_button():
    kb = quiz_result_kb().inline_keyboard
    cbs = [b.callback_data for row in kb for b in row if b.callback_data]
    assert "booking_start" in cbs
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_texts.py -v`
Expected: FAIL.

- [ ] **Step 3: Правки**

В `handlers/consultation.py`: добавить `from formatting import PRICE_TEXT`, в `CONSULTATION_TEXT` заменить строку `"● Стоимость: 100 € / 10000 ₽\n\n"` на `f"● Стоимость: {PRICE_TEXT}\n\n"` (и сделать строку f-строкой). Убедиться, что нигде в файле не осталось «111».

В `keyboards/inline.py` `quiz_result_kb` добавить кнопку записи первой:
```python
def quiz_result_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✦ Записаться на консультацию", callback_data="booking_start")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="Пройти заново", callback_data="quiz_begin")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_texts.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add handlers/consultation.py keyboards/inline.py tests/test_texts.py
git commit -m "Цена через единую константу + «Записаться» в результате теста (блокеры 1,9)"
```

---

## Task 9: Catch-all для потерянного FSM (блокер 4)

**Files:**
- Create: `handlers/fallback.py`
- Modify: `handlers/__init__.py`
- Modify: `tests/test_booking_flow.py` (добавить тест рестарта)

**Interfaces:**
- Produces: `fallback_router` — ловит `quiz_ans:`, `quiz_back`, а также любые сообщения в утерянном lead-FSM. Регистрируется **последним**, чтобы не перехватывать живые состояния.

- [ ] **Step 1: Тест — после сброса состояния кнопка теста отвечает**

Добавить в `tests/test_booking_flow.py`:
```python
@pytest.mark.asyncio
async def test_quiz_answer_without_state_gives_hint(env):
    dp, bot, gcal, session = env
    # без quiz_begin — состояния Quiz.in_progress нет
    await press(dp, bot, "quiz_ans:3")
    texts = [d.get("text", "") for n, d in session.log if d.get("chat_id") == CLIENT_ID]
    assert any("заново" in t.lower() or "сброш" in t.lower() for t in texts)
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k quiz_answer_without_state`
Expected: FAIL (нет ответа — мёртвая кнопка).

- [ ] **Step 3: Создать handlers/fallback.py**

```python
from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import lead_done_kb

router = Router()

_LOST_TEXT = (
    "○─── ☾ ───○\n\n"
    "Похоже, сессия сбросилась (бот перезапускался) 🤍\n"
    "Начни заново из меню — всё быстро восстановится."
)


@router.callback_query(F.data.startswith("quiz_ans:"))
@router.callback_query(F.data == "quiz_back")
async def cb_lost_quiz(callback: CallbackQuery) -> None:
    await callback.message.edit_text(_LOST_TEXT, reply_markup=lead_done_kb())
```

> Почему это работает: роутеры проверяются по порядку. `quiz_router` ловит `quiz_ans:`/`quiz_back` **только** в состоянии `Quiz.in_progress`. Если состояния нет, ни один живой хендлер не сматчится, и управление доходит до `fallback_router`.

- [ ] **Step 4: Подключить fallback последним**

В `handlers/__init__.py` добавить импорт `from .fallback import router as fallback_router` и в `setup_routers()` **последней** строкой перед `return`:
```python
    router.include_router(fallback_router)
```

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k quiz_answer_without_state`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add handlers/fallback.py handlers/__init__.py tests/test_booking_flow.py
git commit -m "Catch-all для потерянного FSM после редеплоя (блокер 4)"
```

---

## Task 10: Напоминание за сутки до сессии (блокер 12)

**Files:**
- Modify: `followup.py`
- Create: `tests/test_reminders.py`

**Interfaces:**
- Consumes: `Booking`, `format_slot_human`.
- Produces: `reminder_pass(bot, now=None) -> int` — шлёт напоминание клиентам, у кого `status=confirmed` и `slot_start` в окне (24±..) часов, один раз (маркер — `Event(action="reminder_sent")` с привязкой к booking). Вызывается из `followup_loop`.

- [ ] **Step 1: Тест напоминания**

`tests/test_reminders.py`:
```python
import pytest
from datetime import datetime, timedelta, timezone
from database import init_db, close_db, get_session, Booking, Event
import database
from followup import reminder_pass


class FakeBot:
    def __init__(self): self.sent = []
    async def send_message(self, uid, text, reply_markup=None):
        self.sent.append((uid, text))


@pytest.mark.asyncio
async def test_reminder_sent_once_for_tomorrow_session():
    await init_db("sqlite+aiosqlite:///:memory:")
    now = datetime(2026, 7, 27, 12, tzinfo=timezone.utc)
    async with get_session() as s:
        s.add(Booking(telegram_id=1, slot_start=now + timedelta(hours=23),
                      status="confirmed"))  # завтра
        s.add(Booking(telegram_id=2, slot_start=now + timedelta(days=5),
                      status="confirmed"))  # далеко
        await s.commit()
    bot = FakeBot()
    n1 = await reminder_pass(bot, now)
    n2 = await reminder_pass(bot, now)  # повторно не шлём
    assert n1 == 1 and n2 == 0
    assert bot.sent[0][0] == 1
    await close_db()
    database.engine = None
    database.async_session = None
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reminders.py -v`
Expected: FAIL (нет `reminder_pass`).

- [ ] **Step 3: Добавить reminder_pass в followup.py**

Дописать в `followup.py`:
```python
from database import Booking
from formatting import format_slot_human

REMINDER_WINDOW_START = timedelta(hours=0)
REMINDER_LEAD = timedelta(hours=24)


async def reminder_pass(bot: Bot, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    horizon = now + REMINDER_LEAD
    async with get_session() as session:
        bookings = (await session.execute(
            select(Booking).where(Booking.status == "confirmed")
        )).scalars().all()
    sent = 0
    for b in bookings:
        slot = _as_utc(b.slot_start)
        if not (now < slot <= horizon):
            continue
        # не слать повторно: уже есть отметка reminder_sent по этому пользователю
        async with get_session() as session:
            already = (await session.execute(
                select(Event).where(
                    Event.telegram_id == b.telegram_id,
                    Event.action == "reminder_sent",
                    Event.created_at >= now - timedelta(days=2),
                )
            )).first()
        if already:
            continue
        try:
            await bot.send_message(
                b.telegram_id,
                "○─── ☾ ───○\n\n"
                "Напоминаю: завтра у тебя консультация 🤍\n"
                f"<b>{format_slot_human(slot)}</b>\n\n"
                "Лана пришлёт ссылку на видеозвонок перед началом. До встречи ✦",
            )
            sent += 1
        except TelegramAPIError:
            logger.info("Напоминание %s не доставлено", b.telegram_id)
        async with get_session() as session:
            session.add(Event(telegram_id=b.telegram_id, action="reminder_sent"))
            await session.commit()
    return sent
```
В `followup_loop` добавить вызов `reminder_pass` рядом с `followup_pass`:
```python
async def followup_loop(bot: Bot) -> None:
    while True:
        try:
            await followup_pass(bot)
            await reminder_pass(bot)
        except Exception:
            logger.exception("Followup/reminder pass failed")
        await asyncio.sleep(CHECK_INTERVAL)
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reminders.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add followup.py tests/test_reminders.py
git commit -m "Напоминание клиенту за сутки до сессии (блокер 12)"
```

---

## Task 11: README, deploy-инструкция, финальная проверка

**Files:**
- Modify: `README.md`
- Modify: `CLAUDE.md` (раздел про booking — освежить под Google)
- Create: `docs/google-calendar-setup.md`

**Interfaces:** нет кода.

- [ ] **Step 1: Инструкция для Ланы по Google**

Создать `docs/google-calendar-setup.md` с пошаговым:
1. Google Cloud Console → новый проект → включить Google Calendar API.
2. Создать Service Account → сгенерировать JSON-ключ.
3. В Google Calendar создать календарь «Консультации».
4. Расшарить «Консультации» сервис-аккаунту (его email из JSON) с правом «Вносить изменения в мероприятия».
5. Расшарить личный календарь сервис-аккаунту с правом «Просматривать все данные о мероприятиях».
6. Скопировать Calendar ID обоих (Настройки календаря → «Идентификатор календаря»).
7. Заполнить env: `GOOGLE_SA_CREDENTIALS` (содержимое JSON или путь), `CALENDAR_ID_BOOKINGS`, `CALENDAR_ID_PERSONAL`.

- [ ] **Step 2: Обновить README и CLAUDE.md**

В README раздел про запись: описать новый флоу (выбор слота из календаря → холд 30 мин → оплата → событие в календаре → подтверждение), новые env-переменные, ссылку на `docs/google-calendar-setup.md`, команду `/bookings`. В CLAUDE.md обновить раздел «Флоу записи на слот» под Google Calendar.

- [ ] **Step 3: Полная проверка компиляции**

Run: `python -m py_compile main.py database.py middlewares.py filters.py followup.py slots.py google_calendar.py booking_config.py formatting.py handlers/*.py keyboards/inline.py`
Expected: без ошибок.

- [ ] **Step 4: Полный прогон тестов**

Run: `PYTHONIOENCODING=utf-8 pytest -v`
Expected: все PASS.

- [ ] **Step 5: Commit**

```bash
git add README.md CLAUDE.md docs/google-calendar-setup.md
git commit -m "Доки: настройка Google Calendar, обновлённый флоу записи, /bookings"
```

---

## Self-Review (выполнено при написании плана)

**Spec coverage:**
- Цель 1 (Лана ведёт расписание) → Task 4 (freebusy) + Task 6 (слоты из календаря). ✓
- Цель 2 (занимают только оплатившие) → Task 6 (холд) + Task 7 (событие после оплаты). ✓
- Цель 3 (синк с календарём) → Task 4/7 (create_event). ✓
- Блокер 1 (цена) → Task 2 + Task 8. ✓
- Блокеры 2,3 (мусор/захват) → Task 6 (холд TTL + лимит). ✓
- Блокер 4 (мёртвые кнопки) → Task 9. ✓
- Блокер 5 (обзор/потеря уведомлений) → Task 7 (`/bookings` + `_notify_admins` с логом «ни одному»). ✓
- Блокер 7 (буфер) → Task 3 (lead). ✓
- Блокер 8 (пояса) → Task 2. ✓
- Блокер 9 (кнопка в тесте) → Task 8. ✓
- Блокер 12 (напоминание) → Task 10. ✓
- Три случая ошибок Google → Task 6 (down на выборе) + Task 7 (sync fail при оплате, гонка двойного клика). ✓
- Миграция не нужна → Task 1 (пересоздание схемы). ✓

**Placeholder scan:** в тесте Task 6 есть намеренная строка-заглушка `@pytest_asyncio_fixture := None` с явной инструкцией её удалить — это указание, не placeholder-код. Остальное — конкретный код. ✓

**Type consistency:** `free_slots(...)` сигнатура одинакова в Task 3 и вызовах Task 6. `GoogleCalendar.busy/create_event/delete_event` — совпадают в Task 4, 6, 7. `format_slot_human` — Task 2, 6, 7, 10. `BookingConfig` поля — Task 5 и потребители. Статусы `held/pay_claimed/confirmed/cancelled` — единообразны. ✓
