import asyncio
import logging
import os
import sys

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from database import close_db, init_db
from handlers import setup_routers

load_dotenv()


async def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stdout,
    )

    bot_token = os.environ["BOT_TOKEN"]
    admin_id = int(os.environ["ADMIN_ID"])
    database_url = os.environ["DATABASE_URL"]

    await init_db(database_url)

    bot = Bot(
        token=bot_token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.include_router(setup_routers())

    try:
        await dp.start_polling(bot, admin_id=admin_id)
    finally:
        await close_db()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
