from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message


class IsAdmin(BaseFilter):
    """Пропускает только пользователей из ADMIN_IDS (workflow data admin_ids)."""

    async def __call__(
        self, event: Message | CallbackQuery, admin_ids: list[int]
    ) -> bool:
        return event.from_user is not None and event.from_user.id in admin_ids
