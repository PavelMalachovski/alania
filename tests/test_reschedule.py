import pytest
from datetime import datetime, timedelta, timezone

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


@pytest.mark.asyncio
async def test_reschedule_reason_edits_anchor_and_deletes_user_text(env):
    dp, bot, gcal, session = env
    # бронь через 2 часа (<24ч), заводим перенос
    slot = datetime.now(timezone.utc) + timedelta(hours=2)
    eid = await gcal.create_event(slot, "Клиент", "desc")
    from slots import free_slots
    import booking_config
    cfg = booking_config.load()
    free = free_slots(datetime.now(timezone.utc), [], [], work_times=cfg.work_times,
                      work_weekdays=cfg.work_weekdays, horizon_days=cfg.horizon_days,
                      lead=cfg.lead, tz=cfg.tz)
    new_slot = next(s for s in free if s - datetime.now(timezone.utc) >= timedelta(days=1))
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="confirmed",
                    google_event_id=eid)
        s.add(b); await s.commit(); bid = b.id
    # входим в поток: resched → day → slot (доводим до запроса причины)
    await press(dp, bot, f"resched:{bid}")
    await press(dp, bot, find_cb(session, "resched_day:"))
    await press(dp, bot, find_cb(session, "resched_slot:"))
    # шлём причину текстом
    from aiogram.types import Update, Message, Chat, User as TgUser
    before_sends = sum(1 for n, d in session.log
                       if n == "SendMessage" and d.get("chat_id") == CLIENT_ID)
    upd = Update(update_id=99, message=Message(
        message_id=4242, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text="заболел ребёнок"))
    await dp.feed_update(bot, upd)
    after_sends = sum(1 for n, d in session.log
                      if n == "SendMessage" and d.get("chat_id") == CLIENT_ID)
    # клиенту НЕ ушло новое сообщение (отредактирован якорь)
    assert after_sends == before_sends
    # текст клиента удалён
    assert any(n == "DeleteMessage" and d.get("message_id") == 4242
               for n, d in session.log)
    # запрос всё равно создан
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status == "pending"


@pytest.mark.asyncio
async def test_apply_reschedule_no_event_just_moves_slot(env):
    # pay_claimed без google_event_id: apply_reschedule не должна трогать
    # календарь, только двигает slot_start и возвращает True (sync_ok)
    dp, bot, gcal, session = env
    from handlers.booking import apply_reschedule
    old_slot = datetime.now(timezone.utc) + timedelta(days=3)
    new_slot = datetime.now(timezone.utc) + timedelta(days=6)
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=old_slot,
                    status="pay_claimed", google_event_id=None)
        s.add(b)
        await s.commit()
        ok = await apply_reschedule(gcal, s, b, new_slot)
        await s.commit()
        bid = b.id
    assert ok is True
    assert gcal.events == {}
    assert gcal.deleted == []
    async with get_session() as s:
        b = await s.get(Booking, bid)
    stored = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
    assert stored == new_slot


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


@pytest.mark.asyncio
async def test_resched_ok_non_pending_is_noop(env):
    dp, bot, gcal, session = env
    from aiogram.types import User as TgUser
    slot = datetime.now(timezone.utc) + timedelta(days=5)
    eid = await gcal.create_event(slot, "Клиент", "desc")
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="confirmed",
                    google_event_id=eid)  # reschedule_status=None → НЕ pending
        s.add(b); await s.commit(); bid = b.id
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_ok:{bid}", user=admin, chat_id=ADMIN_ID)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.status == "confirmed"                     # не тронут
    assert b.slot_start.replace(tzinfo=timezone.utc) == slot
    assert gcal.deleted == [] and eid in gcal.events   # календарь не тронут


@pytest.mark.asyncio
async def test_approve_when_new_slot_taken_keeps_original(env):
    dp, bot, gcal, session = env
    from aiogram.types import User as TgUser
    bid, old_eid, new_slot = await _pending_near(env)   # pending с реальным new_slot
    # делаем new_slot занятым в Google
    gcal.busy_intervals = [(new_slot, new_slot + timedelta(hours=1))]
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_ok:{bid}", user=admin, chat_id=ADMIN_ID)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status is None                  # pending снят
    assert b.status == "confirmed"                      # НЕ отменён
    assert b.slot_start.replace(tzinfo=timezone.utc) != new_slot  # не двинут
    assert old_eid not in gcal.deleted                  # старое событие не удалено


@pytest.mark.asyncio
async def test_occupied_slots_includes_sync_failed_confirmed(env):
    """Fix 1: confirmed-бронь без события в Google (calendar_sync_failed=True)
    ничем, кроме _occupied_slots, не защищена от double-booking — слот должен
    попадать в список занятых."""
    dp, bot, gcal, session = env
    now = datetime.now(timezone.utc)
    slot = now + timedelta(days=3)
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="confirmed",
                    google_event_id=None, calendar_sync_failed=True)
        s.add(b)
        await s.commit()
    from handlers.booking import _occupied_slots
    async with get_session() as s:
        occupied = await _occupied_slots(s, now)
    assert slot in occupied


@pytest.mark.asyncio
async def test_resched_ok_google_down_leaves_pending(env):
    """Fix 2: если gcal.busy() падает при подтверждении переноса, Лана видит
    алерт, а бронь остаётся нетронутой (pending, старый слот, событие)."""
    dp, bot, gcal, session = env
    from aiogram.types import User as TgUser
    bid, old_eid, new_slot = await _pending_near(env)
    gcal.raise_on_busy = True
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_ok:{bid}", user=admin, chat_id=ADMIN_ID)
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status == "pending"             # не тронуто
    assert b.status == "confirmed"
    assert b.slot_start.replace(tzinfo=timezone.utc) != new_slot  # не переехало
    assert b.google_event_id == old_eid                 # событие не пересоздано
    assert old_eid not in gcal.deleted


@pytest.mark.asyncio
async def test_resched_reject_collapses_admin_notification(env):
    dp, bot, gcal, session = env
    bid, old_eid, _ = await _pending_near(env)
    from aiogram.types import User as TgUser
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_no:{bid}", user=admin, chat_id=ADMIN_ID)
    edits = [d for n, d in session.log
             if n == "EditMessageText" and d.get("chat_id") == ADMIN_ID]
    assert edits[-1]["text"].startswith("❌")   # старый код начинался бы с "x"
    assert "отклонён" in edits[-1]["text"].lower()
    assert "Причина:" not in edits[-1]["text"]


@pytest.mark.asyncio
async def test_resched_reason_command_escapes(env):
    """Fix 3: команда (/cancel) вместо причины переноса не сохраняется как
    причина — FSM очищается, pending не выставляется."""
    dp, bot, gcal, session = env
    slot = datetime.now(timezone.utc) + timedelta(hours=2)   # <24ч
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
    new_slot_cb = find_cb(session, "resched_slot:")
    await press(dp, bot, new_slot_cb)

    from aiogram.types import Update, Message, Chat, User as TgUser
    upd = Update(update_id=1001, message=Message(
        message_id=6, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text="/cancel"))
    await dp.feed_update(bot, upd)

    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status is None
    assert b.reschedule_reason is None

    from aiogram.fsm.storage.base import StorageKey
    key = StorageKey(bot_id=bot.id, chat_id=CLIENT_ID, user_id=CLIENT_ID)
    assert await dp.storage.get_state(key) is None
