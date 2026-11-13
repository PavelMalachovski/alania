"""Оплата через lava.top: валюта → email (один раз) → счёт → ссылка на оплату.

callback_data:
  lava_pay:<product>:<RUB|EUR>:<booking_id>   выставить счёт (email уже есть
                                              — сразу, нет — сначала спросить)
  lava_email:<product>:<RUB|EUR>:<booking_id> сменить email и выставить счёт
  lava_back:<product>:<booking_id>            назад к экрану продукта
  lava_check:<payment_id>                     «✓ Я оплатил(а)» — проверить сейчас
  lava_ok:<health|waiver>:<product>:<RUB|EUR>:<booking_id>  подтверждение
product: session (booking_id — запись в held) / course / game (booking_id 0).

Перед счётом — отдельные подтверждения (оферта п. 7.2.1, согласие, ст. 9
GDPR), каждое своей кнопкой: согласие на сведения о состоянии — один раз,
для сессии и курса (User.health_consent_at); просьба начать до истечения
14 дней — под каждый заказ: живёт в FSM-данных (waivers, ключ
<product>:<booking_id>, CONSENT_TTL) и переносится в Payment.waiver_at при
выставлении счёта. Поэтому ниже FSM сбрасываем set_state(None), а не clear():
clear() стёр бы и подтверждение.

Ввод email — FSM PayForm.email по паттерну «якорь» (как причина переноса):
id экрана лежит в FSM, ответ клиента удаляется, экран редактируется на месте.
Оплату подтверждает фоновая проверка (payments.py), кнопка лишь ускоряет."""

import logging
import re
from datetime import datetime, timedelta, timezone

from aiogram import Bot, F, Router, html
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, LinkPreviewOptions, Message

from booking_config import BookingConfig
from database import Booking, Payment, User, get_session
from formatting import format_slot_human
from google_calendar import GoogleCalendar
from handlers.booking import pay_screen_text
from handlers.info import COURSE_TEXT, GAME_TEXT
from keyboards.inline import (
    LEGAL_OFFER_URL,
    LEGAL_PRIVACY_URL,
    booking_error_kb,
    booking_pay_kb,
    course_kb,
    game_kb,
    lava_email_kb,
    lava_consent_kb,
    lava_error_kb,
    lava_invoice_kb,
)
from lava import CURRENCIES, OFFERS, LavaClient, LavaError
# модулем, а не именами: payments импортирует handlers.booking, и при
# импорте payments первым имена отсюда ещё не существовали бы (цикл)
import payments as pay
from ui import delete_safe, edit_screen

router = Router()
logger = logging.getLogger(__name__)

# Только латиница: lava.top кириллицу в адресе не принимает, а на русской
# раскладке в «gmail» легко попадает кириллическая «а» — снаружи не отличить.
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+'-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
EMAIL_LATIN_HINT = (
    "Адрес нужен латиницей — проверь, что клавиатура английская "
    "(русская «а», «о» или «с» выглядят так же, но lava.top их не примет)."
)

_NO_PREVIEW = LinkPreviewOptions(is_disabled=True)

EMAIL_PROMPT_TEXT = (
    "<b>✦ Почта для оплаты</b>\n\n"
    "Напиши свой email одним сообщением ⇩\n"
    "На него lava.top пришлёт чек{access}. Запомню его для следующих оплат."
)
EMAIL_RETRY_TEXT = (
    "<b>✦ Почта для оплаты</b>\n\n"
    "{reason} Напиши адрес ещё раз, например <code>name@mail.ru</code>, "
    "или нажми «Отмена»."
)
PAY_UNAVAILABLE_TEXT = (
    "Оплата сейчас недоступна 🤍 Попробуй через минуту или напиши Лане "
    "в личку — оплатим вручную."
)
HOLD_EXPIRED_TEXT = (
    "Время брони истекло, и слот мог уйти другому 🤍 Выбери время заново."
)


CONSENT_TTL = timedelta(hours=1)
HEALTH_PRODUCTS = ("session", "course")

CONSENT_HEALTH_TEXT = (
    "Я даю явное согласие на обработку сведений о моём психологическом и "
    "физическом состоянии, которые я сообщаю в ходе консультаций, в целях "
    "оказания услуг в соответствии с "
    f'<a href="{LEGAL_PRIVACY_URL}">Политикой конфиденциальности</a>. Я знаю, '
    "что могу отозвать это согласие в любой момент."
)
CONSENT_WAIVER_TEXT = (
    "Я прошу начать оказание услуги до истечения 14 дней со дня заключения "
    "договора и понимаю, что после полного оказания услуги (а для цифровых "
    "материалов — после предоставления доступа) я теряю право на отказ от "
    "договора без объяснения причин "
    f'(<a href="{LEGAL_OFFER_URL}">Публичная оферта</a>, п. 7.2).'
)


class PayForm(StatesGroup):
    email = State()


def _parse(data: str, parts: int):
    """«lava_x:a:b:…» → список значений после префикса или None."""
    values = data.split(":")[1:]
    return values if len(values) == parts else None


def _parse_pay(data: str):
    """(product, currency, booking_id) из lava_pay/lava_email или None."""
    values = _parse(data, 3)
    if not values:
        return None
    product, currency, bid = values
    if product not in OFFERS or currency not in CURRENCIES or not bid.isdigit():
        return None
    booking_id = int(bid)
    if (product == "session") != (booking_id > 0):
        return None
    return product, currency, booking_id


def _as_utc(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


async def _held_slot(tg_id: int, booking_id: int):
    """(slot, held_until) своей неистёкшей брони или текст отказа."""
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
    if not booking or booking.telegram_id != tg_id:
        return "Запись не найдена"
    if booking.status != "held":
        return "Эта запись уже обработана 🤍"
    held_until = _as_utc(booking.held_until)
    if held_until <= datetime.now(timezone.utc):
        return HOLD_EXPIRED_TEXT
    return _as_utc(booking.slot_start), held_until


async def _saved_email(tg_id: int) -> str | None:
    async with get_session() as session:
        user = await session.get(User, tg_id)
    return user.email if user else None


async def _save_email(tg_id: int, email: str) -> None:
    async with get_session() as session:
        user = await session.get(User, tg_id)
        if user is None:  # /start не нажимал (пришёл по старой кнопке) — заводим
            user = User(telegram_id=tg_id)
            session.add(user)
        user.email = email
        await session.commit()


def _order_key(product: str, booking_id: int) -> str:
    return f"{product}:{booking_id}"


async def _waiver_at(state: FSMContext, product: str, booking_id: int) -> datetime | None:
    raw = (await state.get_data()).get("waivers", {}).get(_order_key(product, booking_id))
    if not raw:
        return None
    at = datetime.fromisoformat(raw)
    return at if datetime.now(timezone.utc) - at < CONSENT_TTL else None


async def _missing_consents(tg_id: int, state: FSMContext, product: str,
                            booking_id: int) -> list[str]:
    missing = []
    if product in HEALTH_PRODUCTS:
        async with get_session() as session:
            user = await session.get(User, tg_id)
        if not (user and user.health_consent_at):
            missing.append("health")
    if await _waiver_at(state, product, booking_id) is None:
        missing.append("waiver")
    return missing


async def _show_consents(bot: Bot, chat_id: int, message_id: int, product: str,
                         currency: str, booking_id: int, missing: list[str]) -> None:
    items = []
    if "health" in missing:
        items.append(("health", CONSENT_HEALTH_TEXT))
    items.append(("waiver", CONSENT_WAIVER_TEXT))
    lines = [f"<b>{i}.</b> {text}" for i, (_, text) in enumerate(items, 1)]
    text = (
        "<b>✦ Перед оплатой</b>\n\n"
        + ("Подтверди, пожалуйста, каждый пункт отдельной кнопкой ⇩\n\n"
           if len(items) > 1 else "Подтверди, пожалуйста, кнопкой ⇩\n\n")
        + "\n\n".join(lines)
    )
    buttons = [(i, kind, kind not in missing) for i, (kind, _) in enumerate(items, 1)]
    await edit_screen(bot, chat_id, message_id, text,
                      lava_consent_kb(buttons, product, currency, booking_id),
                      link_preview_options=_NO_PREVIEW)


def _valid_email(email: str) -> bool:
    return len(email) <= 254 and EMAIL_RE.fullmatch(email) is not None


async def _proceed(bot: Bot, chat_id: int, message_id: int, tg_id: int,
                   state: FSMContext, lava, cfg: BookingConfig,
                   product: str, currency: str, booking_id: int,
                   admin_ids: list[int] | None = None) -> None:
    """Дальше по шагам: подтверждения → email → счёт."""
    missing = await _missing_consents(tg_id, state, product, booking_id)
    if missing:
        await _show_consents(bot, chat_id, message_id, product, currency, booking_id, missing)
        return
    email = await _saved_email(tg_id)
    if email and not _valid_email(email):  # сохранён до проверки на латиницу
        await _ask_email(bot, chat_id, message_id, state, product, currency, booking_id,
                         reason=EMAIL_LATIN_HINT)
        return
    if not email:
        await _ask_email(bot, chat_id, message_id, state, product, currency, booking_id)
        return
    await _issue_invoice(bot, chat_id, message_id, tg_id, state, lava, cfg,
                         product, currency, booking_id, email, admin_ids=admin_ids)


async def _ask_email(bot: Bot, chat_id: int, message_id: int, state: FSMContext,
                     product: str, currency: str, booking_id: int,
                     reason: str | None = None) -> None:
    await state.set_state(PayForm.email)
    await state.update_data(pay=f"{product}:{currency}:{booking_id}",
                            pay_screen_id=message_id)
    if reason:
        text = EMAIL_RETRY_TEXT.format(reason=reason)
    else:
        text = EMAIL_PROMPT_TEXT.format(
            access="" if product == "session" else " и доступ к покупке")
    await edit_screen(bot, chat_id, message_id, text, lava_email_kb(product, booking_id))


async def _issue_invoice(bot: Bot, chat_id: int, message_id: int, tg_id: int,
                         state: FSMContext, lava: LavaClient | None,
                         cfg: BookingConfig, product: str, currency: str,
                         booking_id: int, email: str, *,
                         admin_ids: list[int] | None = None) -> None:
    """Выставить счёт lava.top и показать экран со ссылкой на оплату."""
    missing = await _missing_consents(tg_id, state, product, booking_id)
    if missing:  # без подтверждений счёт не выставляем (оферта п. 7.2.1)
        await _show_consents(bot, chat_id, message_id, product, currency, booking_id, missing)
        return
    waiver_at = await _waiver_at(state, product, booking_id)
    slot = None
    if product == "session":
        held = await _held_slot(tg_id, booking_id)
        if isinstance(held, str):
            await edit_screen(bot, chat_id, message_id, held, booking_error_kb())
            return
        slot, _ = held

    if lava is None:
        logger.error("LAVA_API_KEY не задан — оплата недоступна")
        await edit_screen(bot, chat_id, message_id, PAY_UNAVAILABLE_TEXT,
                          lava_error_kb(product, currency, booking_id))
        return
    try:
        invoice = await lava.create_invoice(email, OFFERS[product], currency)
    except LavaError as e:
        if e.email_invalid:
            await _ask_email(bot, chat_id, message_id, state, product, currency,
                             booking_id, reason="lava.top не принял этот email. "
                             + EMAIL_LATIN_HINT)
            return
        logger.exception("lava.top: не выставил счёт (%s, %s)", product, currency)
        await edit_screen(bot, chat_id, message_id, PAY_UNAVAILABLE_TEXT,
                          lava_error_kb(product, currency, booking_id))
        # Лане — с текстом ошибки: клиент видит только «недоступна», а без
        # причины такой сбой из чата не разобрать
        who = await pay.booking_client_line(tg_id)
        await pay.notify_admins(
            bot, admin_ids or [],
            "⚠️ <b>Клиент не смог оплатить: lava.top не выставил счёт</b>\n\n"
            f"<b>Продукт:</b> {pay.PRODUCT_TITLES[product]} ({currency})\n"
            f"<b>Email:</b> {html.quote(email)}\n{who}\n\n"
            f"<code>{html.quote(str(e)[:500])}</code>",
        )
        return

    now = datetime.now(timezone.utc)
    async with get_session() as session:
        if product == "session":
            # счёт выставлен — время держим заново: оплата на стороне lava.top
            # занимает минуты, и холд не должен истечь посреди неё
            booking = await session.get(Booking, booking_id)
            booking.held_until = now + cfg.hold
        payment = Payment(
            telegram_id=tg_id, product=product,
            booking_id=booking_id or None, invoice_id=invoice.id,
            currency=invoice.currency, amount=invoice.amount, email=email,
            status=invoice.status or "new", message_id=message_id,
            waiver_at=waiver_at,
        )
        session.add(payment)
        await session.commit()
        payment_id = payment.id

    money = pay.amount_label(invoice.amount, invoice.currency)
    if product == "session":
        hold_local = (now + cfg.hold).astimezone(cfg.tz)
        text = (
            "<b>✦ Оплата сессии</b>\n\n"
            f"Слот: <b>{format_slot_human(slot)}</b>\n"
            f"Сумма: <b>{money}</b>\n"
            f"Чек придёт на: {html.quote(email)}\n\n"
            f"Время держим до {hold_local:%H:%M} (Прага). Оплати по кнопке ⇩ — "
            "как только платёж пройдёт, запись подтвердится сама и придёт "
            "сообщение."
        )
    else:
        text = (
            f"<b>✦ Оплата: {pay.PRODUCT_TITLES[product]}</b>\n\n"
            f"Сумма: <b>{money}</b>\n"
            f"Доступ и чек придут на: {html.quote(email)}\n\n"
            "Оплати по кнопке ⇩ — как только платёж пройдёт, я напишу."
        )
    await edit_screen(bot, chat_id, message_id, text,
                      lava_invoice_kb(invoice.payment_url, money, payment_id,
                                      product, currency, booking_id))


@router.callback_query(F.data.startswith("lava_pay:"))
async def cb_lava_pay(callback: CallbackQuery, bot: Bot, state: FSMContext,
                      booking_config: BookingConfig,
                      admin_ids: list[int] | None = None,
                      lava: LavaClient | None = None) -> None:
    parsed = _parse_pay(callback.data)
    if parsed is None:
        await callback.answer("Не понял, что оплатить", show_alert=True)
        return
    product, currency, booking_id = parsed
    tg_id = callback.from_user.id
    if product == "session":
        held = await _held_slot(tg_id, booking_id)
        if isinstance(held, str):
            await callback.answer(held, show_alert=True)
            return
    await _proceed(bot, callback.message.chat.id, callback.message.message_id, tg_id,
                   state, lava, booking_config, product, currency, booking_id,
                   admin_ids=admin_ids)


@router.callback_query(F.data.startswith("lava_ok:"))
async def cb_lava_ok(callback: CallbackQuery, bot: Bot, state: FSMContext,
                     booking_config: BookingConfig,
                     admin_ids: list[int] | None = None,
                     lava: LavaClient | None = None) -> None:
    """Одно подтверждение = одно нажатие. Записываем момент и идём дальше:
    остались неподтверждённые — тот же экран, нет — к email/счёту."""
    values = _parse(callback.data, 4)
    kind = values[0] if values else None
    parsed = _parse_pay("lava_ok:" + ":".join(values[1:])) if values else None
    if kind not in ("health", "waiver") or parsed is None:
        await callback.answer("Не понял подтверждение", show_alert=True)
        return
    product, currency, booking_id = parsed
    tg_id = callback.from_user.id
    now = datetime.now(timezone.utc)
    if kind == "health":
        async with get_session() as session:
            user = await session.get(User, tg_id)
            if user is None:
                user = User(telegram_id=tg_id)
                session.add(user)
            user.health_consent_at = user.health_consent_at or now
            await session.commit()
    else:
        waivers = dict((await state.get_data()).get("waivers", {}))
        waivers[_order_key(product, booking_id)] = now.isoformat()
        await state.update_data(waivers=waivers)
    await _proceed(bot, callback.message.chat.id, callback.message.message_id, tg_id,
                   state, lava, booking_config, product, currency, booking_id,
                   admin_ids=admin_ids)


@router.callback_query(F.data.startswith("lava_email:"))
async def cb_lava_email(callback: CallbackQuery, bot: Bot, state: FSMContext) -> None:
    parsed = _parse_pay(callback.data)
    if parsed is None:
        await callback.answer("Не понял, что оплатить", show_alert=True)
        return
    product, currency, booking_id = parsed
    await _ask_email(bot, callback.message.chat.id, callback.message.message_id,
                     state, product, currency, booking_id)


@router.message(PayForm.email)
async def on_email(message: Message, bot: Bot, state: FSMContext,
                   booking_config: BookingConfig,
                   admin_ids: list[int] | None = None,
                   lava: LavaClient | None = None) -> None:
    data = await state.get_data()
    chat_id = message.chat.id
    screen_id = data.get("pay_screen_id")
    product, currency, bid = data.get("pay", "::").split(":")
    await delete_safe(bot, chat_id, message.message_id)
    if not screen_id or product not in OFFERS:
        await state.set_state(None)
        return
    email = (message.text or "").strip()
    if not _valid_email(email):
        reason = ("Это не похоже на email." if "@" not in email
                  else "Не получилось разобрать адрес. " + EMAIL_LATIN_HINT)
        await edit_screen(bot, chat_id, screen_id,
                          EMAIL_RETRY_TEXT.format(reason=reason),
                          lava_email_kb(product, int(bid)))
        return
    await state.set_state(None)
    await _save_email(message.from_user.id, email)
    await _issue_invoice(bot, chat_id, screen_id, message.from_user.id, state, lava,
                         booking_config, product, currency, int(bid), email,
                         admin_ids=admin_ids)


@router.callback_query(F.data.startswith("lava_back:"))
async def cb_lava_back(callback: CallbackQuery, state: FSMContext,
                       booking_config: BookingConfig) -> None:
    """Назад к экрану продукта — из ввода email (FSM сбрасываем) и со счёта."""
    await state.set_state(None)
    values = _parse(callback.data, 2)
    if not values or values[0] not in OFFERS or not values[1].isdigit():
        await callback.answer("Не понял, куда вернуться", show_alert=True)
        return
    product, booking_id = values[0], int(values[1])
    if product == "course":
        await callback.message.edit_text(COURSE_TEXT, reply_markup=course_kb())
    elif product == "game":
        await callback.message.edit_text(GAME_TEXT, reply_markup=game_kb())
    else:
        held = await _held_slot(callback.from_user.id, booking_id)
        if isinstance(held, str):
            await callback.message.edit_text(held, reply_markup=booking_error_kb())
            return
        slot, held_until = held
        await callback.message.edit_text(
            pay_screen_text(slot, held_until.astimezone(booking_config.tz)),
            reply_markup=booking_pay_kb(booking_id),
            link_preview_options=_NO_PREVIEW,
        )


@router.callback_query(F.data.startswith("lava_check:"))
async def cb_lava_check(callback: CallbackQuery, bot: Bot, admin_ids: list[int],
                        gcal: GoogleCalendar, booking_config: BookingConfig,
                        lava: LavaClient | None = None) -> None:
    values = _parse(callback.data, 1)
    if not values or not values[0].isdigit():
        await callback.answer("Не понял счёт", show_alert=True)
        return
    payment_id = int(values[0])
    async with get_session() as session:
        payment = await session.get(Payment, payment_id)
    if not payment or payment.telegram_id != callback.from_user.id:
        await callback.answer("Счёт не найден", show_alert=True)
        return
    if lava is None:
        await callback.answer(PAY_UNAVAILABLE_TEXT, show_alert=True)
        return
    status = await pay.check_payment(bot, admin_ids, gcal, booking_config, lava, payment_id)
    if status == "completed":
        await callback.answer("Оплата получена 🤍")
    elif status == "pending":
        await callback.answer(
            "Оплата пока не поступила. Если ты уже оплатил(а) — подожди минуту: "
            "я проверю сам и напишу, как только она придёт 🤍",
            show_alert=True,
        )
    else:
        await callback.answer(
            "Этот счёт не оплачен и больше не активен. Нажми «⇦ Назад» и "
            "выбери валюту заново 🤍",
            show_alert=True,
        )
