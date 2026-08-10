import asyncio
import logging
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import (
    TelegramAPIError,
    TelegramForbiddenError,
    TelegramNetworkError,
    TelegramNotFound,
    TelegramRetryAfter,
    TelegramServerError,
)
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from booking_config import BookingConfig
from database import Booking, User, get_session
from filters import IsAdmin
from formatting import format_slot_human
from google_calendar import GoogleCalendar
from handlers.booking import apply_reschedule, build_event_fields, _occupied_slots
from handlers.start import MAIN_MENU_TEXT
from keyboards.inline import broadcast_confirm_kb, lead_done_kb
from keyboards.reply import main_reply_kb
from slots import free_slots
from ui import reset_keyboard, show_screen

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

logger = logging.getLogger(__name__)

class BroadcastForm(StatesGroup):
    waiting_message = State()
    waiting_confirm = State()


@router.message(Command("cancel"))
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer("Ок, отменено.")


@router.message(Command("admin"))
async def cmd_admin(message: Message) -> None:
    await message.answer(
        "<b>Админ-команды:</b>\n\n"
        "/broadcast — рассылка всем пользователям бота\n"
        "/bookings — ближайшие оплаченные записи\n"
        "/cancel — отменить текущее действие"
    )


# ── Подтверждение / отклонение оплаты слота ──────────────────────────
@router.callback_query(F.data.startswith("confirm_pay:"))
async def cb_confirm_pay(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status == "confirmed":
            await callback.answer("Уже подтверждено")
            return
        if booking.status != "pay_claimed":
            await callback.answer(
                f"Эта запись уже обработана ({booking.status})", show_alert=True
            )
            return
        slot = booking.slot_start
        if slot.tzinfo is None:
            slot = slot.replace(tzinfo=timezone.utc)
        title, desc = await build_event_fields(session, booking.telegram_id)

    event_id = None
    sync_failed = False
    try:
        event_id = await gcal.create_event(slot, title, desc)
    except Exception:
        logger.exception("Не удалось создать событие для booking %s", booking_id)
        sync_failed = True

    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        booking.status = "confirmed"
        booking.google_event_id = event_id
        booking.calendar_sync_failed = sync_failed
        await session.commit()
        user_id = booking.telegram_id

    try:
        await bot.send_message(
            user_id,
            "<b>✦ Вы оплатили, спасибо!</b> 🤍\n\n"
            f"Запись подтверждена: <b>{format_slot_human(slot)}</b>.\n\n"
            "Лана свяжется с тобой перед сессией и пришлёт ссылку на видеозвонок. "
            "До встречи ✦",
            reply_markup=lead_done_kb(),
        )
    except TelegramAPIError:
        await callback.message.answer(
            "⚠️ Оплата подтверждена, но сообщение клиенту не доставлено."
        )
    warn = " ⚠️ событие оформи вручную" if sync_failed else ""
    await callback.message.edit_text(
        f"✅ {format_slot_human(slot)} — оплата подтверждена{warn}"
    )


@router.callback_query(F.data.startswith("reject_pay:"))
async def cb_reject_pay(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking:
            await callback.answer("Запись не найдена", show_alert=True)
            return
        if booking.status == "cancelled":
            await callback.answer("Уже отменено")
            return
        if booking.status == "confirmed":
            await callback.answer(
                "Запись уже подтверждена, отклонить нельзя", show_alert=True
            )
            return
        event_id = booking.google_event_id
        booking.status = "cancelled"
        await session.commit()
        user_id, slot = booking.telegram_id, booking.slot_start
    if event_id:
        try:
            await gcal.delete_event(event_id)
        except Exception:
            logger.exception("Не удалось удалить событие %s", event_id)
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)
    try:
        await bot.send_message(
            user_id,
            "К сожалению, оплату по этой записи мы не нашли, и слот освобождён.\n"
            "Если ты оплачивал(а) — напиши Лане в ЛС, разберёмся 🤍",
            reply_markup=lead_done_kb(),
        )
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        f"❌ {format_slot_human(slot)} — оплата отклонена, слот освобождён"
    )


@router.callback_query(F.data.startswith("resched_ok:"))
async def cb_resched_ok(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar,
                        booking_config: BookingConfig) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.reschedule_status != "pending":
            await callback.answer("Запрос уже обработан", show_alert=True)
            return
        new_slot = booking.reschedule_to
        if new_slot.tzinfo is None:
            new_slot = new_slot.replace(tzinfo=timezone.utc)
        # новый слот всё ещё свободен?
        try:
            busy = await gcal.busy(now, now + timedelta(days=booking_config.horizon_days))
        except Exception:
            logger.exception("Google недоступен при подтверждении переноса")
            await callback.answer("Google недоступен, попробуй ещё раз", show_alert=True)
            return
        occupied = await _occupied_slots(session, now)
        free = free_slots(now, busy, occupied,
                          work_times=booking_config.work_times,
                          work_weekdays=booking_config.work_weekdays,
                          horizon_days=booking_config.horizon_days,
                          lead=booking_config.lead, tz=booking_config.tz)
        if new_slot not in free:
            booking.reschedule_status = None
            booking.reschedule_to = None
            booking.reschedule_reason = None
            await session.commit()
            user_id = booking.telegram_id
            await callback.answer("Новый слот уже занят — перенос отменён", show_alert=True)
            await callback.message.edit_text(
                "⚠️ Новый слот заняли — перенос не выполнен, запись на прежнем слоте"
            )
            try:
                await bot.send_message(
                    user_id,
                    "К сожалению, выбранное для переноса время уже заняли. "
                    "Запись осталась на прежнем слоте 🤍")
            except TelegramAPIError:
                pass
            return
        await apply_reschedule(gcal, session, booking, new_slot)
        booking.reschedule_status = None
        booking.reschedule_to = None
        booking.reschedule_reason = None
        await session.commit()
        user_id, moved = booking.telegram_id, new_slot
    try:
        await bot.send_message(
            user_id,
            f"✦ Перенос подтверждён: <b>{format_slot_human(moved)}</b> 🤍",
            reply_markup=lead_done_kb())
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        f"✅ Перенос подтверждён: {format_slot_human(moved)}"
    )


@router.callback_query(F.data.startswith("resched_no:"))
async def cb_resched_no(callback: CallbackQuery, bot: Bot, gcal: GoogleCalendar) -> None:
    try:
        booking_id = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.reschedule_status != "pending":
            await callback.answer("Запрос уже обработан", show_alert=True)
            return
        event_id = booking.google_event_id
        booking.status = "cancelled"
        booking.reschedule_status = None
        booking.reschedule_to = None
        booking.reschedule_reason = None
        await session.commit()
        user_id = booking.telegram_id
    if event_id:
        try:
            await gcal.delete_event(event_id)
        except Exception:
            logger.exception("Не удалось удалить событие при отклонении переноса")
    try:
        await bot.send_message(
            user_id,
            "Перенос отклонён. К сожалению, запись отменена, "
            "оплата не возвращается 🤍",
            reply_markup=lead_done_kb())
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        "❌ Перенос отклонён, запись отменена"
    )


@router.message(Command("bookings"))
async def cmd_bookings(message: Message) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Booking).where(
                Booking.status.in_(["pay_claimed", "confirmed"]),
                Booking.slot_start >= now,
            ).order_by(Booking.slot_start)
        )).scalars().all()
    if not rows:
        await message.answer("Ближайших оплаченных записей нет.")
        return
    lines = ["<b>Ближайшие записи:</b>\n"]
    for b in rows:
        slot = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
        mark = "✅" if b.status == "confirmed" else "💳"
        warn = " ⚠️календарь" if b.calendar_sync_failed else ""
        lines.append(f"{mark} {format_slot_human(slot)} — id {b.telegram_id}{warn}")
    await message.answer("\n".join(lines))


# ── Рассылка ─────────────────────────────────────────────────────────
# На человека уходит 5 запросов: копия сообщения + якорь + приветствие и два
# удаления к ним. Лимит Telegram — около 30 запросов в секунду на бота, и
# считаются в нём все методы, а не только отправки. При паузе 0.15 с рассылка
# давала ~33 запроса в секунду, упиралась во flood control (429) и теряла часть
# людей: одной повторной попытки не хватало. 0.4 с — примерно 12 запросов в
# секунду, с запасом.
BROADCAST_DELAY = 0.4
SEND_ATTEMPTS = 4
PROGRESS_EVERY = 25

SENT, BLOCKED, ERROR = "sent", "blocked", "error"


async def _copy_to(bot: Bot, user_id: int, data: dict) -> str:
    """Копия сообщения рассылки одному человеку. copy_message переносит любой
    тип контента — текст, фото, кружок, голосовое — без пометки «переслано».

    Возвращает SENT / BLOCKED (бот заблокирован или аккаунт удалён — повторять
    бессмысленно) / ERROR (не доставлено, повторы исчерпаны)."""
    for attempt in range(1, SEND_ATTEMPTS + 1):
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=data["chat_id"],
                message_id=data["message_id"],
            )
            return SENT
        except TelegramRetryAfter as e:
            logger.warning(
                "Рассылка: flood control, ждём %s с (попытка %s, получатель %s)",
                e.retry_after, attempt, user_id,
            )
            if attempt == SEND_ATTEMPTS:
                return ERROR
            await asyncio.sleep(e.retry_after + 1)
        except (TelegramForbiddenError, TelegramNotFound):
            return BLOCKED
        except (TelegramNetworkError, TelegramServerError) as e:
            logger.warning("Рассылка: сеть/сервер Telegram для %s: %s", user_id, e)
            if attempt == SEND_ATTEMPTS:
                return ERROR
            await asyncio.sleep(2 * attempt)
        except TelegramAPIError:
            logger.exception("Рассылка: Telegram отказал для %s", user_id)
            return ERROR
        except Exception:
            logger.exception("Рассылка: неожиданная ошибка для %s", user_id)
            return ERROR
    return ERROR


async def _restore_bottom(bot: Bot, user_id: int) -> None:
    """Пересобрать низ чата после сообщения Ланы: заново прислать 🤍-якорь с
    клавиатурой и приветственный экран. Так сообщение остаётся НАД сердечком,
    а меню — внизу чата (иначе рассылка падает под якорь и старое окно).

    Глотаем здесь любое исключение, а не только TelegramAPIError: внутри есть
    обращения к settings, и падение БД раньше валило весь цикл рассылки — часть
    людей оставалась без сообщения, а Лана даже не видела итогового отчёта."""
    try:
        await reset_keyboard(bot, user_id, main_reply_kb())
        await show_screen(bot, user_id, MAIN_MENU_TEXT)
    except Exception:
        logger.warning("Рассылка: не пересобрал низ чата для %s", user_id, exc_info=True)


async def _progress(message: Message, done: int, total: int) -> None:
    try:
        await message.edit_text(f"⏳ Рассылка идёт: {done} из {total}…")
    except TelegramAPIError:
        logger.debug("Рассылка: не обновил прогресс")


@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastForm.waiting_message)
    await message.answer(
        "Пришли сообщение для рассылки (текст, голосовое, фото, видео — "
        "что угодно).\n"
        "Я покажу превью перед отправкой. Отмена — /cancel"
    )


@router.message(BroadcastForm.waiting_message)
async def broadcast_message(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.update_data(chat_id=message.chat.id, message_id=message.message_id)
    await state.set_state(BroadcastForm.waiting_confirm)
    await bot.copy_message(
        chat_id=message.chat.id,
        from_chat_id=message.chat.id,
        message_id=message.message_id,
    )
    await message.answer(
        "⇧ Так будет выглядеть сообщение. Отправляем?",
        reply_markup=broadcast_confirm_kb(),
    )


@router.callback_query(BroadcastForm.waiting_confirm, F.data == "broadcast_cancel")
async def cb_broadcast_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Рассылка отменена.")


@router.callback_query(BroadcastForm.waiting_confirm, F.data == "broadcast_confirm")
async def cb_broadcast_confirm(
    callback: CallbackQuery, state: FSMContext, bot: Bot
) -> None:
    data = await state.get_data()
    await state.clear()
    await callback.answer()
    await callback.message.edit_text("⏳ Рассылка запущена…")

    async with get_session() as session:
        result = await session.execute(select(User.telegram_id))
        user_ids = list(result.scalars())

    sent = blocked = 0
    errors: list[int] = []
    total = len(user_ids)
    logger.info("Рассылка: старт, получателей %s", total)
    for done, user_id in enumerate(user_ids, start=1):
        # Ни одна ошибка на конкретном человеке не должна обрывать цикл: раньше
        # исключение улетало в dp.errors(), рассылка тихо останавливалась на
        # середине списка, и остальные не получали ничего.
        try:
            status = await _copy_to(bot, user_id, data)
            if status == SENT:
                sent += 1
                await _restore_bottom(bot, user_id)
            elif status == BLOCKED:
                blocked += 1
            else:
                errors.append(user_id)
        except Exception:
            logger.exception("Рассылка: сорвалась отправка для %s", user_id)
            errors.append(user_id)
        if done % PROGRESS_EVERY == 0 and done < total:
            await _progress(callback.message, done, total)
        await asyncio.sleep(BROADCAST_DELAY)

    logger.info(
        "Рассылка: готово. Доставлено %s, заблокировали %s, ошибок %s",
        sent, blocked, len(errors),
    )
    report = [
        "✅ Рассылка завершена.",
        f"Всего в базе: {total}",
        f"Доставлено: {sent}",
        f"Заблокировали бота или удалились: {blocked}",
        f"Не доставлено из-за ошибок: {len(errors)}",
    ]
    if errors:
        ids = ", ".join(str(i) for i in errors[:10])
        tail = " …" if len(errors) > 10 else ""
        report.append(f"\nID с ошибкой: {ids}{tail}\nИм можно написать вручную.")
    await callback.message.answer("\n".join(report))


@router.callback_query(F.data.in_({"broadcast_confirm", "broadcast_cancel"}))
async def cb_broadcast_stale(callback: CallbackQuery) -> None:
    """Кнопки превью, пережившие рестарт бота. FSM лежит в памяти процесса, и
    состояние `waiting_confirm` рестарт не переживает — без этого хендлера
    нажатие «Отправить» молча не делало бы ничего, и рассылка «не уходила»."""
    await callback.answer(
        "Превью устарело — бот перезапускался. Пришли сообщение заново: /broadcast",
        show_alert=True,
    )
