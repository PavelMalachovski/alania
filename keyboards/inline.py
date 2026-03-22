from aiogram.utils.keyboard import InlineKeyboardBuilder


def main_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="ℹ️ Узнать больше", callback_data="info")
    builder.button(text="📝 Запись на консультацию", callback_data="consultation")
    builder.button(text="📦 Другие продукты", callback_data="products")
    builder.adjust(1)
    return builder.as_markup()


def back_to_menu_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="⬅️ Главное меню", callback_data="main_menu")
    return builder.as_markup()
