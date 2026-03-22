from aiogram import F, Router
from aiogram.types import CallbackQuery

from keyboards.inline import back_to_menu_kb

router = Router()

ABOUT_TEXT = (
    "🔍 <b>Обо мне</b>\n\n"
    "Я — эксперт с многолетним опытом работы. "
    "Моя методология основана на индивидуальном подходе к каждому клиенту.\n\n"
    "📌 <b>Кейсы:</b>\n"
    "• Клиент А — увеличение продаж на 40%\n"
    "• Клиент Б — выход из кризиса за 3 месяца\n"
    "• Клиент В — масштабирование бизнеса x2\n\n"
    "Готов записаться на консультацию? Нажми кнопку ниже!"
)

PRODUCTS_TEXT = (
    "📦 <b>Дополнительные продукты</b>\n\n"
    "1️⃣ <b>Мини-курс «Основы»</b>\n"
    "Базовый курс для новичков. Идеально для старта.\n\n"
    "2️⃣ <b>Гайд «Пошаговый план»</b>\n"
    "Пошаговая инструкция для самостоятельной работы.\n\n"
    "3️⃣ <b>Интенсив «Прорыв»</b>\n"
    "Глубокая групповая программа с обратной связью.\n\n"
    "Для покупки или подробной информации свяжитесь со мной "
    "через запись на консультацию."
)


@router.callback_query(F.data == "info")
async def cb_info(callback: CallbackQuery) -> None:
    await callback.message.edit_text(ABOUT_TEXT, reply_markup=back_to_menu_kb())
    await callback.answer()


@router.callback_query(F.data == "products")
async def cb_products(callback: CallbackQuery) -> None:
    await callback.message.edit_text(PRODUCTS_TEXT, reply_markup=back_to_menu_kb())
    await callback.answer()
