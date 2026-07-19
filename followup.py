"""Дожим: пользователь открыл экран консультации, но за час не оставил заявку
и не выбрал слот — бот один раз присылает «могу ли чем-то помочь?»."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select

from database import Booking, Event, Lead, get_session
from keyboards.inline import followup_kb

logger = logging.getLogger(__name__)

FOLLOWUP_DELAY = timedelta(hours=1)
FOLLOWUP_WINDOW = timedelta(hours=48)  # старые клики не трогаем (например, после редеплоя)
CHECK_INTERVAL = 600  # секунд между проверками

FOLLOWUP_TEXT = (
    "○─── ☾ ───○\n\n"
    "Вижу, ты интересовалась консультацией «Точка сборки» 🤍\n\n"
    "Могу ли я чем-то помочь — ответить на вопросы "
    "или подобрать удобное время для сессии?"
)


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def followup_pass(bot: Bot, now: datetime | None = None) -> int:
    """Одна проверка; возвращает число отправленных сообщений."""
    now = now or datetime.now(timezone.utc)
    async with get_session() as session:
        events = (
            await session.execute(
                select(Event.telegram_id, Event.action, Event.created_at).where(
                    Event.action.in_(["consultation", "followup_sent"])
                )
            )
        ).all()
        with_lead = set((await session.execute(select(Lead.telegram_id))).scalars())
        with_booking = set(
            (await session.execute(select(Booking.telegram_id))).scalars()
        )

    already_sent = {e.telegram_id for e in events if e.action == "followup_sent"}
    last_click: dict[int, datetime] = {}
    for e in events:
        if e.action != "consultation":
            continue
        ts = _as_utc(e.created_at)
        if e.telegram_id not in last_click or ts > last_click[e.telegram_id]:
            last_click[e.telegram_id] = ts

    sent = 0
    for user_id, ts in last_click.items():
        if user_id in already_sent or user_id in with_lead or user_id in with_booking:
            continue
        if not (now - FOLLOWUP_WINDOW <= ts <= now - FOLLOWUP_DELAY):
            continue
        try:
            await bot.send_message(user_id, FOLLOWUP_TEXT, reply_markup=followup_kb())
            sent += 1
        except TelegramAPIError:
            logger.info("Followup to %s failed (бот заблокирован?)", user_id)
        # помечаем в любом случае, чтобы не долбить повторно
        async with get_session() as session:
            session.add(Event(telegram_id=user_id, action="followup_sent"))
            await session.commit()
    return sent


async def followup_loop(bot: Bot) -> None:
    while True:
        try:
            await followup_pass(bot)
        except Exception:
            logger.exception("Followup pass failed")
        await asyncio.sleep(CHECK_INTERVAL)
