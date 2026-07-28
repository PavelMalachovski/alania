from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

# Разделы вынесены в нижнюю (persistent) клавиатуру — тексты совпадают с
# заголовками экранов, без цветных эмодзи (см. конвенцию в CLAUDE.md).
BTN_PERSONAL = "О личной работе"
BTN_GAME = "Игра VECHNOST"
BTN_CHANNEL = "Бесплатный Telegram-канал"
BTN_QUIZ = "Тест «Кто управляет твоей жизнью?»"
BTN_MY = "Мои записи"
BTN_BOOK = "Записаться"
BTN_ASK = "Вопрос Лане"


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_PERSONAL), KeyboardButton(text=BTN_GAME)],
            [KeyboardButton(text=BTN_CHANNEL), KeyboardButton(text=BTN_QUIZ)],
            [KeyboardButton(text=BTN_MY), KeyboardButton(text=BTN_BOOK)],
            [KeyboardButton(text=BTN_ASK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
