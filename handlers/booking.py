import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery
from sqlalchemy import select

from booking_config import BookingConfig
from database import Booking, get_session
from formatting import PRICE_TEXT, format_slot_human
from google_calendar import GoogleCalendar
from keyboards.inline import (
    admin_confirm_pay_kb,
    booking_calendar_kb,
    booking_error_kb,
    booking_pay_kb,
    booking_times_kb,
)
from slots import free_slots

router = Router()
logger = logging.getLogger(__name__)
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_CALENDAR_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>✦ Запись на консультацию</b>\n\n"
    "Дни со свободным временем — активные кнопки. "
    "Время — Прага (в скобках московское).\n\n"
    "Выбери день ⇩"
)


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


async def _render_calendar(
    message, year: int, month: int, slots: list[datetime], cfg: BookingConfig
) -> None:
    """Рисует сетку месяца по свободным слотам (aware-UTC список slots)."""
    tz = cfg.tz
    now = datetime.now(timezone.utc)
    now_d = now.astimezone(tz).date()
    horizon_d = (now + timedelta(days=cfg.horizon_days)).astimezone(tz).date()
    min_mi = _month_index(now_d.year, now_d.month)
    max_mi = _month_index(horizon_d.year, horizon_d.month)
    cur_mi = _month_index(year, month)

    free_dates = {
        d for s in slots
        if (d := s.astimezone(tz).date()).year == year and d.month == month
    }
    await message.edit_text(
        _CALENDAR_TEXT,
        reply_markup=booking_calendar_kb(
            year, month, free_dates,
            has_prev=cur_mi > min_mi, has_next=cur_mi < max_mi,
        ),
    )


MAX_ACTIVE_BOOKINGS = 5


async def _occupied_slots(session, now: datetime) -> list[datetime]:
    """Слоты, занятые до появления события в календаре: held (не истёкшие) и
    pay_claimed (оплачено, ждёт подтверждения)."""
    rows = (await session.execute(
        select(Booking.slot_start).where(
            ((Booking.status == "held") & (Booking.held_until > now))
            | (Booking.status == "pay_claimed")
        )
    )).scalars()
    return [r if r.tzinfo else r.replace(tzinfo=timezone.utc) for r in rows]


async def _active_booking_count(session, tg_id: int, now: datetime) -> int:
    rows = (await session.execute(
        select(Booking.id).where(
            Booking.telegram_id == tg_id,
            (Booking.status.in_(["confirmed", "pay_claimed"]) & (Booking.slot_start > now))
            | ((Booking.status == "held") & (Booking.held_until > now)),
        )
    )).all()
    return len(rows)


async def _load_free(gcal: GoogleCalendar, cfg: BookingConfig) -> list[datetime]:
    now = datetime.now(timezone.utc)
    horizon_end = now + timedelta(days=cfg.horizon_days)
    busy = await gcal.busy(now, horizon_end)
    async with get_session() as session:
        holds = await _occupied_slots(session, now)
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
            "Ближайшее время сейчас занято 🤍 Напиши Лане в ЛС — "
            "подберём время индивидуально.",
            reply_markup=booking_error_kb(),
        )
        return
    # открываем на месяце ближайшего свободного слота
    first = slots[0].astimezone(booking_config.tz).date()
    await _render_calendar(callback.message, first.year, first.month, slots, booking_config)


@router.callback_query(F.data.startswith("book_month:"))
async def cb_book_month(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    try:
        year_s, month_s = callback.data.split(":", 1)[1].split("-")
        year, month = int(year_s), int(month_s)
        if not 1 <= month <= 12:
            raise ValueError
    except ValueError:
        await callback.answer("Не понял месяц", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при навигации календаря")
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    await _render_calendar(callback.message, year, month, slots, booking_config)


@router.callback_query(F.data == "noop")
async def cb_noop(callback: CallbackQuery) -> None:
    # неактивная ячейка календаря — просто гасим «часики» (это делает middleware)
    return


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
        if await _active_booking_count(session, callback.from_user.id, now) >= MAX_ACTIVE_BOOKINGS:
            await callback.answer(
                "У тебя уже 5 активных записей 🤍 Заверши или перенеси одну, "
                "прежде чем брать новую.",
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


def _client_line(callback: CallbackQuery) -> str:
    user = callback.from_user
    username = f"@{user.username}" if user.username else "нет username"
    return (
        f"<b>Клиент:</b> {html.quote(user.full_name)} — {username} "
        f'(<a href="tg://user?id={user.id}">открыть</a>, id {user.id})'
    )


def _event_description(callback: CallbackQuery) -> str:
    user = callback.from_user
    username = f"@{user.username}" if user.username else f"id {user.id}"
    return f"Клиент: {user.full_name} ({username})"


async def _notify_admins(bot: Bot, admin_ids, text: str, reply_markup=None) -> None:
    delivered = False
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, text, reply_markup=reply_markup)
            delivered = True
        except TelegramAPIError:
            logger.warning("Не доставлено админу %s", admin_id)
    if not delivered:
        logger.error("Уведомление не доставлено НИ ОДНОМУ админу: %s", text[:80])


@router.callback_query(F.data.startswith("paid:"))
async def cb_paid(
    callback: CallbackQuery, bot: Bot, admin_ids: list[int], gcal: GoogleCalendar
) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял запись", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status != "held":
            await callback.answer("Уже принято 🤍 Ждём подтверждения Ланы", show_alert=True)
            return
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)

    # создаём событие в календаре
    event_id = None
    sync_failed = False
    try:
        event_id = await gcal.create_event(
            slot, callback.from_user.full_name, _event_description(callback)
        )
    except Exception:
        logger.exception("Не удалось создать событие в календаре для booking %s", booking_id)
        sync_failed = True

    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if booking.status != "held":  # гонка двойного клика
            if event_id:
                try:
                    await gcal.delete_event(event_id)
                except Exception:
                    logger.exception("Откат дубля события не удался")
            await callback.answer("Уже принято 🤍", show_alert=True)
            return
        booking.status = "pay_claimed"
        booking.google_event_id = event_id
        booking.calendar_sync_failed = sync_failed
        await session.commit()

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "🤍 Принято! Проверяем оплату.\n\n"
        f"Как только Лана подтвердит, придёт сообщение о записи на "
        f"<b>{format_slot_human(slot)}</b>."
    )
    warn = "\n\n⚠️ Событие в календаре не создалось — оформи вручную." if sync_failed else ""
    await _notify_admins(
        bot, admin_ids,
        "💳 <b>Клиент сообщил об оплате слота</b>\n\n"
        f"<b>Слот:</b> {format_slot_human(slot)}\n"
        f"{_client_line(callback)}\n\n"
        f"Проверь оплату в Tribute и подтверди ⇩{warn}",
        reply_markup=admin_confirm_pay_kb(booking_id),
    )
