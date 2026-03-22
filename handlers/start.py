from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from database import User, async_session
from keyboards.inline import main_menu_kb

router = Router()

WELCOME_TEXT = (
    "👋 Привет!\n\n"
    "Я бот-помощник, который поможет тебе:\n"
    "• Узнать больше обо мне и моей методологии\n"
    "• Записаться на личную консультацию\n"
    "• Ознакомиться с дополнительными продуктами\n\n"
    "Выбери интересующий пункт ⬇️"
)


@router.message(CommandStart())
async def cmd_start(message: Message) -> None:
    async with async_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
            session.add(user)
            await session.commit()

    await message.answer(WELCOME_TEXT, reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(WELCOME_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
