"""Рассылка Ланы: любой тип контента + пересборка низа чата.

Сообщение Ланы должно оказаться НАД 🤍-якорем клавиатуры и приветственным
экраном, поэтому после доставки бот пересылает якорь и меню заново.

Отдельно проверяется живучесть цикла: ни заблокировавший бота человек, ни
падение при пересборке низа чата не должны обрывать рассылку для остальных.
"""
from datetime import datetime

import pytest
from aiogram.exceptions import TelegramForbiddenError
from aiogram.types import Chat, Message, Update, User as TgUser, Voice

import handlers.admin as admin
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
OTHER_ID = CLIENT_ID + 1


@pytest.fixture(autouse=True)
def _no_delay(monkeypatch):
    """Пауза между получателями нужна против flood control, в тестах — только время."""
    monkeypatch.setattr(admin, "BROADCAST_DELAY", 0)


async def _send(dp, bot, **kwargs):
    upd = Update(update_id=1, message=Message(
        message_id=42, date=datetime.now(), from_user=_ADMIN,
        chat=Chat(id=ADMIN_ID, type="private"), **kwargs))
    await dp.feed_update(bot, upd)


async def _add_client(telegram_id=CLIENT_ID, username="marina", full_name="Марина"):
    async with get_session() as s:
        s.add(User(telegram_id=telegram_id, username=username, full_name=full_name))
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


def _admin_texts(session):
    return " ".join(d.get("text") or "" for _, d in session.log
                    if d.get("chat_id") == ADMIN_ID)


def _copy_targets(session):
    return {d.get("chat_id") for name, d in session.log
            if name == "CopyMessage" and d.get("chat_id") != ADMIN_ID}


async def _run_broadcast(dp, bot, session):
    await _send(dp, bot, text="/broadcast")
    await _send(dp, bot, text="Привет 🤍")
    session.log.clear()
    await press(dp, bot, "broadcast_confirm", user=_ADMIN, chat_id=ADMIN_ID)


@pytest.mark.asyncio
async def test_blocked_user_does_not_stop_broadcast(env):
    """Заблокировавший бота считается отдельно, остальные получают сообщение."""
    dp, bot, gcal, session = env
    await _add_client()
    await _add_client(OTHER_ID, "olga", "Ольга")

    original = session.make_request

    async def blocked_for_client(bot_, method, timeout=None):
        data = method.model_dump(exclude_none=True)
        if type(method).__name__ == "CopyMessage" and data.get("chat_id") == CLIENT_ID:
            raise TelegramForbiddenError(method=method,
                                         message="bot was blocked by the user")
        return await original(bot_, method, timeout)

    session.make_request = blocked_for_client
    await _run_broadcast(dp, bot, session)

    assert _copy_targets(session) == {OTHER_ID}
    texts = _admin_texts(session)
    assert "Доставлено: 1" in texts
    assert "Заблокировали бота или удалились: 1" in texts


@pytest.mark.asyncio
async def test_stale_confirm_button_answers_instead_of_silence(env):
    """После рестарта FSM пуст: кнопка «Отправить» должна честно сказать об этом."""
    dp, bot, gcal, session = env
    await _add_client()
    await press(dp, bot, "broadcast_confirm", user=_ADMIN, chat_id=ADMIN_ID)

    alerts = [d.get("text") for name, d in session.log
              if name == "AnswerCallbackQuery" and d.get("text")]
    assert any("/broadcast" in (t or "") for t in alerts)
    assert not _copy_targets(session)


@pytest.mark.asyncio
async def test_restore_failure_does_not_break_delivery(env, monkeypatch):
    """Падение пересборки низа чата (например, БД) не обрывает рассылку."""
    dp, bot, gcal, session = env
    await _add_client()
    await _add_client(OTHER_ID, "olga", "Ольга")

    async def boom(*args, **kwargs):
        raise RuntimeError("settings недоступны")

    monkeypatch.setattr(admin, "reset_keyboard", boom)
    await _run_broadcast(dp, bot, session)

    assert _copy_targets(session) == {CLIENT_ID, OTHER_ID}
    assert "Доставлено: 2" in _admin_texts(session)
