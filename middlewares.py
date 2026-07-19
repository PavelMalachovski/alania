import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest
from aiogram.types import CallbackQuery, Message, TelegramObject

from database import Event, get_session

logger = logging.getLogger(__name__)


class CallbackSafetyMiddleware(BaseMiddleware):
    """Всегда отвечает на callback (убирает «часики» даже при ошибке в хендлере)
    и гасит TelegramBadRequest от повторного нажатия той же кнопки."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not isinstance(event, CallbackQuery):
            return await handler(event, data)
        try:
            return await handler(event, data)
        except TelegramBadRequest as e:
            if "message is not modified" in str(e):
                return None
            raise
        finally:
            try:
                await event.answer()
            except TelegramAPIError:
                # уже отвечен в хендлере или query устарел — не критично
                pass


class EventLoggingMiddleware(BaseMiddleware):
    """Пишет нажатия кнопок и команды в таблицу events для аналитики воронки."""

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        action: str | None = None
        user_id: int | None = None
        if isinstance(event, CallbackQuery) and event.data:
            action = event.data
            user_id = event.from_user.id
        elif isinstance(event, Message) and event.text and event.text.startswith("/"):
            action = event.text.split()[0]
            user_id = event.from_user.id if event.from_user else None

        if action and user_id:
            try:
                async with get_session() as session:
                    session.add(Event(telegram_id=user_id, action=action[:64]))
                    await session.commit()
            except Exception:
                # аналитика не должна ломать обработку апдейта
                logger.exception("Failed to log event %r for user %s", action, user_id)

        return await handler(event, data)
