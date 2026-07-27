# Перенос записи, лимит 5, событие после подтверждения — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Клиент может переносить записи (≥24ч сам, <24ч с согласия Ланы и причиной; отказ → отмена без возврата); лимит активных записей 5; событие в Google создаётся только после подтверждения оплаты Ланой; новые поля доезжают в боевую БД авто-миграцией.

**Architecture:** Событие в календаре создаётся на `confirm`, а слот между `paid` и `confirm` держится записью `pay_claimed` в расчёте занятости. Перенос переиспользует существующий календарь (клавиатуры параметризуются префиксом callback). Новые поля переноса добавляются в `Booking` + идемпотентный `ALTER … ADD COLUMN IF NOT EXISTS` в `init_db` для Postgres.

**Tech Stack:** Python 3.12, aiogram 3.x (FSM), SQLAlchemy 2.0 async + asyncpg/aiosqlite, pytest + pytest-asyncio.

## Global Constraints

- Python 3.12, aiogram 3.x, HTML parse mode. Колбэки — `F.data ==` / `.startswith`.
- Хендлеры колбэков не зовут пустой `callback.answer()` (это middleware); алерт `callback.answer("...", show_alert=True)` — можно.
- Все `datetime` внутри и в БД — aware; из sqlite приходят наивные → нормализуй `.replace(tzinfo=timezone.utc)` при чтении, как в существующем коде.
- Booking-статусы: `held → pay_claimed → confirmed / cancelled`. Поля переноса (`reschedule_to`, `reschedule_reason`, `reschedule_status`) — поверх, очищаются после применения/отклонения; `reschedule_status='pending'` пока ждём Лану.
- Лимит активных записей: `MAX_ACTIVE_BOOKINGS = 5`.
- Порог самостоятельного переноса: `RESCHEDULE_THRESHOLD = timedelta(hours=24)` до `slot_start` исходной брони.
- Занятость слота: Google busy (confirmed) + `held`(held_until>now) + `pay_claimed`.
- Событие в календаре создаётся ТОЛЬКО в `cb_confirm_pay`; при ошибке Google — `calendar_sync_failed=True`, подтверждение всё равно проходит.
- Отклонение переноса Ланой → запись `cancelled`, слот освобождается, клиенту «оплата не возвращается».
- Escape пользовательского текста в HTML-уведомлениях админам через `aiogram.html.quote(...)`.
- Экранирование тестов на Windows: `PYTHONIOENCODING=utf-8 python -m pytest -q`.
- Проверка компиляции: `python -m py_compile main.py database.py followup.py slots.py google_calendar.py booking_config.py formatting.py handlers/*.py keyboards/inline.py`.

---

## File Structure

- **Modify** `database.py` — 3 новых поля в `Booking`; авто-миграция в `init_db`.
- **Modify** `handlers/booking.py` — `_occupied_slots` (вкл. pay_claimed), `_active_booking_count` (лимит 5), `cb_paid` без создания события, `build_event_fields`, `apply_reschedule`, «Мои записи» + перенос (calendar с префиксом `resched`, FSM причины).
- **Modify** `handlers/admin.py` — `cb_confirm_pay` создаёт событие; `cb_reject_pay` без события; approve/reject переноса.
- **Modify** `keyboards/inline.py` — «Мои записи» в меню; `booking_calendar_kb`/`booking_times_kb` с префиксом и back-target; `my_bookings_kb`; `admin_resched_kb`.
- **Test** `tests/test_reschedule.py` (новый) + дополнения к `tests/test_booking_flow.py`, `tests/test_schema.py`.

---

## Task 1: Поля переноса в Booking + авто-миграция

**Files:**
- Modify: `database.py` (класс `Booking`, функция `init_db`)
- Create: `tests/test_migration.py`

**Interfaces:**
- Produces: `Booking.reschedule_to: datetime|None`, `Booking.reschedule_reason: str|None`, `Booking.reschedule_status: str|None`.
- Produces: `init_db` идемпотентно добавляет эти колонки в Postgres.

- [ ] **Step 1: Тест — новые поля есть на свежей схеме**

`tests/test_migration.py`:
```python
import pytest
from datetime import datetime, timezone
from sqlalchemy import select
from database import Booking, get_session, init_db, close_db
import database


@pytest.mark.asyncio
async def test_reschedule_columns_exist():
    await init_db("sqlite+aiosqlite:///:memory:")
    async with get_session() as s:
        s.add(Booking(
            telegram_id=1,
            slot_start=datetime(2026, 7, 28, 10, tzinfo=timezone.utc),
            reschedule_to=datetime(2026, 7, 29, 10, tzinfo=timezone.utc),
            reschedule_reason="заболела",
            reschedule_status="pending",
        ))
        await s.commit()
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.reschedule_status == "pending"
    assert b.reschedule_reason == "заболела"
    await close_db()
    database.engine = None
    database.async_session = None
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_migration.py -v`
Expected: FAIL (нет атрибутов reschedule_*).

- [ ] **Step 3: Добавить поля в модель**

В `database.py`, в класс `Booking`, после `calendar_sync_failed`:
```python
    reschedule_to: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reschedule_reason: Mapped[str | None] = mapped_column(String(500))
    reschedule_status: Mapped[str | None] = mapped_column(String(20))
```

- [ ] **Step 4: Авто-миграция в init_db**

В `database.py` добавить импорт `from sqlalchemy import text` (к существующим импортам sqlalchemy). Заменить тело `init_db` (блок `async with engine.begin()`):
```python
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        if engine.dialect.name == "postgresql":
            for ddl in _MIGRATIONS:
                await conn.execute(text(ddl))
```
И добавить рядом (модульный уровень `database.py`, перед `init_db`):
```python
# Идемпотентные ALTER для полей, добавленных после первого create_all.
# create_all создаёт только отсутствующие таблицы, но не добавляет колонки в
# существующие — на Postgres их доводим здесь. sqlite (тесты) получает полную
# схему сразу через create_all, поэтому миграции для него не нужны.
_MIGRATIONS = [
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_to TIMESTAMP WITH TIME ZONE",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_reason VARCHAR(500)",
    "ALTER TABLE bookings ADD COLUMN IF NOT EXISTS reschedule_status VARCHAR(20)",
]
```

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_migration.py -v`
Expected: PASS (sqlite-ветка миграцию не трогает, поля из create_all).

- [ ] **Step 6: Полный прогон + компиляция**

Run: `python -m py_compile database.py && PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 7: Commit**

```bash
git add database.py tests/test_migration.py
git commit -m "Поля переноса в Booking + идемпотентная авто-миграция (Postgres)"
```

---

## Task 2: Занятость с pay_claimed + лимит 5

**Files:**
- Modify: `handlers/booking.py` (`_active_holds`→`_occupied_slots`, `_user_has_active`→`_active_booking_count`, `_load_free`, `cb_book_slot`)
- Modify: `tests/test_booking_flow.py` (правки/добавления)

**Interfaces:**
- Consumes: `Booking`, `free_slots`.
- Produces: `_occupied_slots(session, now) -> list[datetime]` (held-не-истёкшие + pay_claimed); `_active_booking_count(session, tg_id, now) -> int`; константа `MAX_ACTIVE_BOOKINGS = 5`.

- [ ] **Step 1: Тесты — pay_claimed держит слот; 6-я бронь отклоняется**

Добавить в `tests/test_booking_flow.py`:
```python
@pytest.mark.asyncio
async def test_pay_claimed_slot_stays_occupied(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)  # создаёт held → мы жмём paid
    await press(dp, bot, paid)                 # теперь pay_claimed, события нет
    # тот же слот больше не предлагается другим
    from datetime import datetime, timezone
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    slot_iso = b.slot_start.replace(tzinfo=timezone.utc).isoformat() if b.slot_start.tzinfo is None else b.slot_start.isoformat()
    # заходим на запись заново — этого слота в клавиатуре времени быть не должно
    await press(dp, bot, "booking_start")
    # находим день брони и открываем его
    day = b.slot_start.date().isoformat()
    await press(dp, bot, f"book_day:{day}")
    cbs = [x.get("callback_data", "") for row in last_kb(session) for x in row]
    assert f"book_slot:{slot_iso}" not in cbs


@pytest.mark.asyncio
async def test_sixth_active_booking_blocked(env):
    dp, bot, gcal, session = env
    from datetime import datetime, timedelta, timezone
    # 5 активных confirmed в будущем
    async with get_session() as s:
        for i in range(5):
            s.add(Booking(
                telegram_id=CLIENT_ID,
                slot_start=datetime.now(timezone.utc) + timedelta(days=2 + i),
                status="confirmed",
            ))
        await s.commit()
    await press(dp, bot, "booking_start")
    day = find_cb(session, "book_day:")
    await press(dp, bot, day)
    slot = find_cb(session, "book_slot:")
    await press(dp, bot, slot)
    # 6-я — отказ, held не создан
    from sqlalchemy import select, func
    async with get_session() as s:
        held = (await s.execute(select(func.count()).select_from(Booking).where(Booking.status == "held"))).scalar()
    assert held == 0
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k "pay_claimed_slot or sixth_active"`
Expected: FAIL (pay_claimed не держит слот; лимит=1 не 5).

- [ ] **Step 3: Переписать occupancy и лимит в booking.py**

В `handlers/booking.py` заменить `_active_holds` и `_user_has_active`:
```python
MAX_ACTIVE_BOOKINGS = 5


async def _occupied_slots(session, now: datetime) -> list[datetime]:
    """Слоты, занятые до появления события в календаре: held (не истёкшие) и
    pay_claimed (оплачено, ждёт подтверждения)."""
    rows = (await session.execute(
        select(Booking.slot_start).where(
            ((Booking.status == "held") & (Booking.held_until > now))
            | (Booking.status == "pay_claimed")
        )
    )).scalars()
    return [r if r.tzinfo else r.replace(tzinfo=timezone.utc) for r in rows]


async def _active_booking_count(session, tg_id: int, now: datetime) -> int:
    rows = (await session.execute(
        select(Booking.id).where(
            Booking.telegram_id == tg_id,
            (Booking.status.in_(["confirmed", "pay_claimed"]) & (Booking.slot_start > now))
            | ((Booking.status == "held") & (Booking.held_until > now)),
        )
    )).all()
    return len(rows)
```
В `_load_free` заменить вызов `holds = await _active_holds(session, now)` на `holds = await _occupied_slots(session, now)`.
В `cb_book_slot` заменить блок лимита:
```python
        if await _active_booking_count(session, callback.from_user.id, now) >= MAX_ACTIVE_BOOKINGS:
            await callback.answer(
                "У тебя уже 5 активных записей 🤍 Заверши или перенеси одну, "
                "прежде чем брать новую.",
                show_alert=True,
            )
            return
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k "pay_claimed_slot or sixth_active"`
Expected: PASS.

- [ ] **Step 5: Полный прогон**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное (существующий `test_pick_time_creates_hold` и лимит-тест на 1 запись — проверь, что старый тест лимита не завязан на «1»; если был `test`, ожидавший блок при 1 активной — обнови его под 5).

- [ ] **Step 6: Commit**

```bash
git add handlers/booking.py tests/test_booking_flow.py
git commit -m "Занятость держит pay_claimed-слот + лимит активных записей 5"
```

---

## Task 3: Событие в календаре — на подтверждении, а не на оплате

**Files:**
- Modify: `handlers/booking.py` (`cb_paid` без create_event; `build_event_fields`)
- Modify: `handlers/admin.py` (`cb_confirm_pay` создаёт событие; `cb_reject_pay` без события)
- Modify: `tests/test_booking_flow.py`

**Interfaces:**
- Consumes: `GoogleCalendar`, `Booking`, `User`.
- Produces: `build_event_fields(session, tg_id) -> tuple[str, str]` (заголовок, описание события из `User`).

- [ ] **Step 1: Тесты — событие после confirm, не после paid**

Добавить в `tests/test_booking_flow.py`:
```python
@pytest.mark.asyncio
async def test_event_created_on_confirm_not_on_paid(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    assert gcal.events == {}          # после «оплатил» события ещё нет
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    assert len(gcal.events) == 1      # событие появилось на подтверждении
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "confirmed" and b.google_event_id in gcal.events


@pytest.mark.asyncio
async def test_reject_from_pay_claimed_touches_no_calendar(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    reject = find_cb(session, "reject_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, reject, user=admin, chat_id=ADMIN_ID)
    assert gcal.events == {} and gcal.deleted == []
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "cancelled"
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k "event_created_on_confirm or reject_from_pay_claimed"`
Expected: FAIL (сейчас событие создаётся на paid).

- [ ] **Step 3: Убрать создание события из cb_paid**

В `handlers/booking.py` заменить тело `cb_paid` (после разбора booking_id) на версию без gcal:
```python
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status != "held":
            await callback.answer("Уже принято 🤍 Ждём подтверждения Ланы", show_alert=True)
            return
        booking.status = "pay_claimed"
        await session.commit()
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "🤍 Принято! Проверяем оплату.\n\n"
        f"Как только Лана подтвердит, придёт сообщение о записи на "
        f"<b>{format_slot_human(slot)}</b>."
    )
    await _notify_admins(
        bot, admin_ids,
        "💳 <b>Клиент сообщил об оплате слота</b>\n\n"
        f"<b>Слот:</b> {format_slot_human(slot)}\n"
        f"{_client_line(callback)}\n\n"
        "Проверь оплату в Tribute и подтверди ⇩",
        reply_markup=admin_confirm_pay_kb(booking_id),
    )
```
Изменить сигнатуру `cb_paid` — убрать `gcal`: `async def cb_paid(callback: CallbackQuery, bot: Bot, admin_ids: list[int]) -> None:`. Удалить теперь неиспользуемый `_event_description` (его заменит `build_event_fields`).

- [ ] **Step 4: Добавить build_event_fields в booking.py**

```python
async def build_event_fields(session, tg_id: int) -> tuple[str, str]:
    """Заголовок и описание события в календаре по данным клиента из User."""
    from database import User
    user = await session.get(User, tg_id)
    name = (user.full_name if user and user.full_name else f"id {tg_id}")
    handle = f"@{user.username}" if user and user.username else f"id {tg_id}"
    return f"Консультация — {name}", f"Клиент: {name} ({handle})"
```

- [ ] **Step 5: cb_confirm_pay создаёт событие**

В `handlers/admin.py` заменить `cb_confirm_pay` на версию с `gcal` и созданием события:
```python
from google_calendar import GoogleCalendar
from handlers.booking import build_event_fields


@router.callback_query(F.data.startswith("confirm_pay:"))
async def cb_confirm_pay(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
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
        if booking.status != "pay_claimed":
            await callback.answer(
                f"Эта запись уже обработана ({booking.status})", show_alert=True
            )
            return
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)
        title, desc = await build_event_fields(session, booking.telegram_id)

    event_id = None
    sync_failed = False
    try:
        event_id = await gcal.create_event(slot, title, desc)
    except Exception:
        logger.exception("Не удалось создать событие для booking %s", booking_id)
        sync_failed = True

    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        booking.status = "confirmed"
        booking.google_event_id = event_id
        booking.calendar_sync_failed = sync_failed
        await session.commit()
        user_id = booking.telegram_id

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
    warn = "\n⚠️ Событие не создалось — оформи вручную." if sync_failed else ""
    await callback.message.edit_text(
        callback.message.html_text + f"\n\n✅ <b>Оплата подтверждена</b>{warn}"
    )
```
Добавить в импорты admin.py `from datetime import timezone` (если ещё нет — есть `datetime, timezone` из Task-7 предыдущего плана; проверь).

- [ ] **Step 6: cb_reject_pay из pay_claimed/held без события (уже так, проверить)**

`cb_reject_pay` уже удаляет событие только `if event_id:`. При новой схеме у `pay_claimed` `google_event_id is None` → `delete_event` не зовётся. Убедиться, что гейт статусов допускает `pay_claimed`/`held` (из прошлого плана уже так). Изменений кода может не потребоваться — подтвердить чтением.

- [ ] **Step 7: Прогон таргетных + полный**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -q` затем `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное. Существующие тесты `test_paid_creates_event_and_notifies_admin` и `test_confirm_pay_notifies_client` изменят смысл — обнови их: событие теперь ожидается после confirm, а не после paid (переименуй/поправь ассерты, не ослабляя их).

- [ ] **Step 8: Commit**

```bash
git add handlers/booking.py handlers/admin.py tests/test_booking_flow.py
git commit -m "Событие в календаре создаётся на подтверждении оплаты, не на «Я оплатил»"
```

---

## Task 4: Параметризация календаря/времени префиксом callback

**Files:**
- Modify: `keyboards/inline.py` (`booking_calendar_kb`, `booking_times_kb`)
- Modify: `handlers/booking.py` (вызовы `_render_calendar`, `cb_book_day`)
- Modify: `tests/test_calendar_kb.py`

**Interfaces:**
- Produces: `booking_calendar_kb(year, month, free_dates, has_prev, has_next, *, prefix="book", back_cb="consultation")` — дни `{prefix}_day:<iso>`, месяцы `{prefix}_month:<ym>`.
- Produces: `booking_times_kb(day_iso, times, *, prefix="book", back_cb="booking_start")` — слоты `{prefix}_slot:<iso>`.

- [ ] **Step 1: Тест — префикс resched даёт resched_day/resched_slot**

Добавить в `tests/test_calendar_kb.py`:
```python
def test_calendar_prefix_resched():
    from datetime import date
    kb = booking_calendar_kb(
        2026, 8, {date(2026, 8, 11)}, has_prev=True, has_next=False,
        prefix="resched", back_cb="my_bookings",
    )
    cbs = [b.callback_data for b in _flat(kb)]
    assert "resched_day:2026-08-11" in cbs
    assert "resched_month:2026-07" in cbs
    assert any(c == "my_bookings" for c in cbs)


def test_times_prefix_resched():
    from keyboards.inline import booking_times_kb
    kb = booking_times_kb(
        "2026-08-11", [("12:00", "2026-08-11T10:00:00+00:00")],
        prefix="resched", back_cb="resched_month:2026-08",
    )
    cbs = [b.callback_data for row in kb.inline_keyboard for b in row]
    assert "resched_slot:2026-08-11T10:00:00+00:00" in cbs
    assert "resched_month:2026-08" in cbs
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_calendar_kb.py -v -k "prefix"`
Expected: FAIL (нет параметра prefix).

- [ ] **Step 3: Параметризовать клавиатуры**

В `keyboards/inline.py` заменить сигнатуры и тела:
```python
def booking_calendar_kb(
    year, month, free_dates, has_prev, has_next, *, prefix="book", back_cb="consultation"
):
    builder = InlineKeyboardBuilder()
    builder.button(
        text="‹" if has_prev else " ",
        callback_data=f"{prefix}_month:{_prev_ym(year, month)}" if has_prev else "noop",
    )
    builder.button(text=f"{_MONTHS_RU[month]} {year}", callback_data="noop")
    builder.button(
        text="›" if has_next else " ",
        callback_data=f"{prefix}_month:{_next_ym(year, month)}" if has_next else "noop",
    )
    for wd in _WEEKDAY_HEADER:
        builder.button(text=wd, callback_data="noop")
    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    for week in weeks:
        for d in week:
            if d.month != month:
                builder.button(text="·", callback_data="noop")
            elif d in free_dates:
                builder.button(text=str(d.day), callback_data=f"{prefix}_day:{d.isoformat()}")
            else:
                builder.button(text="·", callback_data="noop")
    builder.button(text="⇦ Назад", callback_data=back_cb)
    builder.adjust(3, 7, *([7] * len(weeks)), 1)
    return builder.as_markup()


def booking_times_kb(day_iso, times, *, prefix="book", back_cb="booking_start"):
    builder = InlineKeyboardBuilder()
    for label, slot_iso in times:
        builder.button(text=label, callback_data=f"{prefix}_slot:{slot_iso}")
    builder.button(text="⇦ К выбору дня", callback_data=back_cb)
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: booking.py — вызовы по умолчанию не меняются**

`_render_calendar` и `cb_book_day` вызывают клавиатуры без `prefix` → работает как раньше (`book`). Явных правок не требуется, но убедись, что `booking_times_kb(d.isoformat(), time_buttons)` и `booking_calendar_kb(...)` в `_render_calendar` вызываются без позиционных лишних аргументов.

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_calendar_kb.py tests/test_booking_flow.py -q`
Expected: PASS (старые вызовы дефолтятся на book).

- [ ] **Step 6: Commit**

```bash
git add keyboards/inline.py tests/test_calendar_kb.py
git commit -m "Параметризация календаря/времени префиксом callback (для переноса)"
```

---

## Task 5: Экран «Мои записи»

**Files:**
- Modify: `keyboards/inline.py` (`main_menu_kb`, новый `my_bookings_kb`)
- Modify: `handlers/booking.py` (`cb_my_bookings`)
- Modify: `tests/test_booking_flow.py`

**Interfaces:**
- Produces: callback `my_bookings` (кнопка меню); `my_bookings_kb(items)` где `items: list[tuple[str, int]]` = (подпись, booking_id) → кнопки `resched:<id>`.

- [ ] **Step 1: Тест — «Мои записи» показывает будущие оплаченные с resched:<id>**

```python
@pytest.mark.asyncio
async def test_my_bookings_lists_future_paid(env):
    dp, bot, gcal, session = env
    from datetime import datetime, timedelta, timezone
    async with get_session() as s:
        s.add(Booking(telegram_id=CLIENT_ID,
                      slot_start=datetime.now(timezone.utc) + timedelta(days=3),
                      status="confirmed"))
        s.add(Booking(telegram_id=CLIENT_ID,
                      slot_start=datetime.now(timezone.utc) - timedelta(days=3),
                      status="confirmed"))  # прошлая — не показывать
        await s.commit()
    await press(dp, bot, "my_bookings")
    cbs = [b.get("callback_data", "") for row in last_kb(session) for b in row]
    assert sum(c.startswith("resched:") for c in cbs) == 1
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k my_bookings`
Expected: FAIL.

- [ ] **Step 3: Кнопка меню + клавиатура**

В `keyboards/inline.py` `main_menu_kb` добавить перед `builder.adjust(1)`:
```python
    builder.button(text="Мои записи", callback_data="my_bookings")
```
И новая клавиатура:
```python
def my_bookings_kb(items: "list[tuple[str, int]]"):
    """items — (подпись слота, booking_id)."""
    builder = InlineKeyboardBuilder()
    for label, bid in items:
        builder.button(text=f"Перенести · {label}", callback_data=f"resched:{bid}")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 4: Хендлер cb_my_bookings**

В `handlers/booking.py`:
```python
from keyboards.inline import my_bookings_kb  # добавить к импортам


@router.callback_query(F.data == "my_bookings")
async def cb_my_bookings(callback: CallbackQuery) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Booking).where(
                Booking.telegram_id == callback.from_user.id,
                Booking.status.in_(["pay_claimed", "confirmed"]),
                Booking.slot_start >= now,
            ).order_by(Booking.slot_start)
        )).scalars().all()
    if not rows:
        await callback.message.edit_text(
            "○─── ☾ ───○\n\n"
            "У тебя пока нет активных записей 🤍",
            reply_markup=my_bookings_kb([]),
        )
        return
    items = []
    for b in rows:
        slot = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
        items.append((format_slot_human(slot), b.id))
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n<b>✦ Твои записи</b>\n\nВыбери, что перенести ⇩",
        reply_markup=my_bookings_kb(items),
    )
```

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k my_bookings`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add keyboards/inline.py handlers/booking.py tests/test_booking_flow.py
git commit -m "Экран «Мои записи» с кнопкой переноса"
```

---

## Task 6: Перенос — выбор нового слота + развилка 24ч

**Files:**
- Modify: `handlers/booking.py` (FSM `RescheduleForm`, `cb_resched_start`, `cb_resched_month`, `cb_resched_day`, `cb_resched_slot`, `lead_reason`, `apply_reschedule`)
- Create: `tests/test_reschedule.py`

**Interfaces:**
- Consumes: `booking_calendar_kb`/`booking_times_kb` (prefix="resched"), `build_event_fields`, `free_slots`, `_occupied_slots`.
- Produces: `apply_reschedule(gcal, session, booking, new_slot) -> bool` — двигает событие (confirmed) или просто slot_start (pay_claimed); возвращает `sync_ok` (False если Google упал). Обновляет `booking.slot_start`, `booking.google_event_id`.
- Produces: FSM `RescheduleForm(picking, reason)`; callbacks `resched:<id>`, `resched_day:<iso>`, `resched_month:<ym>`, `resched_slot:<utc-iso>`; `RESCHEDULE_THRESHOLD = timedelta(hours=24)`.

- [ ] **Step 1: Тесты переноса (≥24ч и <24ч)**

`tests/test_reschedule.py` (переиспользует харнес из test_booking_flow — импортируй фикстуры/хелперы):
```python
import pytest
from datetime import datetime, timedelta, timezone
from sqlalchemy import select

from database import Booking, get_session
from tests.test_booking_flow import (  # переиспользуем харнес
    env, press, find_cb, last_kb, CLIENT_ID, ADMIN_ID,
)


async def _make_confirmed(days_ahead, gcal):
    """Создаёт confirmed-бронь с событием в FakeGCal, возвращает (id, slot)."""
    slot = datetime.now(timezone.utc) + timedelta(days=days_ahead)
    eid = await gcal.create_event(slot, "Клиент", "desc")
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot,
                    status="confirmed", google_event_id=eid)
        s.add(b)
        await s.commit()
        bid = b.id
    return bid, slot


@pytest.mark.asyncio
async def test_reschedule_far_moves_event(env):
    dp, bot, gcal, session = env
    bid, _ = await _make_confirmed(5, gcal)     # >24ч
    old_events = set(gcal.events)
    await press(dp, bot, f"resched:{bid}")
    day = find_cb(session, "resched_day:")
    await press(dp, bot, day)
    slot = find_cb(session, "resched_slot:")
    await press(dp, bot, slot)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    # slot_start сменился, старое событие удалено, новое создано
    assert b.google_event_id in gcal.events
    assert b.google_event_id not in old_events
    assert b.status == "confirmed"


@pytest.mark.asyncio
async def test_reschedule_near_requires_reason_and_pends(env):
    dp, bot, gcal, session = env
    # бронь через 2 часа — <24ч
    slot = datetime.now(timezone.utc) + timedelta(hours=2)
    eid = await gcal.create_event(slot, "Клиент", "desc")
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot,
                    status="confirmed", google_event_id=eid)
        s.add(b)
        await s.commit()
        bid = b.id
    await press(dp, bot, f"resched:{bid}")
    day = find_cb(session, "resched_day:")
    await press(dp, bot, day)
    new_slot = find_cb(session, "resched_slot:")
    await press(dp, bot, new_slot)
    # бот просит причину — статус ещё не pending, пока причины нет
    # отправляем причину текстом
    from aiogram.types import Update, Message, Chat, User as TgUser
    upd = Update(update_id=999, message=Message(
        message_id=5, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text="заболел ребёнок"))
    await dp.feed_update(bot, upd)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status == "pending"
    assert b.reschedule_reason == "заболел ребёнок"
    assert b.reschedule_to is not None
    # Лане ушли кнопки подтверждения переноса
    admin_cbs = [x.get("callback_data", "") for row in last_kb(session, chat_id=ADMIN_ID) for x in row]
    assert any(c.startswith("resched_ok:") for c in admin_cbs)
    assert any(c.startswith("resched_no:") for c in admin_cbs)
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v`
Expected: FAIL (нет хендлеров переноса).

- [ ] **Step 3: apply_reschedule + FSM + хендлеры в booking.py**

Добавить импорты в booking.py: `from aiogram.fsm.context import FSMContext`, `from aiogram.fsm.state import State, StatesGroup`, `from aiogram.filters import StateFilter`, `from aiogram.types import Message`, и `admin_resched_kb` из keyboards. Константа:
```python
RESCHEDULE_THRESHOLD = timedelta(hours=24)


class RescheduleForm(StatesGroup):
    picking = State()
    reason = State()


async def apply_reschedule(gcal, session, booking, new_slot: datetime) -> bool:
    """Двигает бронь на new_slot. Для confirmed с событием — пересоздаёт событие
    (delete старое + create новое). Возвращает True если Google не подвёл."""
    sync_ok = True
    if booking.google_event_id:
        try:
            await gcal.delete_event(booking.google_event_id)
        except Exception:
            logger.exception("Не удалось удалить старое событие при переносе")
        try:
            title, desc = await build_event_fields(session, booking.telegram_id)
            booking.google_event_id = await gcal.create_event(new_slot, title, desc)
        except Exception:
            logger.exception("Не удалось создать новое событие при переносе")
            booking.google_event_id = None
            booking.calendar_sync_failed = True
            sync_ok = False
    booking.slot_start = new_slot
    return sync_ok
```

Хендлеры:
```python
@router.callback_query(F.data.startswith("resched:"))
async def cb_resched_start(callback: CallbackQuery, state: FSMContext,
                           gcal: GoogleCalendar, booking_config: BookingConfig) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял запись", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if (not booking or booking.telegram_id != callback.from_user.id
                or booking.status not in ("pay_claimed", "confirmed")):
            await callback.answer("Запись недоступна для переноса", show_alert=True)
            return
    await state.set_state(RescheduleForm.picking)
    await state.update_data(resched_booking_id=booking_id)
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при старте переноса")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    if not slots:
        await callback.answer("Свободного времени сейчас нет", show_alert=True)
        return
    first = slots[0].astimezone(booking_config.tz).date()
    await _render_calendar(callback.message, first.year, first.month, slots,
                           booking_config, prefix="resched", back_cb="my_bookings")


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_month:"))
async def cb_resched_month(callback: CallbackQuery, gcal: GoogleCalendar,
                           booking_config: BookingConfig) -> None:
    try:
        y, m = (int(x) for x in callback.data.split(":", 1)[1].split("-"))
    except ValueError:
        await callback.answer("Не понял месяц", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    await _render_calendar(callback.message, y, m, slots, booking_config,
                           prefix="resched", back_cb="my_bookings")


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_day:"))
async def cb_resched_day(callback: CallbackQuery, gcal: GoogleCalendar,
                         booking_config: BookingConfig) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял день", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    day_slots = [s for s in slots if s.astimezone(booking_config.tz).date() == d]
    if not day_slots:
        await callback.answer("На этот день нет свободного времени", show_alert=True)
        return
    time_buttons = [(format_slot_human(s).split("·", 1)[1].strip(), s.isoformat())
                    for s in day_slots]
    await callback.message.edit_text(
        f"<b>✦ Перенос на {_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}</b>\n\n"
        "Выбери время ⇩",
        reply_markup=booking_times_kb(
            d.isoformat(), time_buttons, prefix="resched",
            back_cb=f"resched_month:{d.year}-{d.month:02d}"),
    )


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_slot:"))
async def cb_resched_slot(callback: CallbackQuery, state: FSMContext, bot: Bot,
                          admin_ids: list[int], gcal: GoogleCalendar,
                          booking_config: BookingConfig) -> None:
    try:
        new_slot = datetime.fromisoformat(callback.data.split(":", 1)[1]).astimezone(timezone.utc)
    except ValueError:
        await callback.answer("Не понял слот", show_alert=True)
        return
    data = await state.get_data()
    booking_id = data.get("resched_booking_id")
    if not booking_id:
        await callback.answer("Сессия сброшена, открой «Мои записи» заново", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    try:
        free = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    if new_slot not in free:
        await callback.answer("Это время только что заняли 🤍 Выбери другое", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            await callback.answer("Запись не найдена", show_alert=True)
            await state.clear()
            return
        old_slot = booking.slot_start if booking.slot_start.tzinfo else booking.slot_start.replace(tzinfo=timezone.utc)

        if old_slot - now >= RESCHEDULE_THRESHOLD:
            # самостоятельный перенос
            await apply_reschedule(gcal, session, booking, new_slot)
            await session.commit()
            await state.clear()
            await callback.message.edit_text(
                "○─── ☾ ───○\n\n"
                f"✦ Перенесено на <b>{format_slot_human(new_slot)}</b> 🤍",
                reply_markup=lead_done_kb(),
            )
            await _notify_admins(
                bot, admin_ids,
                "🔁 <b>Клиент перенёс запись</b>\n\n"
                f"Было: {format_slot_human(old_slot)}\n"
                f"Стало: {format_slot_human(new_slot)}\n"
                f"{_client_line(callback)}",
            )
            return

    # <24ч — просим причину (new_slot в FSM), pending выставим после причины
    await state.update_data(resched_new_slot=new_slot.isoformat())
    await state.set_state(RescheduleForm.reason)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "До сессии меньше 24 часов — перенос подтверждает Лана.\n\n"
        "Напиши, пожалуйста, причину переноса ⇩"
    )


@router.message(RescheduleForm.reason, F.text)
async def resched_reason(message: Message, state: FSMContext, bot: Bot,
                         admin_ids: list[int]) -> None:
    data = await state.get_data()
    booking_id = data.get("resched_booking_id")
    new_slot_iso = data.get("resched_new_slot")
    await state.clear()
    if not booking_id or not new_slot_iso:
        await message.answer("Сессия сброшена, открой «Мои записи» заново.")
        return
    new_slot = datetime.fromisoformat(new_slot_iso)
    reason = message.text.strip()[:500]
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != message.from_user.id:
            await message.answer("Запись не найдена.")
            return
        old_slot = booking.slot_start if booking.slot_start.tzinfo else booking.slot_start.replace(tzinfo=timezone.utc)
        booking.reschedule_to = new_slot
        booking.reschedule_reason = reason
        booking.reschedule_status = "pending"
        await session.commit()
    await message.answer(
        "○─── ☾ ───○\n\n"
        "🤍 Запрос на перенос отправлен Лане. Как решится — пришлём сообщение.",
        reply_markup=lead_done_kb(),
    )
    await _notify_admins(
        bot, admin_ids,
        "🔁 <b>Запрос на перенос (меньше 24ч)</b>\n\n"
        f"Было: {format_slot_human(old_slot)}\n"
        f"Хочет: {format_slot_human(new_slot)}\n"
        f"Причина: {html.quote(reason)}\n"
        f'<b>Клиент:</b> id {message.from_user.id}\n\n'
        "Подтвердить перенос? ⇩",
        reply_markup=admin_resched_kb(booking_id),
    )
```
`_render_calendar` расширить параметрами (Task 4 не менял его сигнатуру): добавить `*, prefix="book", back_cb="consultation"` и прокинуть в `booking_calendar_kb(... , prefix=prefix, back_cb=back_cb)`.

- [ ] **Step 4: admin_resched_kb в keyboards/inline.py**

```python
def admin_resched_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить перенос", callback_data=f"resched_ok:{booking_id}")
    builder.button(text="❌ Отклонить перенос", callback_data=f"resched_no:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v`
Expected: PASS (2 теста).

- [ ] **Step 6: Commit**

```bash
git add handlers/booking.py keyboards/inline.py tests/test_reschedule.py
git commit -m "Перенос записи: выбор слота, ≥24ч сам / <24ч запрос с причиной"
```

---

## Task 7: Лана подтверждает/отклоняет перенос

**Files:**
- Modify: `handlers/admin.py` (`cb_resched_ok`, `cb_resched_no`)
- Modify: `tests/test_reschedule.py`

**Interfaces:**
- Consumes: `apply_reschedule`, `_load_free`/`free_slots` (проверка занятости нового слота), `Booking`.
- Produces: callbacks `resched_ok:<id>`, `resched_no:<id>`.

- [ ] **Step 1: Тесты approve/reject**

Добавить в `tests/test_reschedule.py`:
```python
async def _pending_near(env):
    dp, bot, gcal, session = env
    import booking_config
    from slots import free_slots
    cfg = booking_config.load()
    now = datetime.now(timezone.utc)
    slot = now + timedelta(hours=2)          # исходная сессия <24ч
    eid = await gcal.create_event(slot, "Клиент", "desc")
    # reschedule_to должен быть РЕАЛЬНЫМ слотом по сетке (free_slots отдаёт только
    # сеточные времена), иначе approve-хендлер честно сочтёт его занятым.
    free = free_slots(now, [], [], work_times=cfg.work_times,
                      work_weekdays=cfg.work_weekdays, horizon_days=cfg.horizon_days,
                      lead=cfg.lead, tz=cfg.tz)
    new_slot = next(s for s in free if s - now >= timedelta(days=1))
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="confirmed",
                    google_event_id=eid, reschedule_to=new_slot,
                    reschedule_reason="повод", reschedule_status="pending")
        s.add(b)
        await s.commit()
        bid = b.id
    return bid, eid, new_slot


@pytest.mark.asyncio
async def test_admin_approve_moves_booking(env):
    dp, bot, gcal, session = env
    bid, old_eid, new_slot = await _pending_near(env)
    from aiogram.types import User as TgUser
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_ok:{bid}", user=admin, chat_id=ADMIN_ID)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status is None
    assert b.slot_start.replace(tzinfo=timezone.utc) == new_slot
    assert old_eid in gcal.deleted            # старое событие удалено
    assert b.google_event_id in gcal.events   # новое создано


@pytest.mark.asyncio
async def test_admin_reject_cancels_without_refund(env):
    dp, bot, gcal, session = env
    bid, old_eid, _ = await _pending_near(env)
    from aiogram.types import User as TgUser
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_no:{bid}", user=admin, chat_id=ADMIN_ID)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.status == "cancelled"
    assert old_eid in gcal.deleted
    client_texts = [d.get("text", "") for n, d in session.log if d.get("chat_id") == CLIENT_ID]
    assert any("не возвращается" in t for t in client_texts)
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v -k "approve or reject_cancels"`
Expected: FAIL.

- [ ] **Step 3: Хендлеры в admin.py**

Добавить импорты: `from handlers.booking import apply_reschedule, _occupied_slots` (или локально), `from slots import free_slots`, `from booking_config import BookingConfig`, `from datetime import timedelta`. Хендлеры:
```python
@router.callback_query(F.data.startswith("resched_ok:"))
async def cb_resched_ok(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar,
                        booking_config: BookingConfig) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.reschedule_status != "pending":
            await callback.answer("Запрос уже обработан", show_alert=True)
            return
        new_slot = booking.reschedule_to
        if new_slot.tzinfo is None:
            new_slot = new_slot.replace(tzinfo=timezone.utc)
        # новый слот всё ещё свободен?
        busy = await gcal.busy(now, now + timedelta(days=booking_config.horizon_days))
        occupied = await _occupied_slots(session, now)
        free = free_slots(now, busy, occupied,
                          work_times=booking_config.work_times,
                          work_weekdays=booking_config.work_weekdays,
                          horizon_days=booking_config.horizon_days,
                          lead=booking_config.lead, tz=booking_config.tz)
        if new_slot not in free:
            booking.reschedule_status = None
            booking.reschedule_to = None
            booking.reschedule_reason = None
            await session.commit()
            user_id = booking.telegram_id
            await callback.answer("Новый слот уже занят — перенос отменён", show_alert=True)
            await callback.message.edit_text(
                callback.message.html_text + "\n\n⚠️ <b>Новый слот занят, перенос не выполнен</b>")
            try:
                await bot.send_message(
                    user_id,
                    "К сожалению, выбранное для переноса время уже заняли. "
                    "Запись осталась на прежнем слоте 🤍")
            except TelegramAPIError:
                pass
            return
        await apply_reschedule(gcal, session, booking, new_slot)
        booking.reschedule_status = None
        booking.reschedule_to = None
        booking.reschedule_reason = None
        await session.commit()
        user_id, moved = booking.telegram_id, new_slot
    try:
        await bot.send_message(
            user_id,
            "○─── ☾ ───○\n\n"
            f"✦ Перенос подтверждён: <b>{format_slot_human(moved)}</b> 🤍",
            reply_markup=lead_done_kb())
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        callback.message.html_text + "\n\n✅ <b>Перенос подтверждён</b>")


@router.callback_query(F.data.startswith("resched_no:"))
async def cb_resched_no(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.reschedule_status != "pending":
            await callback.answer("Запрос уже обработан", show_alert=True)
            return
        event_id = booking.google_event_id
        booking.status = "cancelled"
        booking.reschedule_status = None
        booking.reschedule_to = None
        booking.reschedule_reason = None
        await session.commit()
        user_id = booking.telegram_id
    if event_id:
        try:
            await gcal.delete_event(event_id)
        except Exception:
            logger.exception("Не удалось удалить событие при отклонении переноса")
    try:
        await bot.send_message(
            user_id,
            "○─── ☾ ───○\n\n"
            "Перенос отклонён. К сожалению, запись отменена, "
            "оплата не возвращается 🤍",
            reply_markup=lead_done_kb())
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        callback.message.html_text + "\n\n❌ <b>Перенос отклонён, запись отменена</b>")
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v`
Expected: PASS (все).

- [ ] **Step 5: Полный прогон + компиляция**

Run: `python -m py_compile handlers/admin.py handlers/booking.py && PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add handlers/admin.py tests/test_reschedule.py
git commit -m "Лана подтверждает/отклоняет перенос (<24ч); reject отменяет без возврата"
```

---

## Task 8: Доки + финальная проверка

**Files:**
- Modify: `README.md`, `CLAUDE.md`

**Interfaces:** нет кода.

- [ ] **Step 1: Обновить README и CLAUDE.md**

В README: «Мои записи» и перенос (≥24ч сам / <24ч согласие Ланы, reject → отмена без возврата), лимит 5, событие в календаре теперь на подтверждении, авто-миграция (ручной DROP больше не нужен). В CLAUDE.md обновить раздел «Флоу записи»: событие на confirm, занятость держит pay_claimed, поля переноса, `MAX_ACTIVE_BOOKINGS`, `RESCHEDULE_THRESHOLD`.

- [ ] **Step 2: Полная компиляция**

Run: `python -m py_compile main.py database.py followup.py slots.py google_calendar.py booking_config.py formatting.py handlers/*.py keyboards/inline.py`
Expected: чисто.

- [ ] **Step 3: Полный прогон**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Доки: перенос записи, лимит 5, событие на подтверждении, авто-миграция"
```

---

## Self-Review (выполнено при написании плана)

**Spec coverage:**
- Событие на confirm → Task 3 (+ занятость Task 2). ✓
- Занятость pay_claimed → Task 2. ✓
- Лимит 5 → Task 2. ✓
- Модель + миграция → Task 1. ✓
- «Мои записи» → Task 5. ✓
- Перенос ≥24ч / <24ч + причина → Task 6. ✓
- Approve/reject Ланой, reject=отмена без возврата → Task 7. ✓
- Параметризация календаря (переиспользование) → Task 4. ✓
- Обработка ошибок Google при переносе → Task 6 (`apply_reschedule`/хендлеры), Task 7. ✓
- Доки → Task 8. ✓

**Placeholder scan:** конкретный код в каждом шаге; «проверь/подтверди» относятся к чтению существующего кода (cb_reject_pay уже совместим), не к недописанному коду. ✓

**Type consistency:** `_occupied_slots`, `_active_booking_count`, `build_event_fields`, `apply_reschedule` — сигнатуры одинаковы в определении (Task 2/3/6) и вызовах (Task 3/6/7). Префиксы callback (`resched_day/month/slot/ok/no`) согласованы между keyboards (Task 4/6) и хендлерами (Task 6/7). `booking_calendar_kb`/`booking_times_kb` с `prefix`/`back_cb` — Task 4 и вызовы Task 6. Статусы и поля переноса — единообразны. ✓
