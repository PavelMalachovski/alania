from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import channel_kb, game_kb, gift_kb

router = Router()

GAME_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>♡ VECHNOST</b>\n\n"
    "Если ты:\n"
    "☆ снова выбираешь «не того» человека\n"
    "☆ чувствуешь, что в отношениях стало скучно\n"
    "☆ или хочешь понимать партнёра лучше\n\n"
    "VECHNOST — это не просто игра.\n"
    "Это инструмент, основанный на:\n"
    "✦ психологии привязанности\n"
    "✦ поведенческих сценариях\n"
    "✦ глубинной коммуникации\n\n"
    "300+ терапевтических вопросов и заданий, разделенных на 4 уровня, "
    "которые показывают, как человек думает и строит отношения "
    "уже с самого начала общения.\n\n"
    "● подробнее — в хайлайте игра"
)

CHANNEL_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>☾ Бесплатный Telegram-канал</b>\n\n"
    "В своём канале я делюсь ченнелингами, энергиями месяца, "
    "полезными материалами и практиками.\n\n"
    "Они помогут тебе гармонизировать состояние и, возможно, найти ответы "
    "на вопросы даже раньше, чем они у тебя возникнут ✧"
)

GIFT_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>✦ Получить подарок</b>\n\n"
    "Рада, что ты решила забрать этот инструмент! "
    "Работа над собой — непростой путь, а наше подсознание зачастую "
    "прячет от нас реальные причины проблем.\n\n"
    "Просто сесть и подумать может быть недостаточно. Нужно задать себе именно "
    "те «правильные» вопросы, на которые тело и психика готовы дать честный ответ.\n\n"
    "Я создала для тебя «Карту твоего запроса» — гайд, который поможет "
    "сформулировать истинный запрос для дальнейшего пути самопознания. "
    "По сути, это техническое задание для тебя или специалиста, "
    "с которым ты захочешь дальше поработать.\n\n"
    "А ещё это часть моей работы с клиентами — именно на основе этого гайда "
    "мы формируем запрос для консультаций и менторства ♡"
)


@router.callback_query(F.data == "game")
async def cb_game(callback: CallbackQuery) -> None:
    await callback.message.edit_text(GAME_TEXT, reply_markup=game_kb())
    await callback.answer()


@router.callback_query(F.data == "channel")
async def cb_channel(callback: CallbackQuery) -> None:
    await callback.message.edit_text(CHANNEL_TEXT, reply_markup=channel_kb())
    await callback.answer()


@router.callback_query(F.data == "gift")
async def cb_gift(callback: CallbackQuery) -> None:
    await callback.message.edit_text(GIFT_TEXT, reply_markup=gift_kb())
    await callback.answer()
