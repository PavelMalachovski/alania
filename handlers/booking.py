import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select

from booking_config import BookingConfig
from database import Booking, get_session
from formatting import PRICE_TEXT, format_slot_human, TZ_PRAGUE
from google_calendar import GoogleCalendar
from keyboards.inline import (
    admin_confirm_pay_kb,
    booking_days_kb,
    booking_error_kb,
    booking_pay_kb,
    booking_times_kb,
)
from slots import free_slots

router = Router()
logger = logging.getLogger(__name__)
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def day_label(d: date) -> str:
    """Совместимость: handlers/admin.py::cb_confirm_pay ещё импортирует эту
    функцию и читает Booking.slot_date/slot_time (схема этих полей убрана
    в Task 1). Task 6 не трогает admin.py — по плану cb_confirm_pay
    переписывается в Task 7 (переезд на format_slot_human + slot_start,
    добавление reject_pay/create_event). До этого момента символ нужен
    только для того, чтобы `from handlers import setup_routers` не падал
    с ImportError; новым хендлерам этого файла он не нужен."""
    return f"{_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}"


async def _active_holds(session, now: datetime) -> list[datetime]:
    rows = (await session.execute(
        select(Booking.slot_start).where(
            Booking.status == "held", Booking.held_until > now
        )
    )).scalars()
    return [r if r.tzinfo else r.replace(tzinfo=timezone.utc) for r in rows]


async def _user_has_active(session, tg_id: int, now: datetime) -> bool:
    row = (await session.execute(
        select(Booking.id).where(
            Booking.telegram_id == tg_id,
            Booking.status.in_(["confirmed", "pay_claimed"])
            | ((Booking.status == "held") & (Booking.held_until > now)),
        ).limit(1)
    )).first()
    return row is not None


async def _load_free(gcal: GoogleCalendar, cfg: BookingConfig) -> list[datetime]:
    now = datetime.now(timezone.utc)
    horizon_end = now + timedelta(days=cfg.horizon_days)
    busy = await gcal.busy(now, horizon_end)
    async with get_session() as session:
        holds = await _active_holds(session, now)
    return free_slots(
        now, busy, holds,
        work_times=cfg.work_times, work_weekdays=cfg.work_weekdays,
        horizon_days=cfg.horizon_days, lead=cfg.lead, tz=cfg.tz,
    )


@router.callback_query(F.data.in_({"booking_start", "consultation_pay"}))
async def cb_booking_start(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google Calendar недоступен при показе слотов")
        await callback.message.edit_text(
            "○─── ☾ ───○\n\n"
            "Расписание сейчас недоступно 🤍 Попробуй через минуту "
            "или напиши Лане в личку — подберём время вручную.",
            reply_markup=booking_error_kb(),
        )
        return
    if not slots:
        await callback.message.edit_text(
            "○─── ☾ ───○\n\n"
            "Ближайшие две недели заняты 🤍 Напиши Лане в ЛС — "
            "подберём время индивидуально.",
            reply_markup=booking_error_kb(),
        )
        return
    days = sorted({s.astimezone(booking_config.tz).date() for s in slots})
    day_buttons = [
        (f"{_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}", d.isoformat())
        for d in days
    ]
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "<b>✦ Запись на консультацию</b>\n\n"
        "Сессии проходят по будням, время — Прага (в скобках московское).\n\n"
        "Выбери удобный день ⇩",
        reply_markup=booking_days_kb(day_buttons),
    )


@router.callback_query(F.data.startswith("book_day:"))
async def cb_book_day(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял день, выбери заново", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при показе времён")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    day_slots = [s for s in slots if s.astimezone(booking_config.tz).date() == d]
    if not day_slots:
        await callback.answer("На этот день уже нет свободного времени", show_alert=True)
        return
    time_buttons = [(format_slot_human(s).split("·", 1)[1].strip(), s.isoformat())
                    for s in day_slots]
    await callback.message.edit_text(
        f"<b>✦ {_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}</b>\n\n"
        "Выбери время ⇩",
        reply_markup=booking_times_kb(d.isoformat(), time_buttons),
    )


@router.callback_query(F.data.startswith("book_slot:"))
async def cb_book_slot(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        slot = datetime.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял слот, выбери заново", show_alert=True)
        return
    slot = slot.astimezone(timezone.utc)
    now = datetime.now(timezone.utc)

    # слот всё ещё свободен?
    try:
        free = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при бронировании")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    if slot not in free:
        await callback.answer("Это время только что заняли 🤍 Выбери другое", show_alert=True)
        return

    async with get_session() as session:
        if await _user_has_active(session, callback.from_user.id, now):
            await callback.answer(
                "У тебя уже есть активная запись 🤍 Заверши её, прежде чем брать новую.",
                show_alert=True,
            )
            return
        booking = Booking(
            telegram_id=callback.from_user.id,
            slot_start=slot,
            status="held",
            held_until=now + booking_config.hold,
        )
        session.add(booking)
        await session.commit()
        booking_id = booking.id

    hold_local = (now + booking_config.hold).astimezone(booking_config.tz)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        f"<b>✦ Твой слот: {format_slot_human(slot)}</b>\n\n"
        f"● Стоимость: {PRICE_TEXT}\n\n"
        f"Время держим до {hold_local:%H:%M} (Прага). "
        "Оплати удобным способом и нажми «✓ Я оплатил(а)» ⇩\n"
        "Лана подтвердит запись, и тебе придёт сообщение.",
        reply_markup=booking_pay_kb(booking_id),
    )
