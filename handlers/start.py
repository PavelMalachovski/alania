from aiogram import Router
from aiogram.filters import CommandStart
from aiogram.types import CallbackQuery, Message

from database import User, get_session
from keyboards.inline import main_menu_kb

router = Router()

MAIN_MENU_TEXT = (
    "○─── ☾ ───○\n\n"
    "Я приветствую тебя в этом боте 🤍\n"
    "Моя задача — сделать твой путь к себе максимально удобным и глубоким.\n\n"
    "● Не пугайся, иногда (если ты не против) я буду присылать тебе полезную информацию, "
    "свежие новости и подкасты, которые Лана будет записывать специально для тебя.\n\n"
    "А теперь выбери, с чего ты хочешь начать ⇩"
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

    await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_kb())


@router.callback_query(lambda c: c.data == "start_menu")
async def cb_start_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
    await callback.answer()
