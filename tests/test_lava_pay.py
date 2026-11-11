"""Оплата через lava.top: выбор валюты → email (один раз) → счёт →
автоподтверждение фоновой проверкой или кнопкой «✓ Я оплатил(а)»."""
from datetime import datetime, timedelta, timezone

import pytest
from aiogram.types import User as TgUser
from sqlalchemy import select

import payments
from database import Booking, Payment, User, get_session
from handlers.payments import PAY_UNAVAILABLE_TEXT
from keyboards.inline import GAME_URL, game_kb
from lava import OFFERS
from tests.test_booking_flow import (  # харнес
    ADMIN_ID, CLIENT_ID, FakeLava, env, find_cb, last_kb, press,
)
from tests.test_reply_keyboard import _send_text

EMAIL = "marina@mail.ru"


def _client_texts(session, method="SendMessage"):
    return [d.get("text") or "" for n, d in session.log
            if n == method and d.get("chat_id") == CLIENT_ID]


def _admin_texts(session):
    return [d.get("text") or "" for n, d in session.log
            if n == "SendMessage" and d.get("chat_id") == ADMIN_ID]


def _alerts(session):
    return [d.get("text") or "" for n, d in session.log if n == "AnswerCallbackQuery"]


def _last_edit(session):
    edits = [d for n, d in session.log
             if n == "EditMessageText" and d.get("chat_id") == CLIENT_ID]
    return edits[-1]


async def _hold(dp, bot, session) -> int:
    await press(dp, bot, "booking_start")
    await press(dp, bot, find_cb(session, "book_day:"))
    await press(dp, bot, find_cb(session, "book_slot:"))
    async with get_session() as s:
        return (await s.execute(select(Booking.id).order_by(Booking.id.desc()))).scalars().first()


async def _pay(dp, bot, session, data):
    """Нажать «Оплатить …» и подтвердить все пункты экрана согласий, если он
    показан (каждый — своей кнопкой, как клиент)."""
    await press(dp, bot, data)
    for _ in range(3):
        ok = find_cb(session, "lava_ok:")
        if ok is None:
            return
        await press(dp, bot, ok)
    raise AssertionError("экран согласий не отпускает")


async def _save_email(email=EMAIL, tg_id=CLIENT_ID):
    async with get_session() as s:
        s.add(User(telegram_id=tg_id, full_name="Марина", username="marina", email=email))
        await s.commit()


async def _invoice(dp, bot, session, currency="RUB"):
    """Бронь + сохранённый email + счёт. (booking_id, Payment)."""
    await _save_email()
    bid = await _hold(dp, bot, session)
    await _pay(dp, bot, session, f"lava_pay:session:{currency}:{bid}")
    async with get_session() as s:
        payment = (await s.execute(select(Payment).order_by(Payment.id.desc()))).scalars().first()
    return bid, payment


async def _pass(dp, bot, gcal, now=None):
    return await payments.payments_pass(bot, [ADMIN_ID], gcal, dp["booking_config"],
                                        dp["lava"], now=now)


async def _booking(bid):
    async with get_session() as s:
        return await s.get(Booking, bid)


async def _payment(pid):
    async with get_session() as s:
        return await s.get(Payment, pid)


@pytest.mark.asyncio
async def test_pay_screen_offers_lava_currencies_only(env):
    dp, bot, gcal, session = env
    bid = await _hold(dp, bot, session)
    cbs = [b.get("callback_data", "") for row in last_kb(session) for b in row]
    assert f"lava_pay:session:RUB:{bid}" in cbs and f"lava_pay:session:EUR:{bid}" in cbs
    assert not any(c.startswith(("pay_crypto:", "paid:", "paid_crypto:")) for c in cbs)
    urls = [b.get("url", "") for row in last_kb(session) for b in row]
    assert not any("tribute" in u for u in urls)


@pytest.mark.asyncio
async def test_first_payment_asks_email_once(env):
    dp, bot, gcal, session = env
    lava = dp["lava"]
    bid = await _hold(dp, bot, session)
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    assert "Напиши свой email" in _last_edit(session)["text"]
    assert lava.created == []

    await _send_text(dp, bot, "не помню", mid=8001)
    assert "не похоже на email" in _last_edit(session)["text"]
    assert any(n == "DeleteMessage" and d.get("message_id") == 8001 for n, d in session.log)

    await _send_text(dp, bot, EMAIL, mid=8002)
    assert lava.created == [(EMAIL, OFFERS["session"], "RUB")]
    assert any(n == "DeleteMessage" and d.get("message_id") == 8002 for n, d in session.log)
    last = _last_edit(session)
    assert last["message_id"] == 777                      # тот же экран-якорь
    assert "5000 ₽" in last["text"] and EMAIL in last["text"]
    urls = [b.get("url") for row in last["reply_markup"]["inline_keyboard"] for b in row]
    assert "https://pay.lava.top/inv_1" in urls
    async with get_session() as s:
        assert (await s.get(User, CLIENT_ID)).email == EMAIL
        p = (await s.execute(select(Payment))).scalar_one()
    assert (p.booking_id, p.product, p.currency, p.status) == (bid, "session", "RUB", "new")

    # второй счёт — без вопроса про email
    await _pay(dp, bot, session, f"lava_pay:session:EUR:{bid}")
    assert lava.created[-1] == (EMAIL, OFFERS["session"], "EUR")


@pytest.mark.asyncio
async def test_email_rejected_by_lava_asks_again(env):
    dp, bot, gcal, session = env
    await _save_email("typo@mail.rru")
    bid = await _hold(dp, bot, session)
    dp["lava"].fail = "email"
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    assert "lava.top не принял этот email" in _last_edit(session)["text"]
    dp["lava"].fail = None
    await _send_text(dp, bot, EMAIL, mid=8101)
    assert dp["lava"].created == [(EMAIL, OFFERS["session"], "RUB")]


@pytest.mark.asyncio
async def test_lava_down_shows_retry_not_dead_button(env):
    dp, bot, gcal, session = env
    await _save_email()
    bid = await _hold(dp, bot, session)
    dp["lava"].fail = "down"
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    last = _last_edit(session)
    assert last["text"] == PAY_UNAVAILABLE_TEXT
    cbs = [b.get("callback_data") for row in last["reply_markup"]["inline_keyboard"] for b in row]
    assert f"lava_pay:session:RUB:{bid}" in cbs


@pytest.mark.asyncio
async def test_no_api_key_shows_unavailable(env):
    dp, bot, gcal, session = env
    await _save_email()
    bid = await _hold(dp, bot, session)
    dp["lava"] = None
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    assert _last_edit(session)["text"] == PAY_UNAVAILABLE_TEXT


@pytest.mark.asyncio
async def test_completed_payment_confirms_booking_once(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    assert await _pass(dp, bot, gcal) == 1        # ещё не оплачен
    assert (await _booking(bid)).status == "held"

    dp["lava"].statuses[p.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    b = await _booking(bid)
    assert b.status == "confirmed" and b.google_event_id in gcal.events
    assert b.calendar_sync_failed is False
    assert (await _payment(p.id)).status == "completed"
    assert any("Запись подтверждена" in t for t in _client_texts(session))
    assert any("Оплата через lava.top" in t and EMAIL in t for t in _admin_texts(session))
    # экран счёта с кнопкой «Оплатить» убран
    assert any(n == "DeleteMessage" and d.get("message_id") == p.message_id
               for n, d in session.log)

    await _pass(dp, bot, gcal)                    # повторный проход — ничего нового
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_paid_button_checks_right_away(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    await press(dp, bot, f"lava_check:{p.id}")
    assert any("пока не поступила" in t for t in _alerts(session))
    assert (await _booking(bid)).status == "held"

    dp["lava"].statuses[p.invoice_id] = "completed"
    await press(dp, bot, f"lava_check:{p.id}")
    assert (await _booking(bid)).status == "confirmed"
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_someone_elses_payment_is_not_checked(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    dp["lava"].statuses[p.invoice_id] = "completed"
    stranger = TgUser(id=777000, is_bot=False, first_name="X")
    await press(dp, bot, f"lava_check:{p.id}", user=stranger, chat_id=777000)
    assert (await _booking(bid)).status == "held"


@pytest.mark.asyncio
async def test_late_payment_for_taken_slot_goes_to_lana(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    b = await _booking(bid)
    async with get_session() as s:
        mine = await s.get(Booking, bid)
        mine.held_until = datetime.now(timezone.utc) - timedelta(minutes=5)
        # пока клиент платил, этот слот взял другой
        s.add(Booking(telegram_id=999, slot_start=b.slot_start, status="held",
                      held_until=datetime.now(timezone.utc) + timedelta(minutes=20)))
        await s.commit()
    dp["lava"].statuses[p.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    assert (await _booking(bid)).status == "paid_conflict"
    assert gcal.events == {}
    assert any("слот уже занят" in t for t in _admin_texts(session))
    assert any("успели занять" in t for t in _client_texts(session))


@pytest.mark.asyncio
async def test_late_payment_for_free_slot_still_confirms(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    async with get_session() as s:
        (await s.get(Booking, bid)).held_until = datetime.now(timezone.utc) - timedelta(minutes=5)
        await s.commit()
    dp["lava"].statuses[p.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    assert (await _booking(bid)).status == "confirmed"


@pytest.mark.asyncio
async def test_second_payment_for_same_booking_flags_lana(env):
    dp, bot, gcal, session = env
    bid, rub = await _invoice(dp, bot, session, "RUB")
    await _pay(dp, bot, session, f"lava_pay:session:EUR:{bid}")
    async with get_session() as s:
        eur = (await s.execute(select(Payment).where(Payment.currency == "EUR"))).scalar_one()
    dp["lava"].statuses[rub.invoice_id] = "completed"
    dp["lava"].statuses[eur.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    assert len(gcal.events) == 1
    assert any("Лишняя оплата" in t for t in _admin_texts(session))


@pytest.mark.asyncio
async def test_failed_payment_tells_client(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    dp["lava"].statuses[p.invoice_id] = "failed"
    await _pass(dp, bot, gcal)
    assert (await _payment(p.id)).status == "failed"
    assert (await _booking(bid)).status == "held"
    assert any("Оплата не прошла" in t for t in _client_texts(session))


@pytest.mark.asyncio
async def test_polling_slows_down_then_gives_up(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    now = datetime.now(timezone.utc)
    async with get_session() as s:
        row = await s.get(Payment, p.id)
        row.created_at = now - timedelta(hours=2)
        row.checked_at = now - timedelta(minutes=2)
        await s.commit()
    assert await _pass(dp, bot, gcal, now=now) == 0           # проверяли недавно
    assert await _pass(dp, bot, gcal, now=now + timedelta(minutes=11)) == 1

    async with get_session() as s:
        (await s.get(Payment, p.id)).created_at = now - timedelta(hours=49)
        await s.commit()
    assert await _pass(dp, bot, gcal, now=now) == 0
    assert (await _payment(p.id)).status == "expired"

    # заплатили позже, чем опрос сдался: кнопка всё равно проверяет
    dp["lava"].statuses[p.invoice_id] = "completed"
    await press(dp, bot, f"lava_check:{p.id}")
    assert (await _payment(p.id)).status == "completed"


@pytest.mark.asyncio
async def test_course_payment_sends_access_note(env):
    dp, bot, gcal, session = env
    await _save_email()
    await _pay(dp, bot, session, "lava_pay:course:RUB:0")
    assert dp["lava"].created == [(EMAIL, OFFERS["course"], "RUB")]
    assert "Курс-практикум" in _last_edit(session)["text"]
    async with get_session() as s:
        p = (await s.execute(select(Payment))).scalar_one()
    assert p.product == "course" and p.booking_id is None
    dp["lava"].statuses[p.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    assert any("пришлёт доступ" in t and EMAIL in t for t in _client_texts(session))
    assert any("Покупка через lava.top" in t for t in _admin_texts(session))
    assert gcal.events == {}


@pytest.mark.asyncio
async def test_game_screen_sells_via_lava_and_keeps_game_link(env):
    dp, bot, gcal, session = env
    buttons = [b for row in game_kb().inline_keyboard for b in row]
    cbs = [b.callback_data for b in buttons if b.callback_data]
    assert "lava_pay:game:RUB:0" in cbs and "lava_pay:game:EUR:0" in cbs
    assert GAME_URL in [b.url for b in buttons]
    await _save_email()
    await _pay(dp, bot, session, "lava_pay:game:EUR:0")
    assert dp["lava"].created == [(EMAIL, OFFERS["game"], "EUR")]


@pytest.mark.asyncio
async def test_back_from_email_prompt_cancels_input(env):
    dp, bot, gcal, session = env
    bid = await _hold(dp, bot, session)
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    await press(dp, bot, f"lava_back:session:{bid}")
    assert "Твой слот" in _last_edit(session)["text"]
    await _send_text(dp, bot, EMAIL, mid=8201)
    assert dp["lava"].created == []                           # ввод отменён


@pytest.mark.asyncio
async def test_bad_callback_data_is_rejected(env):
    dp, bot, gcal, session = env
    for data in ("lava_pay:session:USD:1", "lava_pay:course:RUB:5",
                 "lava_pay:session:RUB:0", "lava_pay:xxx:RUB:0"):
        await press(dp, bot, data)
    assert dp["lava"].created == []


@pytest.mark.asyncio
async def test_old_crypto_buttons_explain_instead_of_silence(env):
    dp, bot, gcal, session = env
    await press(dp, bot, "pay_crypto:1")
    await press(dp, bot, "pay_back:1")
    assert sum("криптовалютой больше недоступна" in t for t in _alerts(session)) == 2


@pytest.mark.asyncio
async def test_concurrent_confirmations_create_one_event(env):
    """Кнопка «Я оплатил(а)» и фоновый проход могут подтвердить одну запись
    одновременно: переход в confirmed атомарный, событие ровно одно."""
    import asyncio
    from handlers.booking import finalize_booking
    dp, bot, gcal, session = env
    bid = await _hold(dp, bot, session)
    results = await asyncio.gather(finalize_booking(gcal, bid, ("held",)),
                                   finalize_booking(gcal, bid, ("held",)))
    assert sum(r is not None for r in results) == 1
    assert len(gcal.events) == 1


@pytest.mark.asyncio
async def test_late_payment_close_to_session_is_not_a_false_conflict(env):
    """Холд истёк, до сессии меньше BOOKING_LEAD_HOURS: новым клиентам такой
    слот уже не показывают, но заплатившему за него — подтверждаем."""
    from zoneinfo import ZoneInfo
    dp, bot, gcal, session = env
    prague = ZoneInfo("Europe/Prague")
    now = datetime(2026, 11, 16, 10, 30, tzinfo=prague).astimezone(timezone.utc)  # пн
    slot = datetime(2026, 11, 16, 12, 0, tzinfo=prague).astimezone(timezone.utc)   # +1.5 ч
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="held",
                    held_until=now - timedelta(minutes=10))
        s.add(b)
        await s.commit()
        p = Payment(telegram_id=CLIENT_ID, product="session", booking_id=b.id,
                    invoice_id="inv_late", currency="RUB", amount=5000, email=EMAIL,
                    status="new", created_at=now - timedelta(minutes=20))
        s.add(p)
        await s.commit()
        bid = b.id
    dp["lava"].statuses["inv_late"] = "completed"
    await _pass(dp, bot, gcal, now=now)
    assert (await _booking(bid)).status == "confirmed"


def _consent_screen(session):
    last = _last_edit(session)
    cbs = [b.get("callback_data", "") for row in last["reply_markup"]["inline_keyboard"]
           for b in row]
    return last["text"], [c for c in cbs if c.startswith("lava_ok:")]


@pytest.mark.asyncio
async def test_no_invoice_without_separate_consents(env):
    """Оферта п. 7.2.1: два подтверждения, каждое своей кнопкой, до счёта."""
    dp, bot, gcal, session = env
    await _save_email()
    bid = await _hold(dp, bot, session)
    await press(dp, bot, f"lava_pay:session:RUB:{bid}")
    text, oks = _consent_screen(session)
    assert "явное согласие" in text and "14 дней" in text
    assert oks == [f"lava_ok:health:session:RUB:{bid}", f"lava_ok:waiver:session:RUB:{bid}"]
    assert dp["lava"].created == []

    await press(dp, bot, oks[0])                     # только первый пункт
    text, oks = _consent_screen(session)
    assert oks == [f"lava_ok:waiver:session:RUB:{bid}"]
    assert dp["lava"].created == []
    async with get_session() as s:
        assert (await s.get(User, CLIENT_ID)).health_consent_at is not None

    await press(dp, bot, oks[0])                     # второй — и сразу счёт
    assert len(dp["lava"].created) == 1
    async with get_session() as s:
        p = (await s.execute(select(Payment))).scalar_one()
    assert p.waiver_at is not None


@pytest.mark.asyncio
async def test_health_once_waiver_per_order(env):
    dp, bot, gcal, session = env
    await _save_email()
    bid = await _hold(dp, bot, session)
    await _pay(dp, bot, session, f"lava_pay:session:RUB:{bid}")
    # другой заказ (курс): согласие о состоянии уже есть, про 14 дней — снова
    await press(dp, bot, "lava_pay:course:RUB:0")
    text, oks = _consent_screen(session)
    assert oks == ["lava_ok:waiver:course:RUB:0"]
    assert "явное согласие" not in text


@pytest.mark.asyncio
async def test_game_needs_only_waiver(env):
    dp, bot, gcal, session = env
    await _save_email()
    await press(dp, bot, "lava_pay:game:RUB:0")
    _, oks = _consent_screen(session)
    assert oks == ["lava_ok:waiver:game:RUB:0"]


@pytest.mark.asyncio
async def test_stale_waiver_is_asked_again(env, monkeypatch):
    import handlers.payments as hp
    dp, bot, gcal, session = env
    await _save_email()
    await _pay(dp, bot, session, "lava_pay:game:RUB:0")
    monkeypatch.setattr(hp, "CONSENT_TTL", timedelta(0))
    await press(dp, bot, "lava_pay:game:EUR:0")
    _, oks = _consent_screen(session)
    assert oks == ["lava_ok:waiver:game:EUR:0"]


@pytest.mark.asyncio
async def test_paid_message_confirms_contract_and_waiver(env):
    dp, bot, gcal, session = env
    bid, p = await _invoice(dp, bot, session)
    dp["lava"].statuses[p.invoice_id] = "completed"
    await _pass(dp, bot, gcal)
    msg = [d for n, d in session.log if n == "SendMessage" and d.get("chat_id") == CLIENT_ID
           and "Запись подтверждена" in (d.get("text") or "")][-1]
    assert "Публичной оферты" in msg["text"] and "до истечения 14 дней" in msg["text"]
    assert msg["link_preview_options"]["is_disabled"] is True
