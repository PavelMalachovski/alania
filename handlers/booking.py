import logging
from datetime import date, datetime, timedelta, timezone

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from booking_config import BookingConfig
from database import Booking, get_session
from formatting import PRICE_TEXT, format_slot_human
from google_calendar import GoogleCalendar
from keyboards.inline import (
    admin_confirm_pay_kb,
    admin_resched_kb,
    booking_calendar_kb,
    booking_error_kb,
    booking_pay_kb,
    booking_times_kb,
    lead_done_kb,
    my_bookings_kb,
)
from slots import free_slots
from ui import delete_safe, edit_screen

router = Router()
logger = logging.getLogger(__name__)
_WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

_CALENDAR_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>✦ Запись на личную сессию</b>\n\n"
    "Выбери удобный для тебя день ⇩\n"
    "‼️ Часовой пояс: Прага CET (в скобках — московское время)"
)


def _month_index(year: int, month: int) -> int:
    return year * 12 + (month - 1)


async def _render_calendar(
    message, year: int, month: int, slots: list[datetime], cfg: BookingConfig,
    *, prefix: str = "book", back_cb: str = "consultation", send: bool = False,
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
    kb = booking_calendar_kb(
        year, month, free_dates,
        has_prev=cur_mi > min_mi, has_next=cur_mi < max_mi,
        prefix=prefix, back_cb=back_cb,
    )
    if send:
        await message.answer(_CALENDAR_TEXT, reply_markup=kb)
    else:
        await message.edit_text(_CALENDAR_TEXT, reply_markup=kb)


MAX_ACTIVE_BOOKINGS = 5


async def _occupied_slots(session, now: datetime) -> list[datetime]:
    """Слоты, занятые до появления события в календаре: held (не истёкшие),
    pay_claimed (оплачено, ждёт подтверждения) и confirmed с
    calendar_sync_failed=True (событие в Google не создалось — слот больше
    ничем не защищён от double-booking)."""
    rows = (await session.execute(
        select(Booking.slot_start).where(
            ((Booking.status == "held") & (Booking.held_until > now))
            | (Booking.status == "pay_claimed")
            | ((Booking.status == "confirmed") & (Booking.calendar_sync_failed == True)  # noqa: E712
               & (Booking.slot_start > now))
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


async def open_calendar(message, gcal: GoogleCalendar, cfg: BookingConfig, *, send: bool) -> None:
    """Показать календарь записи. send=True — новым сообщением, иначе редактируя message."""
    try:
        slots = await _load_free(gcal, cfg)
    except Exception:
        logger.exception("Google Calendar недоступен при показе слотов")
        text = (
            "○─── ☾ ───○\n\n"
            "Расписание сейчас недоступно 🤍 Попробуй через минуту "
            "или напиши Лане в личку — подберём время вручную."
        )
        await (message.answer(text, reply_markup=booking_error_kb()) if send
               else message.edit_text(text, reply_markup=booking_error_kb()))
        return
    if not slots:
        text = (
            "○─── ☾ ───○\n\n"
            "Ближайшее время сейчас занято 🤍 Напиши Лане в ЛС — "
            "подберём время индивидуально."
        )
        await (message.answer(text, reply_markup=booking_error_kb()) if send
               else message.edit_text(text, reply_markup=booking_error_kb()))
        return
    # открываем на месяце ближайшего свободного слота
    first = slots[0].astimezone(cfg.tz).date()
    await _render_calendar(message, first.year, first.month, slots, cfg, send=send)


@router.callback_query(F.data.in_({"booking_start", "consultation_pay"}))
async def cb_booking_start(
    callback: CallbackQuery, gcal: GoogleCalendar, booking_config: BookingConfig
) -> None:
    await open_calendar(callback.message, gcal, booking_config, send=False)


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


async def build_event_fields(session, tg_id: int) -> tuple[str, str]:
    """Заголовок и описание события в календаре по данным клиента из User."""
    from database import User
    user = await session.get(User, tg_id)
    name = (user.full_name if user and user.full_name else f"id {tg_id}")
    handle = f"@{user.username}" if user and user.username else f"id {tg_id}"
    return f"Консультация — {name}", f"Клиент: {name} ({handle})"


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
async def cb_paid(callback: CallbackQuery, bot: Bot, admin_ids: list[int]) -> None:
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
        booking.status = "pay_claimed"
        await session.commit()
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)

    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "🤍 Принято! Проверяем оплату.\n\n"
        f"Как только Лана подтвердит, придёт сообщение о записи на "
        f"<b>{format_slot_human(slot)}</b>."
    )
    await _notify_admins(
        bot, admin_ids,
        "💳 <b>Клиент сообщил об оплате слота</b>\n\n"
        f"<b>Слот:</b> {format_slot_human(slot)}\n"
        f"{_client_line(callback)}\n\n"
        "Проверь оплату в Tribute и подтверди ⇩",
        reply_markup=admin_confirm_pay_kb(booking_id),
    )


async def open_my_bookings(message, tg_id: int, *, send: bool) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Booking).where(
                Booking.telegram_id == tg_id,
                Booking.status.in_(["pay_claimed", "confirmed"]),
                Booking.slot_start >= now,
            ).order_by(Booking.slot_start)
        )).scalars().all()
    if not rows:
        text = "○─── ☾ ───○\n\nУ тебя пока нет активных записей 🤍"
        kb = my_bookings_kb([])
    else:
        items = []
        for b in rows:
            slot = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
            items.append((format_slot_human(slot), b.id))
        text = "○─── ☾ ───○\n\n<b>✦ Твои записи</b>\n\nВыбери, что перенести ⇩"
        kb = my_bookings_kb(items)
    await (message.answer(text, reply_markup=kb) if send
           else message.edit_text(text, reply_markup=kb))


@router.callback_query(F.data == "my_bookings")
async def cb_my_bookings(callback: CallbackQuery) -> None:
    await open_my_bookings(callback.message, callback.from_user.id, send=False)


RESCHEDULE_THRESHOLD = timedelta(hours=24)


class RescheduleForm(StatesGroup):
    picking = State()
    reason = State()


async def apply_reschedule(gcal, session, booking, new_slot: datetime) -> bool:
    """Двигает бронь на new_slot. Для confirmed с событием — пересоздаёт событие
    (delete старое + create новое). Возвращает True если Google не подвёл."""
    sync_ok = True
    if booking.google_event_id:
        try:
            await gcal.delete_event(booking.google_event_id)
        except Exception:
            logger.exception("Не удалось удалить старое событие при переносе")
            booking.calendar_sync_failed = True
        try:
            title, desc = await build_event_fields(session, booking.telegram_id)
            booking.google_event_id = await gcal.create_event(new_slot, title, desc)
        except Exception:
            logger.exception("Не удалось создать новое событие при переносе")
            booking.google_event_id = None
            booking.calendar_sync_failed = True
            sync_ok = False
    booking.slot_start = new_slot
    return sync_ok


@router.callback_query(F.data.startswith("resched:"))
async def cb_resched_start(callback: CallbackQuery, state: FSMContext,
                           gcal: GoogleCalendar, booking_config: BookingConfig) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял запись", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if (not booking or booking.telegram_id != callback.from_user.id
                or booking.status not in ("pay_claimed", "confirmed")):
            await callback.answer("Запись недоступна для переноса", show_alert=True)
            return
    await state.set_state(RescheduleForm.picking)
    await state.update_data(resched_booking_id=booking_id)
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        logger.exception("Google недоступен при старте переноса")
        await state.clear()
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍 Попробуй ещё раз.",
            reply_markup=booking_error_kb(),
        )
        return
    if not slots:
        await state.clear()
        await callback.answer("Свободного времени сейчас нет", show_alert=True)
        return
    first = slots[0].astimezone(booking_config.tz).date()
    await _render_calendar(callback.message, first.year, first.month, slots,
                           booking_config, prefix="resched", back_cb="my_bookings")


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_month:"))
async def cb_resched_month(callback: CallbackQuery, gcal: GoogleCalendar,
                           booking_config: BookingConfig) -> None:
    try:
        y, m = (int(x) for x in callback.data.split(":", 1)[1].split("-"))
    except ValueError:
        await callback.answer("Не понял месяц", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    await _render_calendar(callback.message, y, m, slots, booking_config,
                           prefix="resched", back_cb="my_bookings")


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_day:"))
async def cb_resched_day(callback: CallbackQuery, gcal: GoogleCalendar,
                         booking_config: BookingConfig) -> None:
    try:
        d = date.fromisoformat(callback.data.split(":", 1)[1])
    except ValueError:
        await callback.answer("Не понял день", show_alert=True)
        return
    try:
        slots = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    day_slots = [s for s in slots if s.astimezone(booking_config.tz).date() == d]
    if not day_slots:
        await callback.answer("На этот день нет свободного времени", show_alert=True)
        return
    time_buttons = [(format_slot_human(s).split("·", 1)[1].strip(), s.isoformat())
                    for s in day_slots]
    await callback.message.edit_text(
        f"<b>✦ Перенос на {_WEEKDAYS_RU[d.weekday()]} {d.strftime('%d.%m')}</b>\n\n"
        "Выбери время ⇩",
        reply_markup=booking_times_kb(
            d.isoformat(), time_buttons, prefix="resched",
            back_cb=f"resched_month:{d.year}-{d.month:02d}"),
    )


@router.callback_query(RescheduleForm.picking, F.data.startswith("resched_slot:"))
async def cb_resched_slot(callback: CallbackQuery, state: FSMContext, bot: Bot,
                          admin_ids: list[int], gcal: GoogleCalendar,
                          booking_config: BookingConfig) -> None:
    try:
        new_slot = datetime.fromisoformat(callback.data.split(":", 1)[1]).astimezone(timezone.utc)
    except ValueError:
        await callback.answer("Не понял слот", show_alert=True)
        return
    data = await state.get_data()
    booking_id = data.get("resched_booking_id")
    if not booking_id:
        await callback.answer("Сессия сброшена, открой «Мои записи» заново", show_alert=True)
        return
    now = datetime.now(timezone.utc)
    try:
        free = await _load_free(gcal, booking_config)
    except Exception:
        await callback.message.edit_text(
            "Расписание сейчас недоступно 🤍", reply_markup=booking_error_kb())
        return
    if new_slot not in free:
        await callback.answer("Это время только что заняли 🤍 Выбери другое", show_alert=True)
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != callback.from_user.id:
            await callback.answer("Запись не найдена", show_alert=True)
            await state.clear()
            return
        old_slot = booking.slot_start if booking.slot_start.tzinfo else booking.slot_start.replace(tzinfo=timezone.utc)

        if old_slot - now >= RESCHEDULE_THRESHOLD:
            # самостоятельный перенос
            await apply_reschedule(gcal, session, booking, new_slot)
            await session.commit()
            await state.clear()
            await callback.message.edit_text(
                "○─── ☾ ───○\n\n"
                f"✦ Перенесено на <b>{format_slot_human(new_slot)}</b> 🤍",
                reply_markup=lead_done_kb(),
            )
            await _notify_admins(
                bot, admin_ids,
                "🔁 <b>Клиент перенёс запись</b>\n\n"
                f"Было: {format_slot_human(old_slot)}\n"
                f"Стало: {format_slot_human(new_slot)}\n"
                f"{_client_line(callback)}",
            )
            return

    # <24ч — просим причину; якорь = это же сообщение, его и будем редактировать
    await state.update_data(
        resched_new_slot=new_slot.isoformat(),
        resched_screen_id=callback.message.message_id,
    )
    await state.set_state(RescheduleForm.reason)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "До сессии меньше 24 часов — перенос подтверждает Лана.\n\n"
        "Напиши, пожалуйста, причину переноса ⇩"
    )


@router.message(RescheduleForm.reason, F.text)
async def resched_reason(message: Message, state: FSMContext, bot: Bot,
                         admin_ids: list[int]) -> None:
    data = await state.get_data()
    screen_id = data.get("resched_screen_id")
    chat_id = message.chat.id

    async def _finish_screen(text: str, kb=None) -> None:
        # убрать текст клиента и обновить якорь (или прислать новое, если якорь потерян)
        await delete_safe(bot, chat_id, message.message_id)
        if screen_id:
            await edit_screen(bot, chat_id, screen_id, text, kb)
        else:
            await message.answer(text, reply_markup=kb)

    if message.text.startswith("/"):
        await state.clear()
        await _finish_screen("Ок, перенос отменён.", lead_done_kb())
        return
    booking_id = data.get("resched_booking_id")
    new_slot_iso = data.get("resched_new_slot")
    await state.clear()
    if not booking_id or not new_slot_iso:
        await _finish_screen("Сессия сброшена, открой «Мои записи» заново.", lead_done_kb())
        return
    new_slot = datetime.fromisoformat(new_slot_iso)
    reason = message.text.strip()[:500]
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != message.from_user.id:
            await _finish_screen("Запись не найдена.", lead_done_kb())
            return
        old_slot = booking.slot_start if booking.slot_start.tzinfo else booking.slot_start.replace(tzinfo=timezone.utc)
        booking.reschedule_to = new_slot
        booking.reschedule_reason = reason
        booking.reschedule_status = "pending"
        await session.commit()
    await _finish_screen(
        "○─── ☾ ───○\n\n"
        "🤍 Запрос на перенос отправлен Лане. Как решится — пришлём сообщение.",
        lead_done_kb(),
    )
    await _notify_admins(
        bot, admin_ids,
        "🔁 <b>Запрос на перенос (меньше 24ч)</b>\n\n"
        f"Было: {format_slot_human(old_slot)}\n"
        f"Хочет: {format_slot_human(new_slot)}\n"
        f"Причина: {html.quote(reason)}\n"
        f'<b>Клиент:</b> id {message.from_user.id}\n\n'
        "Подтвердить перенос? ⇩",
        reply_markup=admin_resched_kb(booking_id),
    )
