import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import ErrorEvent

from database import close_db, init_db
from followup import followup_loop
from handlers import setup_routers
from middlewares import (
    CallbackSafetyMiddleware,
    CommandCleanupMiddleware,
    EventLoggingMiddleware,
)

load_dotenv()


def resolve_admin_ids(admin_ids_raw: str, owner_raw: str | None = "") -> list[int]:
    """ADMIN_IDS (через запятую) + OWNER_CHAT_ID (личка эксперта, всегда админ).

    OWNER_CHAT_ID добавляется к списку админов независимо от ADMIN_IDS — так
    уведомления о записи/оплате и кнопки подтверждения доходят до Ланы в личку,
    даже если ADMIN_IDS настроен на кого-то ещё."""
    ids = [int(x) for x in admin_ids_raw.replace(" ", "").split(",") if x]
    owner = (owner_raw or "").strip()
    if owner:
        owner_id = int(owner)
        if owner_id not in ids:
            ids.append(owner_id)
    return ids


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    bot_token = os.environ["BOT_TOKEN"]
    # ADMIN_IDS=123,456 (через запятую); ADMIN_ID поддерживается для совместимости.
    # OWNER_CHAT_ID — личка эксперта, всегда попадает в админы (см. resolve_admin_ids).
    admin_ids_raw = os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID", "")
    admin_ids = resolve_admin_ids(admin_ids_raw, os.environ.get("OWNER_CHAT_ID", ""))
    if not admin_ids:
        raise RuntimeError("Set ADMIN_IDS or OWNER_CHAT_ID env var (telegram ids)")
    database_url = os.environ["DATABASE_URL"]

    import booking_config
    from google_calendar import GoogleCalendar

    bcfg = booking_config.load()
    gcal = GoogleCalendar.from_env()

    await init_db(database_url)

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.callback_query.outer_middleware(CallbackSafetyMiddleware())
    dp.callback_query.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(CommandCleanupMiddleware())
    dp.include_router(setup_routers())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logging.exception("Unhandled error while processing update: %s", event.exception)
        return True

    followup_task = asyncio.create_task(followup_loop(bot))
    try:
        await dp.start_polling(bot, admin_ids=admin_ids, booking_config=bcfg, gcal=gcal)
    finally:
        followup_task.cancel()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
