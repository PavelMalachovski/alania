from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_BOOK = "📅 Записаться"
BTN_MY = "📋 Мои записи"
BTN_MENU = "🏠 Меню"
BTN_ASK = "💬 Вопрос Лане"


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_MENU), KeyboardButton(text=BTN_ASK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
