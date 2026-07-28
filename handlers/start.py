from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from database import User, get_session
from keyboards.reply import main_reply_kb
from ui import reset_keyboard, show_screen

router = Router()

MAIN_MENU_TEXT = (
    "Это пространство создано для того, чтобы помочь тебе подсветить важное "
    "и найти ответы на свои вопросы 🤍\n\n"
    "Иногда я буду присылать сюда важные обновления, подкасты и материалы, "
    "которые помогут тебе на этом пути.\n\n"
    "С чего начнём? Выбирай нужный раздел ниже ⇩"
)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, bot: Bot) -> None:
    await state.clear()
    async with get_session() as session:
        user = await session.get(User, message.from_user.id)
        if not user:
            user = User(
                telegram_id=message.from_user.id,
                username=message.from_user.username,
                full_name=message.from_user.full_name,
            )
            session.add(user)
        else:
            user.username = message.from_user.username
            user.full_name = message.from_user.full_name
        await session.commit()

    # Нижняя клавиатура — на отдельном якоре (переживает удаление контентных
    # окон), приветствие — обычное контентное окно (без нижней клавиатуры).
    await reset_keyboard(bot, message.chat.id, main_reply_kb())
    await show_screen(bot, message.chat.id, MAIN_MENU_TEXT)


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(f"Твой Telegram ID: <code>{message.from_user.id}</code>")


@router.callback_query(F.data == "start_menu")
async def cb_start_menu(callback: CallbackQuery, state: FSMContext, bot: Bot) -> None:
    # «В меню»/«Назад» убирают текущий экран и показывают приветствие новым
    # сообщением (единое окно на чат). Нижняя клавиатура держится на якоре
    # (см. reset_keyboard на /start), поэтому здесь её вешать не нужно.
    await state.clear()
    await show_screen(bot, callback.message.chat.id, MAIN_MENU_TEXT)
