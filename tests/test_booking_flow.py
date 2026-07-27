import pytest
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.base import BaseSession
from aiogram.enums import ParseMode
from aiogram.types import CallbackQuery, Chat, Message, Update, User as TgUser

import database
from database import Booking, get_session, init_db, close_db
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

# _dp (собранный на весь процесс Dispatcher с роутерами) живёт в
# tests/conftest.py — см. комментарий там про переиспользование харнеса
# несколькими тестовыми файлами (test_reschedule.py и т.д.).


@pytest_asyncio.fixture
async def env(_dp):
    await init_db("sqlite+aiosqlite:///:memory:")
    session = FakeSession()
    bot = Bot(token="1:AA", session=session,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    gcal = FakeGCal()
    cfg = booking_config.load()
    _dp["admin_ids"] = [ADMIN_ID]
    _dp["booking_config"] = cfg
    _dp["gcal"] = gcal
    # _dp — session-scoped, его MemoryStorage переживает между тестами. FSM-флоу
    # (перенос) может оставить состояние в picking/reason со stale data — чистим
    # хранилище для тестовых ключей ПЕРЕД каждым тестом, чтобы старт был с нуля.
    from aiogram.fsm.storage.base import StorageKey
    for uid in (CLIENT_ID, ADMIN_ID):
        key = StorageKey(bot_id=bot.id, chat_id=uid, user_id=uid)
        await _dp.storage.set_state(key, None)
        await _dp.storage.set_data(key, {})
    yield _dp, bot, gcal, session
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


async def _book_one(dp, bot, session):
    await press(dp, bot, "booking_start")
    await press(dp, bot, find_cb(session, "book_day:"))
    await press(dp, bot, find_cb(session, "book_slot:"))
    return find_cb(session, "paid:")


@pytest.mark.asyncio
async def test_paid_notifies_admin_without_creating_event(env):
    # переименовано из test_paid_creates_event_and_notifies_admin: событие
    # теперь создаётся на confirm (см. test_event_created_on_confirm_not_on_paid),
    # а не на paid — здесь фиксируем, что paid только переводит статус и шлёт
    # админу кнопки, календаря не касаясь.
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "pay_claimed"
    assert b.google_event_id is None
    assert gcal.events == {}
    # админу ушло уведомление с кнопками подтвердить/отклонить
    admin_kb = last_kb(session, chat_id=ADMIN_ID)
    flat = [x.get("callback_data", "") for row in admin_kb for x in row]
    assert any(c.startswith("confirm_pay:") for c in flat)
    assert any(c.startswith("reject_pay:") for c in flat)


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


@pytest.mark.asyncio
async def test_double_confirm_creates_single_event(env):
    # переименовано из test_double_paid_creates_single_event: событие теперь
    # создаётся в cb_confirm_pay, поэтому double-click-защита от дублирующего
    # события переехала туда же (двойной paid больше не трогает календарь
    # вообще — см. test_paid_notifies_admin_without_creating_event).
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)  # второй клик
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_reject_pay_deletes_event_and_frees_slot(env):
    # переименовано по смыслу не было, но сценарий адаптирован: в новой схеме
    # pay_claimed никогда не получает google_event_id естественным путём
    # (событие появляется только вместе с переходом в confirmed) — реальный
    # UI-флоу это больше не воспроизводит. Тест проверяет defense-in-depth
    # ветку `if event_id:` в cb_reject_pay, вручную проставляя event_id на
    # pay_claimed-записи (как если бы это состояние возникло нештатно) —
    # чтобы удаление события при отклонении не осталось без покрытия.
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
        b.google_event_id = "evt_manual"
        await s.commit()
    gcal.events["evt_manual"] = b.slot_start
    reject = find_cb(session, "reject_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, reject, user=admin, chat_id=ADMIN_ID)
    assert gcal.deleted == ["evt_manual"]
    assert "evt_manual" not in gcal.events
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
    # адаптировано: Google теперь дёргается в cb_confirm_pay, а не в cb_paid —
    # падение имитируем на confirm; запись всё равно переходит в confirmed
    # (админ уже проверил оплату), просто с пометкой calendar_sync_failed.
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    async def boom(*a, **k):
        raise RuntimeError("insert failed")
    gcal.create_event = boom
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "confirmed"
    assert b.calendar_sync_failed is True
    assert b.google_event_id is None


@pytest.mark.asyncio
async def test_past_confirmed_booking_does_not_block_new_booking(env):
    dp, bot, gcal, session = env
    from sqlalchemy import select
    async with get_session() as s:
        s.add(Booking(
            telegram_id=CLIENT_ID,
            slot_start=datetime.now(timezone.utc) - timedelta(days=10),
            status="confirmed",
        ))
        await s.commit()
    # клиент с ПРОШЕДШЕЙ подтверждённой записью должен свободно дойти до
    # выбора дня/времени и создать новый held, а не упереться в алерт
    # «уже есть активная запись»
    paid = await _book_one(dp, bot, session)
    assert paid is not None
    async with get_session() as s:
        bookings = (await s.execute(select(Booking))).scalars().all()
    held = [b for b in bookings if b.status == "held"]
    assert len(held) == 1


@pytest.mark.asyncio
async def test_reject_after_confirm_is_noop(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    reject = find_cb(session, "reject_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    deleted_before = len(gcal.deleted)

    # второй админ (или то же открытое сообщение) жмёт «Отклонить» на уже
    # подтверждённой записи — должно быть no-op
    await press(dp, bot, reject, user=admin, chat_id=ADMIN_ID)

    from sqlalchemy import select
    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "confirmed"
    assert len(gcal.deleted) == deleted_before  # событие не удалено повторно
    client_texts = [d.get("text", "") for n, d in session.log if d.get("chat_id") == CLIENT_ID]
    assert not any("не нашли" in t for t in client_texts)  # клиенту не сказали "отменено"


@pytest.mark.asyncio
async def test_quiz_answer_without_state_gives_hint(env):
    dp, bot, gcal, session = env
    # без quiz_begin — состояния Quiz.in_progress нет
    await press(dp, bot, "quiz_ans:3")
    texts = [d.get("text", "") for n, d in session.log if d.get("chat_id") == CLIENT_ID]
    assert any("заново" in t.lower() or "сброш" in t.lower() for t in texts)


@pytest.mark.asyncio
async def test_booking_start_renders_calendar(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "booking_start")
    kb = last_kb(session)
    cbs = [b.get("callback_data", "") for row in kb for b in row]
    # календарь: есть шапка-навигация (noop-заголовок) и хотя бы один свободный день
    assert "noop" in cbs
    assert any(c.startswith("book_day:") for c in cbs)


@pytest.mark.asyncio
async def test_calendar_month_navigation(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "booking_start")
    nav = find_cb(session, "book_month:")
    if nav is None:
        pytest.skip("горизонт уместился в один месяц — навигации нет")
    await press(dp, bot, nav)
    kb = last_kb(session)
    cbs = [b.get("callback_data", "") for row in kb for b in row]
    # после навигации всё ещё календарь (шапка на месте)
    assert "noop" in cbs


@pytest.mark.asyncio
async def test_noop_does_not_crash(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "booking_start")
    before = len(session.log)
    await press(dp, bot, "noop")  # тап по неактивной ячейке
    # не упало и не отправило клиенту нового сообщения
    new_client_msgs = [
        d for n, d in session.log[before:]
        if n in ("SendMessage", "EditMessageText") and d.get("chat_id") == CLIENT_ID
    ]
    assert new_client_msgs == []


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
async def test_fifth_active_booking_allowed(env):
    dp, bot, gcal, session = env
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import select, func
    # 4 активных confirmed в будущем
    async with get_session() as s:
        for i in range(4):
            s.add(Booking(
                telegram_id=CLIENT_ID,
                slot_start=datetime.now(timezone.utc) + timedelta(days=2 + i),
                status="confirmed",
            ))
        await s.commit()
    # 5-я бронь должна пройти (при лимите=1 упала бы)
    await press(dp, bot, "booking_start")
    await press(dp, bot, find_cb(session, "book_day:"))
    await press(dp, bot, find_cb(session, "book_slot:"))
    async with get_session() as s:
        held = (await s.execute(
            select(func.count()).select_from(Booking).where(Booking.status == "held")
        )).scalar()
    assert held == 1   # 5-я запись создана как held


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


@pytest.mark.asyncio
async def test_confirm_collapses_admin_notification(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    # последний EditMessageText в чат Ланы — короткая итоговая строка
    edits = [d for n, d in session.log
             if n == "EditMessageText" and d.get("chat_id") == ADMIN_ID]
    last = edits[-1]["text"]
    assert last.startswith("✅")          # старый код начинался бы с "x"
    assert "подтвержд" in last.lower()
    assert "Проверь оплату в Tribute" not in last   # полный исходный текст ушёл


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
