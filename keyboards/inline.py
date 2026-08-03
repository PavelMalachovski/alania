import calendar as _calendar
from datetime import date as _date

from aiogram.types import CopyTextButton
from aiogram.utils.keyboard import InlineKeyboardBuilder

from formatting import CRYPTO_ADDRESS

# ── Внешние ссылки ───────────────────────────────────────────────────
DM_URL = "https://t.me/LanaLeonovich"
PAY_RUB_URL = "https://web.tribute.tg/p/rTr"
PAY_EUR_URL = "https://web.tribute.tg/p/tse"
GAME_URL = "https://t.me/tvoya_vechnost_bot"
CHANNEL_URL = "https://t.me/+yL84pnnJCUNlZjJk"

# Юр. документы на сайте. SITE_URL — заглушка: сайт лежит в web/, но домен
# ещё не выкачен. Когда выкатится — правится одна строка (пути к страницам
# уже совпадают с web/legal/). Дисклеймера по крипте на сайте пока нет.
SITE_URL = "https://alania.sky"
LEGAL_OFFER_URL = f"{SITE_URL}/legal/oferta.html"
LEGAL_PRIVACY_URL = f"{SITE_URL}/legal/privacy.html"
LEGAL_CONSENT_URL = f"{SITE_URL}/legal/consent.html"
LEGAL_CRYPTO_URL = f"{SITE_URL}/legal/crypto.html"


def ask_lana_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def personal_work_kb():
    """Экран «О личной работе»: отзывы, запись (CTA) и возврат в меню."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Отзывы", callback_data="consultation_reviews")
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


# ── Запись на слот (календарь) ───────────────────────────────────────
_WEEKDAY_HEADER = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
_MONTHS_RU = [
    "", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
    "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь",
]


def _prev_ym(year: int, month: int) -> str:
    return f"{year}-{month - 1:02d}" if month > 1 else f"{year - 1}-12"


def _next_ym(year: int, month: int) -> str:
    return f"{year}-{month + 1:02d}" if month < 12 else f"{year + 1}-01"


def booking_calendar_kb(
    year: int, month: int, free_dates: "set[_date]", has_prev: bool, has_next: bool,
    *, prefix: str = "book", back_cb: str = "consultation"
):
    """Сетка месяца Пн–Вс. free_dates — дни этого месяца со свободными слотами
    (кнопки {prefix}_day:<iso>); остальные ячейки неактивны (callback noop)."""
    builder = InlineKeyboardBuilder()

    # строка навигации: ‹  Месяц Год  ›
    builder.button(
        text="‹" if has_prev else " ",
        callback_data=f"{prefix}_month:{_prev_ym(year, month)}" if has_prev else "noop",
    )
    builder.button(text=f"{_MONTHS_RU[month]} {year}", callback_data="noop")
    builder.button(
        text="›" if has_next else " ",
        callback_data=f"{prefix}_month:{_next_ym(year, month)}" if has_next else "noop",
    )

    # шапка дней недели
    for wd in _WEEKDAY_HEADER:
        builder.button(text=wd, callback_data="noop")

    # дни месяца по неделям
    weeks = _calendar.Calendar(firstweekday=0).monthdatescalendar(year, month)
    for week in weeks:
        for d in week:
            if d.month != month:
                builder.button(text="·", callback_data="noop")
            elif d in free_dates:
                builder.button(text=str(d.day), callback_data=f"{prefix}_day:{d.isoformat()}")
            else:
                builder.button(text="·", callback_data="noop")

    builder.button(text="⇦ Назад", callback_data=back_cb)
    # раскладка: nav(3) · шапка(7) · по 7 на неделю · назад(1)
    builder.adjust(3, 7, *([7] * len(weeks)), 1)
    return builder.as_markup()


def booking_times_kb(day_iso: str, times: "list[tuple[str, str]]",
    *, prefix: str = "book", back_cb: str = "booking_start"):
    """times — список (подпись «12:00 Прага (14:00 Мск)», utc-iso начала слота)."""
    builder = InlineKeyboardBuilder()
    for label, slot_iso in times:
        builder.button(text=label, callback_data=f"{prefix}_slot:{slot_iso}")
    builder.button(text="⇦ К выбору дня", callback_data=back_cb)
    builder.adjust(1)
    return builder.as_markup()


def booking_error_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="↻ Попробовать снова", callback_data="booking_start")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В главное меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def booking_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить в рублях", url=PAY_RUB_URL)
    builder.button(text="Оплатить в евро", url=PAY_EUR_URL)
    builder.button(text="Оплатить в криптовалюте",
                   callback_data=f"pay_crypto:{booking_id}")
    builder.button(text="✓ Я оплатил(а)", callback_data=f"paid:{booking_id}")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.adjust(1)
    return builder.as_markup()


def booking_crypto_kb(booking_id: int):
    """Экран крипто-оплаты: копирование адреса — нативной кнопкой Telegram
    (copy_text, Bot API 8.0); адрес продублирован в тексте тегом <code> —
    на клиентах постарше копируется тапом по нему."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⧉ Скопировать адрес кошелька",
                   copy_text=CopyTextButton(text=CRYPTO_ADDRESS))
    builder.button(text="✓ Я оплатил(а)", callback_data=f"paid_crypto:{booking_id}")
    builder.button(text="⇦ Назад", callback_data=f"pay_back:{booking_id}")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.adjust(1)
    return builder.as_markup()


def admin_confirm_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить оплату", callback_data=f"confirm_pay:{booking_id}")
    builder.button(text="❌ Оплата не найдена", callback_data=f"reject_pay:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def admin_resched_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить перенос", callback_data=f"resched_ok:{booking_id}")
    builder.button(text="❌ Отклонить перенос", callback_data=f"resched_no:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def my_bookings_kb(items: "list[tuple[str, int]]"):
    """items — (подпись слота, booking_id)."""
    builder = InlineKeyboardBuilder()
    for label, bid in items:
        builder.button(text=f"Перенести · {label}", callback_data=f"resched:{bid}")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def followup_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ В главное меню", callback_data="start_menu")
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


# ── Заявка (FSM) ─────────────────────────────────────────────────────
def lead_cancel_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Отменить заявку", callback_data="lead_cancel")
    builder.adjust(1)
    return builder.as_markup()


def lead_contact_kb(has_username: bool):
    builder = InlineKeyboardBuilder()
    if has_username:
        builder.button(text="Оставить мой Telegram", callback_data="lead_use_tg")
    builder.button(text="Отменить заявку", callback_data="lead_cancel")
    builder.adjust(1)
    return builder.as_markup()


def lead_done_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="⇦ В главное меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


# ── Админ ────────────────────────────────────────────────────────────
def broadcast_confirm_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Отправить всем", callback_data="broadcast_confirm")
    builder.button(text="❌ Отменить", callback_data="broadcast_cancel")
    builder.adjust(1)
    return builder.as_markup()


def reviews_kb(page: int, total: int):
    builder = InlineKeyboardBuilder()
    if page > 0:
        builder.button(text="⬅️ Пред.", callback_data=f"review_{page - 1}")
    if page < total - 1:
        builder.button(text="➡️ След.", callback_data=f"review_{page + 1}")
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(2, 1, 1)
    return builder.as_markup()


# ── Тест «Кто управляет твоей жизнью?» ───────────────────────────────
def quiz_intro_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Начать тест", callback_data="quiz_begin")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def quiz_question_kb(options: "list[tuple[str, int]]", is_first: bool):
    """options — список (текст варианта, балл) в порядке показа. Кнопки —
    короткие номера «1..N» (полный текст вариантов идёт в тексте вопроса,
    иначе Telegram обрезает длинные подписи inline-кнопок)."""
    builder = InlineKeyboardBuilder()
    for i, (_text, score) in enumerate(options, 1):
        builder.button(text=str(i), callback_data=f"quiz_ans:{score}")
    if not is_first:
        builder.button(text="⇦ Назад", callback_data="quiz_back")
    builder.button(text="✕ Прервать", callback_data="start_menu")
    # ряд номеров, затем (Назад +) Прервать
    builder.adjust(len(options), 2 if not is_first else 1)
    return builder.as_markup()


def quiz_result_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="✦ Записаться на консультацию", callback_data="booking_start")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="Пройти заново", callback_data="quiz_begin")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
