import logging

from aiogram.exceptions import TelegramAPIError, TelegramBadRequest

logger = logging.getLogger(__name__)

# id последнего показанного «экрана» на чат — чтобы новое окно (или команда)
# удаляло предыдущее и в чате не копились устаревшие меню. In-memory: после
# рестарта просто забываем старые окна (уборка косметическая, не критичная).
_last_screen: dict[int, int] = {}


async def delete_safe(bot, chat_id: int, message_id: int) -> None:
    """Удалить сообщение, не падая на ошибке (старше 48ч, уже удалено, нет прав)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        logger.debug("delete_safe: не удалил %s/%s", chat_id, message_id)


def track_screen(chat_id: int, message) -> None:
    """Запомнить сообщение как текущий «экран» чата (id для будущей уборки)."""
    mid = getattr(message, "message_id", None)
    if mid is not None:
        _last_screen[chat_id] = mid


async def clear_screen(bot, chat_id: int) -> None:
    """Удалить ранее показанный экран этого чата (если был) и забыть его."""
    prev = _last_screen.pop(chat_id, None)
    if prev is not None:
        await delete_safe(bot, chat_id, prev)


async def show_screen(bot, chat_id: int, text: str, reply_markup=None):
    """Убрать предыдущее окно чата и показать новое, запомнив его как текущее.
    Используется там, где нужно (пере)установить нижнюю клавиатуру — /start,
    возврат в меню (edit не умеет ставить ReplyKeyboardMarkup)."""
    await clear_screen(bot, chat_id)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    track_screen(chat_id, sent)
    return sent


async def render_screen(bot, chat_id: int, text: str, reply_markup=None):
    """Показать экран, редактируя единое окно чата на месте. Сообщение не
    пересоздаётся — поэтому постоянная нижняя клавиатура (её держит первое
    сообщение с ReplyKeyboardMarkup) не теряется при переходах между разделами.
    Если окна нет или его нельзя отредактировать — шлём новое и запоминаем."""
    mid = _last_screen.get(chat_id)
    if mid is not None:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=mid, reply_markup=reply_markup
            )
            return mid
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return mid           # тот же экран — оставляем как есть
            _last_screen.pop(chat_id, None)   # окно удалено/непригодно
        except TelegramAPIError:
            _last_screen.pop(chat_id, None)
    sent = await bot.send_message(chat_id, text, reply_markup=reply_markup)
    _last_screen[chat_id] = sent.message_id
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
