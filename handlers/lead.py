import logging

from aiogram import Bot, F, Router, html
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, User as TgUser

from database import Lead, get_session
from keyboards.inline import lead_cancel_kb, lead_contact_kb, lead_done_kb

router = Router()
logger = logging.getLogger(__name__)

PRODUCTS = {
    "consultation": "Консультация «Точка сборки»",
    "mentoring": "Менторство (4 недели)",
}


class LeadForm(StatesGroup):
    name = State()
    request = State()
    contact = State()


@router.callback_query(F.data.startswith("lead_start:"))
async def cb_lead_start(callback: CallbackQuery, state: FSMContext) -> None:
    product = callback.data.split(":", 1)[1]
    if product not in PRODUCTS:
        return
    await state.set_state(LeadForm.name)
    await state.update_data(product=product)
    await callback.message.answer(
        "○─── ☾ ───○\n\n"
        f"<b>✦ Заявка: {PRODUCTS[product]}</b>\n\n"
        "Как тебя зовут?",
        reply_markup=lead_cancel_kb(),
    )


@router.callback_query(F.data == "lead_cancel", StateFilter("*"))
async def cb_lead_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(
        "Хорошо, заявка отменена ✦\n"
        "Если появятся вопросы — я всегда здесь 🤍",
        reply_markup=lead_done_kb(),
    )


@router.message(LeadForm.name, F.text)
async def lead_name(message: Message, state: FSMContext) -> None:
    await state.update_data(name=message.text.strip()[:255])
    await state.set_state(LeadForm.request)
    await message.answer(
        "Опиши кратко свой запрос — с чем хочешь поработать?",
        reply_markup=lead_cancel_kb(),
    )


@router.message(LeadForm.request, F.text)
async def lead_request(message: Message, state: FSMContext) -> None:
    await state.update_data(request=message.text.strip())
    await state.set_state(LeadForm.contact)
    await message.answer(
        "Как с тобой удобнее связаться?\n"
        "Напиши номер телефона или ник в Telegram ⇩",
        reply_markup=lead_contact_kb(bool(message.from_user.username)),
    )


@router.message(LeadForm.contact, F.text)
async def lead_contact(
    message: Message, state: FSMContext, bot: Bot, admin_ids: list[int]
) -> None:
    await _finish_lead(
        message.from_user, message.text.strip()[:255], message, state, bot, admin_ids
    )


@router.callback_query(LeadForm.contact, F.data == "lead_use_tg")
async def cb_lead_use_tg(
    callback: CallbackQuery, state: FSMContext, bot: Bot, admin_ids: list[int]
) -> None:
    user = callback.from_user
    contact = f"@{user.username}" if user.username else f"id {user.id}"
    await _finish_lead(user, contact, callback.message, state, bot, admin_ids)


@router.message(StateFilter(LeadForm))
async def lead_non_text(message: Message) -> None:
    await message.answer(
        "Пожалуйста, отправь обычное текстовое сообщение ✦",
        reply_markup=lead_cancel_kb(),
    )


async def _finish_lead(
    tg_user: TgUser,
    contact: str,
    reply_to: Message,
    state: FSMContext,
    bot: Bot,
    admin_ids: list[int],
) -> None:
    data = await state.get_data()
    await state.clear()

    product = PRODUCTS.get(data.get("product"), "—")
    name = data.get("name", "—")
    request_text = f"[{product}] {data.get('request', '—')}"[:2000]

    async with get_session() as session:
        session.add(
            Lead(
                telegram_id=tg_user.id,
                name=name,
                contact_info=contact,
                request_text=request_text,
            )
        )
        await session.commit()

    await reply_to.answer(
        "○─── ☾ ───○\n\n"
        f"✦ Спасибо, {html.quote(name)}!\n\n"
        "Твоя заявка принята. Лана свяжется с тобой в ближайшее время 🤍",
        reply_markup=lead_done_kb(),
    )

    username = f"@{tg_user.username}" if tg_user.username else "нет username"
    notification = (
        "✦ <b>Новая заявка!</b>\n\n"
        f"<b>Продукт:</b> {product}\n"
        f"<b>Имя:</b> {html.quote(name)}\n"
        f"<b>Запрос:</b> {html.quote(data.get('request', '—'))}\n"
        f"<b>Контакт:</b> {html.quote(contact)}\n"
        f"<b>Профиль:</b> {username} "
        f'(<a href="tg://user?id={tg_user.id}">открыть</a>, id {tg_user.id})'
    )
    for admin_id in admin_ids:
        try:
            await bot.send_message(admin_id, notification)
        except TelegramAPIError:
            logger.warning(
                "Failed to notify admin %s about new lead (бот не может писать "
                "первым — админ должен нажать /start у бота)",
                admin_id,
            )
