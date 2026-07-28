from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from booking_config import BookingConfig
from google_calendar import GoogleCalendar
from handlers.booking import open_calendar, open_my_bookings
from handlers.consultation import PERSONAL_WORK_TEXT
from handlers.info import CHANNEL_TEXT, GAME_TEXT
from keyboards.inline import (
    ask_lana_kb,
    channel_kb,
    game_kb,
    personal_work_kb,
    quiz_intro_kb,
)
from keyboards.reply import (
    BTN_ASK,
    BTN_BOOK,
    BTN_CHANNEL,
    BTN_GAME,
    BTN_MY,
    BTN_PERSONAL,
    BTN_QUIZ,
)
from quiz_data import INTRO_TEXT
from ui import clear_screen, delete_safe, show_screen, track_screen

router = Router()

ASK_TEXT = "Напиши Лане в личные сообщения — она ответит 🤍"


# Разделы: тап по нижней кнопке удаляется, предыдущее окно чата убирается,
# показывается новый экран (см. show_screen — единое «окно» на чат).
@router.message(StateFilter(None), F.text == BTN_PERSONAL)
async def reply_personal(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await show_screen(bot, message.chat.id, PERSONAL_WORK_TEXT, personal_work_kb())


@router.message(StateFilter(None), F.text == BTN_GAME)
async def reply_game(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await show_screen(bot, message.chat.id, GAME_TEXT, game_kb())


@router.message(StateFilter(None), F.text == BTN_CHANNEL)
async def reply_channel(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await show_screen(bot, message.chat.id, CHANNEL_TEXT, channel_kb())


@router.message(StateFilter(None), F.text == BTN_QUIZ)
async def reply_quiz(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await show_screen(bot, message.chat.id, INTRO_TEXT, quiz_intro_kb())


@router.message(StateFilter(None), F.text == BTN_BOOK)
async def reply_book(message: Message, gcal: GoogleCalendar,
                     booking_config: BookingConfig, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await clear_screen(bot, message.chat.id)
    sent = await open_calendar(message, gcal, booking_config, send=True)
    track_screen(message.chat.id, sent)


@router.message(StateFilter(None), F.text == BTN_MY)
async def reply_my(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await clear_screen(bot, message.chat.id)
    sent = await open_my_bookings(message, message.from_user.id, send=True)
    track_screen(message.chat.id, sent)


@router.message(StateFilter(None), F.text == BTN_ASK)
async def reply_ask(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await show_screen(bot, message.chat.id, ASK_TEXT, ask_lana_kb())
