import pytest
from datetime import datetime
from aiogram.types import Update, Message, Chat, User as TgUser

from tests.test_booking_flow import env, CLIENT_ID  # харнес


async def _send_text(dp, bot, text, mid=7000):
    upd = Update(update_id=mid, message=Message(
        message_id=mid, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text=text))
    await dp.feed_update(bot, upd)


@pytest.mark.asyncio
async def test_start_sets_reply_keyboard(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "/start")
    sends = [d for n, d in session.log if n == "SendMessage" and d.get("chat_id") == CLIENT_ID]
    kb = sends[-1].get("reply_markup", {})
    assert "keyboard" in kb   # ReplyKeyboardMarkup (не inline_keyboard)
    labels = [b["text"] for row in kb["keyboard"] for b in row]
    assert "Записаться на сессию" in labels and "Мои записи" in labels
    assert "О личной работе" in labels and "Задать вопрос Лане" in labels
    assert "🏠 Меню" not in labels   # кнопка «Меню» убрана


@pytest.mark.asyncio
async def test_start_deletes_previous_menu_window(env):
    dp, bot, gcal, session = env
    import ui
    ui._last_screen.pop(CLIENT_ID, None)   # чистый старт (dict глобальный на процесс)
    await _send_text(dp, bot, "/start", mid=7100)
    welcome1_id = session._mid              # id только что показанного меню
    await _send_text(dp, bot, "/start", mid=7101)
    # повторный /start убрал предыдущее окно
    assert any(n == "DeleteMessage" and d.get("message_id") == welcome1_id
               for n, d in session.log)


@pytest.mark.asyncio
async def test_reply_book_opens_calendar_and_deletes_tap(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "Записаться на сессию", mid=7010)
    # тап удалён
    assert any(n == "DeleteMessage" and d.get("message_id") == 7010 for n, d in session.log)
    # показан календарь (есть book_day: или noop в новом сообщении)
    last = [d for n, d in session.log if n == "SendMessage" and d.get("chat_id") == CLIENT_ID][-1]
    cbs = [b.get("callback_data", "") for row in last.get("reply_markup", {}).get("inline_keyboard", []) for b in row]
    assert any(c.startswith("book_day:") for c in cbs) or "noop" in cbs
