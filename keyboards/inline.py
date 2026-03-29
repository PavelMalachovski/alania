from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Внешние ссылки ───────────────────────────────────────────────────
DM_URL = "https://t.me/LanaLeonovich"
PAY_RUB_URL = "https://web.tribute.tg/p/rTr"
PAY_EUR_URL = "https://web.tribute.tg/p/tse"
GAME_URL = "https://t.me/tvoya_vechnost_bot"
CHANNEL_URL = "https://t.me/+yL84pnnJCUNlZjJk"
GUIDE_URL = "https://t.me/c/2260920571/433"


def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Узнать больше о личной работе", callback_data="personal_work")
    builder.button(text="Узнать больше про игру VECHNOST", callback_data="game")
    builder.button(text="Войти в бесплатный Telegram-канал", callback_data="channel")
    builder.button(text="Получить гайд «карта твоего запроса»", callback_data="gift")
    builder.adjust(1)
    return builder.as_markup()


def personal_work_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Личная консультация «Точка сборки»", callback_data="consultation")
    builder.button(text="Менторство (4 недели)", callback_data="mentoring")
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def consultation_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Кому подойдет?", callback_data="consultation_who")
    builder.button(text="Как проходит сессия?", callback_data="consultation_how")
    builder.button(text="Отзывы", callback_data="consultation_reviews")
    builder.button(text="Записаться", callback_data="consultation_pay")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="personal_work")
    builder.adjust(1)
    return builder.as_markup()


def consultation_pay_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить в рублях", url=PAY_RUB_URL)
    builder.button(text="Оплатить в евро", url=PAY_EUR_URL)
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(1)
    return builder.as_markup()


def consultation_sub_kb(back_to: str = "consultation"):
    builder = InlineKeyboardBuilder()
    builder.button(text="Записаться", callback_data="consultation_pay")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def consultation_how_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Забрать гайд", url=GUIDE_URL)
    builder.button(text="Записаться", callback_data="consultation_pay")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(1)
    return builder.as_markup()


def mentoring_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Узнать больше в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="personal_work")
    builder.adjust(1)
    return builder.as_markup()


def game_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Перейти к игре", url=GAME_URL)
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def channel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Войти в канал", url=CHANNEL_URL)
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def gift_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Забрать гайд", url=GUIDE_URL)
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def reviews_kb(page: int, total: int):
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред.", callback_data=f"review_{page - 1}")
    if page < total - 1:
        builder.button(text="➡️ След.", callback_data=f"review_{page + 1}")
    builder.button(text="Записаться", callback_data="consultation_pay")
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(2, 1, 1)
    return builder.as_markup()
