import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

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
    """Убрать предыдущее окно чата и показать новое, запомнив его как текущее.
    Используется там, где нужно (пере)установить нижнюю клавиатуру — /start,
    возврат в меню (edit не умеет ставить ReplyKeyboardMarkup)."""
    await clear_screen(bot, chat_id)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    await _set_screen(chat_id, sent.message_id)
    return sent


async def render_screen(bot, chat_id: int, text: str, reply_markup=None, *,
                        send_markup=None):
    """Показать экран, редактируя единое окно чата на месте. Сообщение не
    пересоздаётся — поэтому постоянная нижняя клавиатура (её держит первое
    сообщение с ReplyKeyboardMarkup) не теряется при переходах между разделами.
    Если окна нет или его нельзя отредактировать — шлём новое. `send_markup`
    задаёт reply_markup именно для этого фолбэка-отправки (например, чтобы при
    пересоздании приветствия вернуть нижнюю клавиатуру, которую edit ставить
    не умеет); по умолчанию — тот же `reply_markup`, что и для правки."""
    mid = await _get_screen(chat_id)
    if mid is not None:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=mid, reply_markup=reply_markup
            )
            return mid
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return mid           # тот же экран — оставляем как есть
            await _forget_screen(chat_id)    # окно удалено/непригодно
        except TelegramAPIError:
            await _forget_screen(chat_id)
    markup = send_markup if send_markup is not None else reply_markup
    sent = await bot.send_message(chat_id, text, reply_markup=markup)
    await _set_screen(chat_id, sent.message_id)
    return sent.message_id


async def edit_screen(bot, chat_id: int, message_id: int, text: str,
                      reply_markup=None) -> None:
    """Отредактировать «экран», глотая «not modified»/«to edit not found» и пр."""
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )
    except TelegramAPIError:
        logger.debug("edit_screen: не отредактировал %s/%s", chat_id, message_id)
