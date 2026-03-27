from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from database import User, get_session
from keyboards.inline import main_menu_kb, welcome_kb

router = Router()

WELCOME_TEXT = (
    "Привет, дорогая! 🤍\n\n"
    "Этот бот создан для того, чтобы помочь тебе соединиться с собой, "
    "найти ответы на важные вопросы и получить поддержку на твоем пути самопознания.\n\n"
    "Чтобы начать наше знакомство и узнать про полезные инструменты, "
    "с помощью которых это можно сделать, нажми кнопку ниже."
)

MAIN_MENU_TEXT = (
    "Привет! 👋\n"
    "Я приветствую тебя в этом боте.\n"
    "Моя задача — сделать твой путь к себе максимально удобным и глубоким.\n\n"
    "Не пугайся, иногда (если ты не против) я буду присылать тебе полезную информацию, "
    "свежие новости и подкасты, которые Лана будет записывать специально для тебя.\n\n"
    "А теперь выбери, с чего ты хочешь начать и с чем мне помочь тебе в первую очередь?"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
            session.add(user)
            await session.commit()

    await message.answer(WELCOME_TEXT, reply_markup=welcome_kb())


@router.callback_query(lambda c: c.data == "start_menu")
async def cb_start_menu(callback: CallbackQuery) -> None:
    await callback.message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
