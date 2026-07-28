import logging

from aiogram.exceptions import TelegramAPIError

from database import del_setting, get_setting, set_setting

logger = logging.getLogger(__name__)

# id текущего «экрана» на чат храним в таблице settings (key=screen:<chat_id>),
# а не в памяти — чтобы трекинг переживал рестарты. Railway передеплаивает бота
# часто; при in-memory состоянии /start после рестарта не мог удалить прежнее
# приветствие и в чате появлялся дубликат.
def _screen_key(chat_id: int) -> str:
    return f"screen:{chat_id}"


async def _get_screen(chat_id: int) -> int | None:
    raw = await get_setting(_screen_key(chat_id))
    return int(raw) if raw else None


async def _set_screen(chat_id: int, message_id: int) -> None:
    await set_setting(_screen_key(chat_id), str(message_id))


async def _forget_screen(chat_id: int) -> None:
    await del_setting(_screen_key(chat_id))


async def delete_safe(bot, chat_id: int, message_id: int) -> None:
    """Удалить сообщение, не падая на ошибке (старше 48ч, уже удалено, нет прав)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        logger.debug("delete_safe: не удалил %s/%s", chat_id, message_id)


async def clear_screen(bot, chat_id: int) -> None:
    """Удалить текущее окно этого чата (если было) и забыть его. Зовётся из
    middleware при любой команде — чтобы приветствие/раздел не оставались висеть."""
    mid = await _get_screen(chat_id)
    if mid is not None:
        await delete_safe(bot, chat_id, mid)
        await _forget_screen(chat_id)


async def show_screen(bot, chat_id: int, text: str, reply_markup=None):
    """Единое «окно» на чат: удалить предыдущий экран и показать новый
    сообщением, запомнив его. Нажатие любой кнопки/раздела так убирает
    предыдущий экран (приветствие «исчезает», а не копится).

    Почему send, а не edit: сообщение с нижней клавиатурой
    (`ReplyKeyboardMarkup`) нельзя перерисовать в раздел через
    `edit_message_text` — правка не срабатывает. А удаление сообщения нижнюю
    клавиатуру НЕ убирает (она на уровне чата, держится до `ReplyKeyboardRemove`
    или новой клавиатуры), поэтому 7 кнопок остаются видны во всех разделах."""
    await clear_screen(bot, chat_id)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await _set_screen(chat_id, sent.message_id)
    return sent


async def track_screen(chat_id: int, message) -> None:
    """Запомнить уже отправленное сообщение как текущее окно чата — для тех,
    кто шлёт его сам (open_calendar/open_my_bookings), а не через show_screen."""
    mid = getattr(message, "message_id", None)
    if mid is not None:
        await _set_screen(chat_id, mid)


async def edit_screen(bot, chat_id: int, message_id: int, text: str,
                      reply_markup=None) -> None:
    """Отредактировать «экран», глотая «not modified»/«to edit not found» и пр."""
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )
    except TelegramAPIError:
        logger.debug("edit_screen: не отредактировал %s/%s", chat_id, message_id)
