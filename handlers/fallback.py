from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import lead_done_kb

router = Router()

_LOST_TEXT = (
    "○─── ☾ ───○\n\n"
    "Похоже, сессия сбросилась (бот перезапускался) 🤍\n"
    "Начни заново из меню — всё быстро восстановится."
)


@router.callback_query(F.data.startswith("quiz_ans:"))
@router.callback_query(F.data == "quiz_back")
async def cb_lost_quiz(callback: CallbackQuery) -> None:
    await callback.message.edit_text(_LOST_TEXT, reply_markup=lead_done_kb())
