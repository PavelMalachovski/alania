import asyncio
import logging
from datetime import datetime, timezone

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramRetryAfter
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message
from sqlalchemy import select

from database import Booking, User, get_session, set_setting
from filters import IsAdmin
from formatting import format_slot_human
from google_calendar import GoogleCalendar
from keyboards.inline import broadcast_confirm_kb, lead_done_kb

router = Router()
router.message.filter(IsAdmin())
router.callback_query.filter(IsAdmin())

logger = logging.getLogger(__name__)

GUIDE_FILE_KEY = "guide_file_id"


class GuideForm(StatesGroup):
    waiting_file = State()


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
        "/set_guide — загрузить файл гайда «Карта твоего запроса»\n"
        "/broadcast — рассылка всем пользователям бота\n"
        "/bookings — ближайшие оплаченные записи\n"
        "/cancel — отменить текущее действие"
    )


# ── Гайд ─────────────────────────────────────────────────────────────
@router.message(Command("set_guide"))
async def cmd_set_guide(message: Message, state: FSMContext) -> None:
    await state.set_state(GuideForm.waiting_file)
    await message.answer(
        "Пришли файл гайда (PDF) следующим сообщением.\n"
        "Отмена — /cancel"
    )


@router.message(GuideForm.waiting_file, F.document)
async def guide_file(message: Message, state: FSMContext) -> None:
    await set_setting(GUIDE_FILE_KEY, message.document.file_id)
    await state.clear()
    await message.answer(
        "✅ Гайд сохранён. Теперь кнопка «Забрать гайд» отправляет этот файл."
    )


@router.message(GuideForm.waiting_file)
async def guide_not_file(message: Message) -> None:
    await message.answer("Нужен именно файл (документ). Отмена — /cancel")


# ── Подтверждение / отклонение оплаты слота ──────────────────────────
@router.callback_query(F.data.startswith("confirm_pay:"))
async def cb_confirm_pay(callback: CallbackQuery, bot: Bot) -> None:
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
        booking.status = "confirmed"
        await session.commit()
        user_id, slot = booking.telegram_id, booking.slot_start
    if slot.tzinfo is None:
        slot = slot.replace(tzinfo=timezone.utc)
    try:
        await bot.send_message(
            user_id,
            "○─── ☾ ───○\n\n"
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
    await callback.message.edit_text(
        callback.message.html_text + "\n\n✅ <b>Оплата подтверждена</b>"
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
            "○─── ☾ ───○\n\n"
            "К сожалению, оплату по этой записи мы не нашли, и слот освобождён.\n"
            "Если ты оплачивал(а) — напиши Лане в ЛС, разберёмся 🤍",
            reply_markup=lead_done_kb(),
        )
    except TelegramAPIError:
        pass
    await callback.message.edit_text(
        callback.message.html_text + "\n\n❌ <b>Оплата отклонена, слот освобождён</b>"
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
@router.message(Command("broadcast"))
async def cmd_broadcast(message: Message, state: FSMContext) -> None:
    await state.set_state(BroadcastForm.waiting_message)
    await message.answer(
        "Пришли сообщение для рассылки (текст, фото, видео — что угодно).\n"
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

    sent = failed = 0
    for user_id in user_ids:
        try:
            await bot.copy_message(
                chat_id=user_id,
                from_chat_id=data["chat_id"],
                message_id=data["message_id"],
            )
            sent += 1
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after)
            try:
                await bot.copy_message(
                    chat_id=user_id,
                    from_chat_id=data["chat_id"],
                    message_id=data["message_id"],
                )
                sent += 1
            except TelegramAPIError:
                failed += 1
        except TelegramAPIError:
            # пользователь заблокировал бота или удалился
            failed += 1
        await asyncio.sleep(0.05)

    await callback.message.answer(
        f"✅ Рассылка завершена.\n"
        f"Доставлено: {sent}\n"
        f"Не доставлено (бот заблокирован и т.п.): {failed}"
    )
