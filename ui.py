import logging

from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


async def delete_safe(bot, chat_id: int, message_id: int) -> None:
    """Удалить сообщение, не падая на ошибке (старше 48ч, уже удалено, нет прав)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        logger.debug("delete_safe: не удалил %s/%s", chat_id, message_id)


async def edit_screen(bot, chat_id: int, message_id: int, text: str,
                      reply_markup=None) -> None:
    """Отредактировать «экран», глотая «not modified»/«to edit not found» и пр."""
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )
    except TelegramAPIError:
        logger.debug("edit_screen: не отредактировал %s/%s", chat_id, message_id)
