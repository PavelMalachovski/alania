from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from booking_config import BookingConfig
from google_calendar import GoogleCalendar
from handlers.booking import open_calendar, open_my_bookings
from handlers.start import open_main_menu
from keyboards.inline import ask_lana_kb
from keyboards.reply import BTN_ASK, BTN_BOOK, BTN_MENU, BTN_MY
from ui import delete_safe

router = Router()


@router.message(StateFilter(None), F.text == BTN_BOOK)
async def reply_book(message: Message, gcal: GoogleCalendar,
                     booking_config: BookingConfig, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_calendar(message, gcal, booking_config, send=True)


@router.message(StateFilter(None), F.text == BTN_MY)
async def reply_my(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_my_bookings(message, message.from_user.id, send=True)


@router.message(StateFilter(None), F.text == BTN_MENU)
async def reply_menu(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_main_menu(message, send=True)


@router.message(StateFilter(None), F.text == BTN_ASK)
async def reply_ask(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await message.answer(
        "○─── ☾ ───○\n\nНапиши Лане в личные сообщения — она ответит 🤍",
        reply_markup=ask_lana_kb(),
    )
