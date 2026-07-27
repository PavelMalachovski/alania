import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from ui import delete_safe, edit_screen


class BoomBot:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []
    async def delete_message(self, chat_id, message_id):
        self.calls.append(("delete", chat_id, message_id))
        raise self.exc
    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.calls.append(("edit", chat_id, message_id, text))
        raise self.exc


class OkBot:
    def __init__(self):
        self.calls = []
    async def delete_message(self, chat_id, message_id):
        self.calls.append(("delete", chat_id, message_id))
    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.calls.append(("edit", chat_id, message_id, text))


def _bad(msg):
    from aiogram.methods.base import TelegramMethod
    return TelegramBadRequest(method=None, message=msg)


@pytest.mark.asyncio
async def test_delete_safe_swallows_errors():
    bot = BoomBot(TelegramAPIError(method=None, message="too old"))
    await delete_safe(bot, 1, 2)   # не должно бросить
    assert bot.calls == [("delete", 1, 2)]


@pytest.mark.asyncio
async def test_edit_screen_swallows_not_modified():
    bot = BoomBot(_bad("message is not modified"))
    await edit_screen(bot, 1, 2, "text")   # не должно бросить
    assert bot.calls[0][0] == "edit"


@pytest.mark.asyncio
async def test_edit_screen_passes_through_on_ok():
    bot = OkBot()
    await edit_screen(bot, 5, 6, "hello", reply_markup=None)
    assert bot.calls == [("edit", 5, 6, "hello")]
