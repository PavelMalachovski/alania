import logging
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from database import Booking, get_session
from keyboards.inline import (
    admin_confirm_pay_kb,
    booking_days_kb,
    booking_pay_kb,
    booking_times_kb,
)

router = Router()
logger = logging.getLogger(__name__)

TZ = ZoneInfo("Europe/Prague")
SLOT_TIMES = ["12:00", "14:00", "16:00"]
HORIZON_DAYS = 14  # показываем слоты на две недели вперёд
WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def day_label(d: date) -> str:
    return f"{WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}"


def available_days(now: datetime | None = None) -> list[date]:
    """Рабочие дни (пн–пт) на две недели вперёд; сегодня — только если ещё есть будущие слоты."""
    now = now or datetime.now(TZ)
    days = []
    for offset in range(HORIZON_DAYS):
        d = now.date() + timedelta(days=offset)
        if d.weekday() >= 5:  # сб/вс
            continue
        if offset == 0 and not _future_times(now):
            continue
        days.append(d)
    return days


def _future_times(now: datetime) -> list[str]:
    return [t for t in SLOT_TIMES if t > now.strftime("%H:%M")]


async def free_times(d: date, now: datetime | None = None) -> list[str]:
    now = now or datetime.now(TZ)
    async with get_session() as session:
        taken = set(
            (
                await session.execute(
                    select(Booking.slot_time).where(Booking.slot_date == d)
                )
            ).scalars()
        )
    times = _future_times(now) if d == now.date() else SLOT_TIMES
    return [t for t in times if t not in taken]


# старый callback consultation_pay остаётся рабочим в уже отправленных сообщениях
@router.callback_query(F.data.in_({"booking_start", "consultation_pay"}))
async def cb_booking_start(callback: CallbackQuery) -> None:
    days = available_days()
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "<b>✦ Запись на консультацию</b>\n\n"
        "Сессии проходят с понедельника по пятницу в 12:00, 14:00 и 16:00 "
        "(время Прага / CET).\n\n"
        "Выбери удобный день ⇩",
        reply_markup=booking_days_kb([(day_label(d), d.isoformat()) for d in days]),
    )


@router.callback_query(F.data.startswith("book_day:"))
async def cb_book_day(callback: CallbackQuery) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        return
    if d not in available_days():
        await callback.answer("Этот день уже недоступен", show_alert=True)
        return
    times = await free_times(d)
    if not times:
        await callback.answer("На этот день всё занято 🤍 Выбери другой", show_alert=True)
        return
    await callback.message.edit_text(
        f"<b>✦ {day_label(d)}</b>\n\nВыбери время ⇩",
        reply_markup=booking_times_kb(d.isoformat(), times),
    )


@router.callback_query(F.data.startswith("book_slot:"))
async def cb_book_slot(
    callback: CallbackQuery, bot: Bot, admin_ids: list[int]
) -> None:
    try:
        _, iso, t = callback.data.split(":", 2)
        d = date.fromisoformat(iso)
    except ValueError:
        return
    if t not in SLOT_TIMES or d not in available_days() or t not in await free_times(d):
        await callback.answer("Этот слот уже заняли 🤍 Выбери другой", show_alert=True)
        return

    booking = Booking(telegram_id=callback.from_user.id, slot_date=d, slot_time=t)
    try:
        async with get_session() as session:
            session.add(booking)
            await session.commit()
            booking_id = booking.id
    except IntegrityError:
        await callback.answer("Этот слот только что заняли 🤍 Выбери другой", show_alert=True)
        return

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        f"<b>✦ Твой слот: {day_label(d)} в {t}</b> (время Прага / CET)\n\n"
        "● Стоимость: 111 € / 11111 ₽\n\n"
        "Чтобы завершить запись, оплати удобным способом ⇩\n"
        "После оплаты нажми «✓ Я оплатил(а)» — Лана подтвердит запись, "
        "и тебе придёт сообщение.",
        reply_markup=booking_pay_kb(booking_id),
    )

    await _notify_admins(
        bot,
        admin_ids,
        "📅 <b>Новая запись на слот!</b>\n\n"
        f"<b>Слот:</b> {day_label(d)} в {t}\n"
        f"{_client_line(callback)}\n\n"
        "Ждём оплату — придёт отдельное уведомление.",
    )


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(callback: CallbackQuery, bot: Bot, admin_ids: list[int]) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            return
        if booking.status != "new":
            await callback.answer("Уже принято 🤍 Ждём подтверждения Ланы", show_alert=True)
            return
        booking.status = "pay_claimed"
        await session.commit()
        d, t = booking.slot_date, booking.slot_time

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "🤍 Принято! Проверяем оплату.\n\n"
        f"Как только Лана подтвердит, тебе придёт сообщение о записи "
        f"на <b>{day_label(d)} в {t}</b>."
    )

    await _notify_admins(
        bot,
        admin_ids,
        "💳 <b>Клиент сообщил об оплате слота</b>\n\n"
        f"<b>Слот:</b> {day_label(d)} в {t}\n"
        f"{_client_line(callback)}\n\n"
        "Проверь оплату в Tribute и подтверди ⇩",
        reply_markup=admin_confirm_pay_kb(booking_id),
    )


def _client_line(callback: CallbackQuery) -> str:
    user = callback.from_user
    username = f"@{user.username}" if user.username else "нет username"
    return (
        f"<b>Клиент:</b> {html.quote(user.full_name)} — {username} "
        f'(<a href="tg://user?id={user.id}">открыть</a>, id {user.id})'
    )


async def _notify_admins(
    bot: Bot, admin_ids: list[int], text: str, reply_markup=None
) -> None:
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
        except TelegramAPIError:
            logger.warning("Failed to notify admin %s", admin_id)
