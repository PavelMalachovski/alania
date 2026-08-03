"""Экран оплаты в криптовалюте: адрес, кнопка копирования, возврат и «оплатил».

Харнес (FakeSession/FakeGCal/env/press/...) переиспользуется из
test_booking_flow.py — см. комментарий в conftest.py про один Dispatcher
на процесс.
"""
import pytest
from sqlalchemy import select

from database import Booking, get_session
from formatting import CRYPTO_ADDRESS
from tests.test_booking_flow import (  # noqa: F401 — env тянет фикстуру _dp
    ADMIN_ID,
    CLIENT_ID,
    env,
    find_cb,
    last_kb,
    press,
)


async def _hold_slot(dp, bot, session):
    """Довести клиента до экрана оплаты, вернуть callback_data крипто-кнопки."""
    await press(dp, bot, "booking_start")
    await press(dp, bot, find_cb(session, "book_day:"))
    await press(dp, bot, find_cb(session, "book_slot:"))
    return find_cb(session, "pay_crypto:")


def _last_text(session, chat_id=CLIENT_ID):
    return next(d for n, d in reversed(session.log)
                if d.get("chat_id") == chat_id and d.get("text"))["text"]


@pytest.mark.asyncio
async def test_pay_screen_offers_crypto(env):
    dp, bot, gcal, session = env
    assert await _hold_slot(dp, bot, session) is not None


@pytest.mark.asyncio
async def test_crypto_screen_shows_address_and_copy_button(env):
    dp, bot, gcal, session = env
    await press(dp, bot, await _hold_slot(dp, bot, session))
    assert CRYPTO_ADDRESS in _last_text(session)
    copy_buttons = [b for row in last_kb(session) for b in row if b.get("copy_text")]
    assert copy_buttons and copy_buttons[0]["copy_text"]["text"] == CRYPTO_ADDRESS


@pytest.mark.asyncio
async def test_back_returns_to_pay_screen(env):
    dp, bot, gcal, session = env
    await press(dp, bot, await _hold_slot(dp, bot, session))
    await press(dp, bot, find_cb(session, "pay_back:"))
    assert "Стоимость" in _last_text(session)
    assert find_cb(session, "pay_crypto:") is not None


@pytest.mark.asyncio
async def test_crypto_paid_claims_slot_and_tells_admin_the_method(env):
    dp, bot, gcal, session = env
    await press(dp, bot, await _hold_slot(dp, bot, session))
    await press(dp, bot, find_cb(session, "paid_crypto:"))

    async with get_session() as s:
        b = (await s.execute(select(Booking))).scalar_one()
    assert b.status == "pay_claimed"
    assert gcal.events == {}                     # событие только на подтверждении

    admin_text = _last_text(session, chat_id=ADMIN_ID)
    assert "USDT" in admin_text and "Tribute" not in admin_text
    flat = [x.get("callback_data", "") for row in last_kb(session, chat_id=ADMIN_ID)
            for x in row]
    assert any(c.startswith("confirm_pay:") for c in flat)


@pytest.mark.asyncio
async def test_crypto_screen_refuses_foreign_booking(env):
    dp, bot, gcal, session = env
    crypto_cb = await _hold_slot(dp, bot, session)
    from aiogram.types import User as TgUser
    stranger = TgUser(id=CLIENT_ID + 77, is_bot=False, first_name="Чужой")
    before = len(session.log)
    await press(dp, bot, crypto_cb, user=stranger, chat_id=CLIENT_ID + 77)
    # адрес кошелька чужому не показали
    assert all(CRYPTO_ADDRESS not in (d.get("text") or "")
               for _, d in session.log[before:])
