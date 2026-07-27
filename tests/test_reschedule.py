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
