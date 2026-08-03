"""Рассылка Ланы: любой тип контента + пересборка низа чата.

Сообщение Ланы должно оказаться НАД 🤍-якорем клавиатуры и приветственным
экраном, поэтому после доставки бот пересылает якорь и меню заново.
"""
from datetime import datetime

import pytest
from aiogram.types import Chat, Message, Update, User as TgUser, Voice

from database import User, get_session
from handlers.start import MAIN_MENU_TEXT
from tests.test_booking_flow import (  # noqa: F401 — env тянет фикстуру _dp
    ADMIN_ID,
    CLIENT_ID,
    env,
    press,
)
from ui import ANCHOR_TEXT

_ADMIN = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")


async def _send(dp, bot, **kwargs):
    upd = Update(update_id=1, message=Message(
        message_id=42, date=datetime.now(), from_user=_ADMIN,
        chat=Chat(id=ADMIN_ID, type="private"), **kwargs))
    await dp.feed_update(bot, upd)


async def _add_client():
    async with get_session() as s:
        s.add(User(telegram_id=CLIENT_ID, username="marina", full_name="Марина"))
        await s.commit()


def _client_calls(session):
    return [name for name, d in session.log if d.get("chat_id") == CLIENT_ID]


def _client_texts(session):
    return [d.get("text") for _, d in session.log if d.get("chat_id") == CLIENT_ID]


@pytest.mark.asyncio
async def test_voice_broadcast_lands_above_heart_and_menu(env):
    dp, bot, gcal, session = env
    await _add_client()
    await _send(dp, bot, text="/broadcast")
    await _send(dp, bot, voice=Voice(file_id="v1", file_unique_id="u1", duration=7))
    session.log.clear()
    await press(dp, bot, "broadcast_confirm", user=_ADMIN, chat_id=ADMIN_ID)

    calls = _client_calls(session)
    assert calls[0] == "CopyMessage"          # сначала голосовое от Ланы
    texts = _client_texts(session)
    assert ANCHOR_TEXT in texts               # затем якорь с клавиатурой
    assert MAIN_MENU_TEXT in texts            # и приветственный экран
    assert texts.index(ANCHOR_TEXT) < texts.index(MAIN_MENU_TEXT)


@pytest.mark.asyncio
async def test_broadcast_reports_delivery(env):
    dp, bot, gcal, session = env
    await _add_client()
    await _send(dp, bot, text="/broadcast")
    await _send(dp, bot, text="Привет 🤍")
    await press(dp, bot, "broadcast_confirm", user=_ADMIN, chat_id=ADMIN_ID)

    admin_texts = " ".join(d.get("text") or "" for _, d in session.log
                           if d.get("chat_id") == ADMIN_ID)
    assert "Доставлено: 1" in admin_texts
