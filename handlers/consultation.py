from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import (
    consultation_kb,
    consultation_sub_kb,
    mentoring_kb,
    personal_work_kb,
)

router = Router()

PERSONAL_WORK_TEXT = (
    "В личной работе я использую комплексный подход, работая сразу на нескольких уровнях: "
    "тело, энергия и подсознание. Это позволяет достигать фундаментальных изменений и менять "
    "не только состояние, но и логику выбора, которая в дальнейшем меняет результат и влияет "
    "на состояние получением релевантного и желаемого опыта.\n\n"
    "Выбери подходящий тебе формат:"
)

CONSULTATION_TEXT = (
    "<b>Личная консультация «Точка сборки»</b>\n\n"
    "Личная консультация «Точка сборки» — это глубокое погружение через соединение "
    "нескольких форматов.\n\n"
    "Я работаю с тобой через ченнелинг, помогая найти ответы на твои вопросы "
    "и внедрить в жизнь новые действия используя коучинговые инструменты.\n\n"
    "Сессия длится 70–90 минут и проходит онлайн (видеозвонок).\n"
    "Стоимость: 111 евро.\n\n"
    "Во время встречи мы можем разобрать один или несколько запросов. "
    "Ты получишь конкретные рекомендации, практики и методы, которые дадут "
    "новый результат в жизни."
)

CONSULTATION_WHO_TEXT = (
    "<b>🎯 Кому подойдет?</b>\n\n"
    "Этот формат для тебя, если ты:\n\n"
    "• Выгорела и не можешь найти ответы на свои вопросы.\n"
    "• Потерялась и не знаешь, куда дальше двигаться.\n"
    "• Устала прорабатывать одни и те же травмы и повторяющиеся ситуации.\n"
    "• Чувствуешь, что способна на большее, но не понимаешь как его достичь "
    "и какое твое предназначение.\n"
    "• Знаешь, что нужно делать, но не можешь начать.\n"
    "• Хочешь научиться легкости и получить ясность в жизни."
)

CONSULTATION_HOW_TEXT = (
    "<b>🔄 Как проходит сессия?</b>\n\n"
    "Сессия проходит онлайн через видеосвязь.\n"
    "Длительность: 70–90 минут.\n\n"
    "Мы работаем на нескольких уровнях: тело, психика и энергии. "
    "Я отвечаю на твои вопросы через ченнелинг, мы разбираем твой запрос или проблему, "
    "находя не только ответы на вопросы, но и выстраивая новую стратегию действия.\n\n"
    "<b>Важно:</b> Для эффективной работы у тебя должен быть сформирован запрос. "
    "Если его нет — мы сформируем его на встрече, либо я рекомендую тебе сначала "
    "забрать мой бесплатный гайд «Карта запроса» в главном меню — "
    "он идеально помогает выявить ключевые темы.\n\n"
    "После сессии я даю рекомендации и практики, которые составляю специально для тебя, "
    "чтобы закрепить полученный эффект и результат."
)

CONSULTATION_REVIEWS_TEXT = (
    "<b>💬 Отзывы</b>\n\n"
    "Раздел отзывов скоро будет дополнен."
)

MENTORING_TEXT = (
    "<b>Личное менторство (4 недели)</b>\n\n"
    "Личное менторство — это программа для тех, кто готов к кардинальным, "
    "фундаментальным изменениям.\n\n"
    "Часто нам не хватает не просто информации и ответов на вопросы, "
    "а помощи и поддержки в том, чтобы внедрить новые привычки в ежедневную жизнь, "
    "научиться не просто получать вдохновение, но и реализовывать то, "
    "что мы давно задумали, но никак не могли начать.\n\n"
    "<b>Что тебя ждет:</b>\n"
    "• 4 глубокие терапевтические встречи (каждая по ~2 часа).\n"
    "• Сопровождение и поддержка в личных сообщениях по возникающим вопросам "
    "между сессиями.\n"
    "• Домашние задания, чтобы ты не сбилась с пути и встроила в жизнь "
    "новый способ мышления.\n\n"
    "Мы перестраиваем старую логику выбора и действия, которые больше не работают, "
    "и формируем новые паттерны поведения и привычки.\n\n"
    "Работа идет на всех уровнях: энергия, психика, тело.\n\n"
    "Для тех, кому нужны не разовые решения, а новая жизнь и индивидуальный подход, "
    "созданный именно под твой запрос."
)


@router.callback_query(F.data == "personal_work")
async def cb_personal_work(callback: CallbackQuery) -> None:
    await callback.message.edit_text(PERSONAL_WORK_TEXT, reply_markup=personal_work_kb())
    await callback.answer()


@router.callback_query(F.data == "consultation")
async def cb_consultation(callback: CallbackQuery) -> None:
    await callback.message.edit_text(CONSULTATION_TEXT, reply_markup=consultation_kb())
    await callback.answer()


@router.callback_query(F.data == "consultation_who")
async def cb_consultation_who(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        CONSULTATION_WHO_TEXT, reply_markup=consultation_sub_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "consultation_how")
async def cb_consultation_how(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        CONSULTATION_HOW_TEXT, reply_markup=consultation_sub_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "consultation_reviews")
async def cb_consultation_reviews(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        CONSULTATION_REVIEWS_TEXT, reply_markup=consultation_sub_kb()
    )
    await callback.answer()


@router.callback_query(F.data == "mentoring")
async def cb_mentoring(callback: CallbackQuery) -> None:
    await callback.message.edit_text(MENTORING_TEXT, reply_markup=mentoring_kb())
    await callback.answer()
