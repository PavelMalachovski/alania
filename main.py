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
from middlewares import CallbackSafetyMiddleware, EventLoggingMiddleware

load_dotenv()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    bot_token = os.environ["BOT_TOKEN"]
    # ADMIN_IDS=123,456 (через запятую); ADMIN_ID поддерживается для совместимости
    admin_ids_raw = os.environ.get("ADMIN_IDS") or os.environ.get("ADMIN_ID", "")
    admin_ids = [int(x) for x in admin_ids_raw.replace(" ", "").split(",") if x]
    if not admin_ids:
        raise RuntimeError("Set ADMIN_IDS env var (comma-separated telegram ids)")
    database_url = os.environ["DATABASE_URL"]

    await init_db(database_url)

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.callback_query.outer_middleware(CallbackSafetyMiddleware())
    dp.callback_query.outer_middleware(EventLoggingMiddleware())
    dp.message.outer_middleware(EventLoggingMiddleware())
    dp.include_router(setup_routers())

    @dp.errors()
    async def on_error(event: ErrorEvent) -> bool:
        logging.exception("Unhandled error while processing update: %s", event.exception)
        return True

    followup_task = asyncio.create_task(followup_loop(bot))
    try:
        await dp.start_polling(bot, admin_ids=admin_ids)
    finally:
        followup_task.cancel()
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
