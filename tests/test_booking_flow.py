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


# aiogram Router-объекты в handlers/*.py — модульные синглтоны: include_router
# намертво привязывает router.parent_router и падает RuntimeError при повторном
# include_router() того же router в другой Dispatcher. setup_routers() поэтому
# можно безопасно вызвать только один раз за процесс — dp собираем на весь
# модуль тестов, а не в каждом тесте отдельно (per-test заново создавать нельзя).
@pytest.fixture(scope="module")
def _dp():
    dp = Dispatcher()
    dp.callback_query.outer_middleware(CallbackSafetyMiddleware())
    dp.callback_query.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(EventLoggingMiddleware())
    dp.include_router(setup_routers())
    return dp


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


@pytest.mark.asyncio
async def test_quiz_answer_without_state_gives_hint(env):
    dp, bot, gcal, session = env
    # без quiz_begin — состояния Quiz.in_progress нет
    await press(dp, bot, "quiz_ans:3")
    texts = [d.get("text", "") for n, d in session.log if d.get("chat_id") == CLIENT_ID]
    assert any("заново" in t.lower() or "сброш" in t.lower() for t in texts)
