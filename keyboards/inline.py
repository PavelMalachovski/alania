import calendar as _calendar
from datetime import date as _date

from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Внешние ссылки ───────────────────────────────────────────────────
DM_URL = "https://t.me/LanaLeonovich"
GAME_URL = "https://t.me/tvoya_vechnost_bot"
CHANNEL_URL = "https://t.me/+yL84pnnJCUNlZjJk"

# Оплата — счета lava.top (lava.py), ссылок на оплату здесь нет: ссылка
# своя у каждого счёта и приходит из API.

# Юр. документы — Google Docs Ланы, открыты по ссылке без входа в аккаунт.
# Форма /preview — read-only читалка: открывается прямо в браузере и не тянет
# в приложение Docs, как /edit. Хвост исходных ссылок (?usp=drivesdk&ouid=…)
# не нужен — доступ даёт сам id, а «&» в HTML-разметке сообщения лишний.
# Копий этих текстов в репозитории нет: и бот, и лендинг ссылаются сюда же.
_GDOC = "https://docs.google.com/document/d/{}/preview"
LEGAL_OFFER_URL = _GDOC.format("1uKkXGBah_qI0jlRUBaD0SyylDStKr2sP")
LEGAL_PRIVACY_URL = _GDOC.format("1_ZJE1ejwbpGsbt3tkF89EyuyiA2WPeVm")
LEGAL_CONSENT_URL = _GDOC.format("1CPsoI6U1nC1gN6O8_QanG1fi4-mSHa-w")


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


def _pay_buttons(builder, product: str, booking_id: int = 0) -> None:
    """«Оплатить в рублях / в евро» → счёт lava.top (handlers/payments.py)."""
    builder.button(text="Оплатить в рублях",
                   callback_data=f"lava_pay:{product}:RUB:{booking_id}")
    builder.button(text="Оплатить в евро",
                   callback_data=f"lava_pay:{product}:EUR:{booking_id}")


def booking_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    _pay_buttons(builder, "session", booking_id)
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.adjust(1)
    return builder.as_markup()


def lava_email_kb(product: str, booking_id: int = 0):
    """Экран «напиши email»: ввод ждёт FSM, отсюда — только отмена."""
    builder = InlineKeyboardBuilder()
    builder.button(text="⇦ Отмена", callback_data=f"lava_back:{product}:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def lava_invoice_kb(payment_url: str, amount_label: str, payment_id: int,
                    product: str, currency: str, booking_id: int = 0):
    """Счёт выставлен: ссылка на оплату lava.top, ручная проверка статуса
    (фоновая проверка идёт и без неё), смена email, назад к выбору валюты."""
    builder = InlineKeyboardBuilder()
    builder.button(text=f"Оплатить {amount_label}", url=payment_url)
    builder.button(text="✓ Я оплатил(а)", callback_data=f"lava_check:{payment_id}")
    builder.button(text="Изменить email",
                   callback_data=f"lava_email:{product}:{currency}:{booking_id}")
    builder.button(text="⇦ Назад", callback_data=f"lava_back:{product}:{booking_id}")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.adjust(1)
    return builder.as_markup()


def lava_error_kb(product: str, currency: str, booking_id: int = 0):
    builder = InlineKeyboardBuilder()
    builder.button(text="↻ Попробовать снова",
                   callback_data=f"lava_pay:{product}:{currency}:{booking_id}")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В меню", callback_data="start_menu")
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
    _pay_buttons(builder, "game")
    builder.button(text="Перейти к игре", url=GAME_URL)
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def course_kb():
    """Экран курса: счёт lava.top в рублях или евро. Доступ к курсу lava.top
    присылает покупателю на email сам, Лане подтверждать нечего."""
    builder = InlineKeyboardBuilder()
    _pay_buttons(builder, "course")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В меню", callback_data="start_menu")
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
