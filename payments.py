"""Автоподтверждение оплат lava.top: фоновый опрос статуса счетов.

Вебхуков нет (бот на polling, публичного адреса нет) — статус каждого
неоплаченного счёта бот спрашивает сам: первый час на каждом проходе
(POLL_INTERVAL), потом раз в SLOW_EVERY, после GIVE_UP_AFTER перестаёт
(expired). Кнопка «✓ Я оплатил(а)» на экране счёта проверяет сразу, не
дожидаясь прохода.

Одна и та же оплата может прийти одновременно из прохода и из кнопки:
переход счёта в completed/failed — атомарный UPDATE … WHERE status IN
pending, обрабатывает его ровно тот, чей UPDATE сработал."""

import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, html
from aiogram.exceptions import TelegramAPIError
from sqlalchemy import select, update

from booking_config import BookingConfig
from database import Booking, Payment, get_session
from formatting import format_slot_human
from google_calendar import GoogleCalendar
from handlers.booking import (
    BOOKING_CONFIRMED_TEXT,
    _load_free,
    _notify_admins,
    client_line_for,
    finalize_booking,
)
from keyboards.inline import lead_done_kb
from lava import COMPLETED, FAILED, PENDING, LavaClient, LavaError
from ui import delete_safe

logger = logging.getLogger(__name__)

# expired — счёт, который опрос бросил (GIVE_UP_AFTER). Кнопка «✓ Я оплатил(а)»
# его всё равно проверяет: заплатить могли и позже.
_CLAIMABLE = PENDING + ("expired",)

POLL_INTERVAL = 20                      # секунд между проходами
FAST_WINDOW = timedelta(hours=1)        # первый час — на каждом проходе
SLOW_EVERY = timedelta(minutes=10)      # дальше — не чаще раза в 10 минут
GIVE_UP_AFTER = timedelta(hours=48)     # потом перестаём опрашивать

PRODUCT_TITLES = {
    "session": "Личная сессия",
    "course": "Курс-практикум «ВЗЛОМАЙ РЕАЛЬНОСТЬ»",
    "game": "VECHNOST — игра для пар",
}
_CURRENCY_SIGN = {"RUB": "₽", "EUR": "€", "USD": "$"}


def amount_label(amount: float, currency: str) -> str:
    """5000 ₽ / 50 € / 12.5 €."""
    value = f"{amount:g}" if amount != int(amount) else f"{int(amount)}"
    return f"{value} {_CURRENCY_SIGN.get(currency, currency)}"


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _send(bot: Bot, chat_id: int, text: str, reply_markup=None) -> None:
    try:
        await bot.send_message(chat_id, text, reply_markup=reply_markup)
    except TelegramAPIError:
        logger.warning("Сообщение об оплате не доставлено %s", chat_id)


async def _claim(payment_id: int, new_status: str) -> bool:
    """Перевести счёт из pending/expired в new_status. False — уже обработан."""
    async with get_session() as session:
        res = await session.execute(
            update(Payment)
            .where(Payment.id == payment_id, Payment.status.in_(_CLAIMABLE))
            .values(status=new_status)
            .execution_options(synchronize_session=False)
        )
        await session.commit()
    return res.rowcount == 1


async def check_payment(bot: Bot, admin_ids: list[int], gcal: GoogleCalendar,
                        cfg: BookingConfig, lava: LavaClient, payment_id: int,
                        now: datetime | None = None) -> str:
    """Спросить lava.top о счёте и обработать результат. Возвращает статус
    счёта после проверки: pending / completed / failed / cancelled / …"""
    now = now or datetime.now(timezone.utc)
    async with get_session() as session:
        payment = await session.get(Payment, payment_id)
        if payment is None:
            return "missing"
        if payment.status not in _CLAIMABLE:
            return payment.status
        invoice_id = payment.invoice_id
        payment.checked_at = now
        await session.commit()

    try:
        status = await lava.invoice_status(invoice_id)
    except LavaError:
        logger.warning("lava.top: не узнал статус счёта %s", invoice_id, exc_info=True)
        return "pending"

    if status == COMPLETED:
        if await _claim(payment_id, COMPLETED):
            await _on_completed(bot, admin_ids, gcal, cfg, payment_id, now)
        return COMPLETED
    if status in FAILED:
        if await _claim(payment_id, status):
            await _on_failed(bot, payment_id)
        return status
    return "pending"


async def _on_completed(bot, admin_ids, gcal, cfg, payment_id: int, now: datetime) -> None:
    async with get_session() as session:
        p = await session.get(Payment, payment_id)
    # экран счёта с кнопкой «Оплатить» больше не нужен — иначе по нему
    # можно заплатить второй раз
    if p.message_id:
        await delete_safe(bot, p.telegram_id, p.message_id)
    money = amount_label(p.amount, p.currency)
    email = html.quote(p.email)  # ввёл сам клиент, а сообщения — HTML
    who = await client_line_for(p.telegram_id)

    if p.product != "session":
        title = PRODUCT_TITLES.get(p.product, p.product)
        await _send(
            bot, p.telegram_id,
            "<b>✦ Оплата прошла, спасибо!</b> 🤍\n\n"
            f"lava.top пришлёт доступ к «{title}» на <b>{email}</b> — "
            "загляни в почту (и в папку «Спам», если письма нет).",
            reply_markup=lead_done_kb(),
        )
        await _notify_admins(
            bot, admin_ids,
            "🛍 <b>Покупка через lava.top</b>\n\n"
            f"<b>Продукт:</b> {title}\n<b>Сумма:</b> {money}\n"
            f"<b>Email:</b> {email}\n{who}",
        )
        return

    outcome, slot, sync_failed = await _settle_booking(gcal, cfg, p.booking_id, now)
    slot_text = format_slot_human(slot) if slot else "—"
    if outcome == "confirmed":
        await _send(bot, p.telegram_id, BOOKING_CONFIRMED_TEXT.format(slot=slot_text),
                    reply_markup=lead_done_kb())
        warn = "\n\n⚠️ Событие в календаре не создалось — оформи вручную." if sync_failed else ""
        await _notify_admins(
            bot, admin_ids,
            "💳 <b>Оплата через lava.top — запись подтверждена</b>\n\n"
            f"<b>Слот:</b> {slot_text}\n<b>Сумма:</b> {money}\n"
            f"<b>Email:</b> {email}\n{who}{warn}",
        )
    elif outcome == "conflict":
        await _send(
            bot, p.telegram_id,
            "<b>✦ Оплата получена</b> 🤍\n\n"
            f"Но пока шла оплата, время {slot_text} успели занять. Лана "
            "свяжется с тобой и подберёт другое время.",
            reply_markup=lead_done_kb(),
        )
        await _notify_admins(
            bot, admin_ids,
            "⚠️ <b>Оплата пришла, а слот уже занят</b>\n\n"
            f"Бронь истекла до оплаты, и слот {slot_text} успели занять. "
            "Свяжись с клиентом: другое время или возврат.\n\n"
            f"<b>Сумма:</b> {money}\n<b>Email:</b> {email}\n{who}",
        )
    else:  # already — запись уже подтверждена/отменена (двойная оплата и т.п.)
        await _send(
            bot, p.telegram_id,
            "<b>✦ Оплата получена</b> 🤍\n\nЛана свяжется с тобой.",
            reply_markup=lead_done_kb(),
        )
        await _notify_admins(
            bot, admin_ids,
            "⚠️ <b>Лишняя оплата по записи</b>\n\n"
            f"Запись на {slot_text} уже была обработана, а по ней пришла ещё "
            "одна оплата. Проверь и при необходимости верни деньги.\n\n"
            f"<b>Сумма:</b> {money}\n<b>Email:</b> {email}\n{who}",
        )


async def _settle_booking(gcal: GoogleCalendar, cfg: BookingConfig,
                          booking_id: int | None, now: datetime):
    """Оплаченная запись → (confirmed | conflict | already, слот, sync_failed).

    Пока холд жив, слот за клиентом — подтверждаем сразу. Если холд истёк
    (заплатили поздно), слот мог уйти другому: подтверждаем, только если он
    всё ещё свободен, иначе paid_conflict и Лана решает вручную. Google
    недоступен — проверить нельзя, тоже конфликт: лучше спросить Лану, чем
    записать двоих на одно время."""
    async with get_session() as session:
        booking = await session.get(Booking, booking_id) if booking_id else None
    if booking is None:
        return "already", None, False
    slot = _as_utc(booking.slot_start)
    if booking.status not in ("held", "pay_claimed"):
        return "already", slot, False

    held_until = _as_utc(booking.held_until)
    if booking.status == "held" and (held_until is None or held_until <= now):
        try:
            still_free = slot in await _load_free(gcal, cfg, now=now, lead=timedelta(0))
        except Exception:
            logger.exception("Google недоступен при проверке слота оплаты %s", booking_id)
            still_free = False
        if not still_free:
            async with get_session() as session:
                await session.execute(
                    update(Booking)
                    .where(Booking.id == booking_id, Booking.status == "held")
                    .values(status="paid_conflict")
                    .execution_options(synchronize_session=False)
                )
                await session.commit()
            return "conflict", slot, False

    done = await finalize_booking(gcal, booking_id, ("held", "pay_claimed"))
    if done is None:
        return "already", slot, False
    slot, _user_id, sync_failed = done
    return "confirmed", slot, sync_failed


async def _on_failed(bot: Bot, payment_id: int) -> None:
    async with get_session() as session:
        p = await session.get(Payment, payment_id)
    await _send(
        bot, p.telegram_id,
        "Оплата не прошла 🤍 Чтобы попробовать ещё раз, нажми «⇦ Назад» на "
        "экране оплаты и выбери валюту заново — или напиши Лане в личку.",
    )


async def payments_pass(bot: Bot, admin_ids: list[int], gcal: GoogleCalendar,
                        cfg: BookingConfig, lava: LavaClient,
                        now: datetime | None = None) -> int:
    """Один проход по неоплаченным счетам; возвращает число проверенных."""
    now = now or datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Payment.id, Payment.created_at, Payment.checked_at)
            .where(Payment.status.in_(PENDING))
        )).all()
    checked = 0
    for pid, created_at, checked_at in rows:
        age = now - _as_utc(created_at)
        if age > GIVE_UP_AFTER:
            await _claim(pid, "expired")
            continue
        last = _as_utc(checked_at)
        if age > FAST_WINDOW and last is not None and now - last < SLOW_EVERY:
            continue
        await check_payment(bot, admin_ids, gcal, cfg, lava, pid, now)
        checked += 1
    return checked


async def payments_loop(bot: Bot, admin_ids: list[int], gcal: GoogleCalendar,
                        cfg: BookingConfig, lava: LavaClient) -> None:
    while True:
        try:
            await payments_pass(bot, admin_ids, gcal, cfg, lava)
        except Exception:
            logger.exception("Payments pass failed")
        await asyncio.sleep(POLL_INTERVAL)
