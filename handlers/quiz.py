from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from keyboards.inline import quiz_intro_kb, quiz_question_kb, quiz_result_kb
from quiz_data import INTRO_TEXT, QUESTIONS, result_for_score

router = Router()


class Quiz(StatesGroup):
    in_progress = State()


def _question_text(idx: int) -> str:
    q = QUESTIONS[idx]
    return (
        f"Вопрос {idx + 1}/{len(QUESTIONS)}\n\n"
        f"{q['text']}"
    )


async def _show_question(callback: CallbackQuery, idx: int) -> None:
    await callback.message.edit_text(
        _question_text(idx),
        reply_markup=quiz_question_kb(QUESTIONS[idx]["options"], is_first=(idx == 0)),
    )


@router.callback_query(F.data == "quiz_intro")
async def cb_quiz_intro(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(INTRO_TEXT, reply_markup=quiz_intro_kb())


@router.callback_query(F.data == "quiz_begin")
async def cb_quiz_begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Quiz.in_progress)
    await state.update_data(answers={}, idx=0)
    await _show_question(callback, 0)


@router.callback_query(Quiz.in_progress, F.data.startswith("quiz_ans:"))
async def cb_quiz_answer(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        score = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    if not 1 <= score <= 4:
        return
    data = await state.get_data()
    answers = dict(data.get("answers", {}))
    idx = data.get("idx", 0)
    answers[idx] = score

    if idx + 1 < len(QUESTIONS):
        idx += 1
        await state.update_data(answers=answers, idx=idx)
        await _show_question(callback, idx)
    else:
        total = sum(answers.values())
        await state.clear()
        _, _, body = result_for_score(total)
        await callback.message.edit_text(body, reply_markup=quiz_result_kb())


@router.callback_query(Quiz.in_progress, F.data == "quiz_back")
async def cb_quiz_back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    idx = data.get("idx", 0)
    if idx == 0:
        return
    idx -= 1
    await state.update_data(idx=idx)
    await _show_question(callback, idx)
