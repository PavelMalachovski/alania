from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

from database import Lead, async_session
from keyboards.inline import back_to_menu_kb, main_menu_kb

router = Router()


class ConsultationForm(StatesGroup):
    name = State()
    request_text = State()
    contact_info = State()


@router.callback_query(F.data == "consultation")
async def cb_consultation_start(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(ConsultationForm.name)
    await callback.message.edit_text(
        "📝 <b>Запись на консультацию</b>\n\n"
        "Шаг 1/3: Как тебя зовут?"
    )
    await callback.answer()


@router.message(ConsultationForm.name)
async def process_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text)
    await state.set_state(ConsultationForm.request_text)
    await message.answer(
        f"Приятно познакомиться, {html.bold(html.quote(message.text))}!\n\n"
        "Шаг 2/3: Опиши кратко свой запрос или проблему."
    )


@router.message(ConsultationForm.request_text)
async def process_request(message: Message, state: FSMContext) -> None:
    await state.update_data(request_text=message.text)
    await state.set_state(ConsultationForm.contact_info)
    await message.answer(
        "Шаг 3/3: Укажи удобный способ связи\n"
        "(номер телефона или ник в Telegram)."
    )


@router.message(ConsultationForm.contact_info)
async def process_contact(
    message: Message, state: FSMContext, bot: Bot, admin_id: int
) -> None:
    data = await state.get_data()
    await state.clear()

    async with async_session() as session:
        lead = Lead(
            telegram_id=message.from_user.id,
            name=data["name"],
            request_text=data["request_text"],
            contact_info=message.text,
        )
        session.add(lead)
        await session.commit()

    await message.answer(
        "✅ Отлично! Твоя заявка принята.\n"
        "Я свяжусь с тобой в ближайшее время!",
        reply_markup=back_to_menu_kb(),
    )

    # Уведомление администратору
    admin_text = (
        "🔔 <b>Новая заявка на консультацию!</b>\n\n"
        f"👤 Имя: {html.quote(data['name'])}\n"
        f"📩 Контакт: {html.quote(message.text)}\n"
        f"📝 Запрос: {html.quote(data['request_text'])}\n"
        f"🆔 Telegram ID: {message.from_user.id}"
    )
    await bot.send_message(admin_id, admin_text)
