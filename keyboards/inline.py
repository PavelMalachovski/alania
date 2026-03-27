from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Внешние ссылки (замените на актуальные) ──────────────────────────
BOOKING_URL = "https://t.me/lana_leonovich"
DM_URL = "https://t.me/lana_leonovich"
GAME_URL = "https://t.me/lana_leonovich"
CHANNEL_URL = "https://t.me/lana_leonovich"
GUIDE_URL = "https://t.me/lana_leonovich"


def welcome_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Старт", callback_data="start_menu")
    return builder.as_markup()


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
    builder.button(text="⬅️ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def consultation_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎯 Кому подойдет?", callback_data="consultation_who")
    builder.button(text="🔄 Как проходит сессия?", callback_data="consultation_how")
    builder.button(text="💬 Отзывы", callback_data="consultation_reviews")
    builder.button(text="📅 Записаться", url=BOOKING_URL)
    builder.button(text="❓ Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⬅️ Назад", callback_data="personal_work")
    builder.adjust(1)
    return builder.as_markup()


def consultation_sub_kb(back_to: str = "consultation"):
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Записаться", url=BOOKING_URL)
    builder.button(text="❓ Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⬅️ Назад", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def mentoring_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Записаться", url=BOOKING_URL)
    builder.button(text="❓ Узнать больше в ЛС", url=DM_URL)
    builder.button(text="⬅️ Назад", callback_data="personal_work")
    builder.adjust(1)
    return builder.as_markup()


def game_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Перейти к игре", url=GAME_URL)
    builder.button(text="⬅️ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def channel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📢 Войти в канал", url=CHANNEL_URL)
    builder.button(text="⬅️ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def gift_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="📥 Забрать гайд", url=GUIDE_URL)
    builder.button(text="⬅️ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
