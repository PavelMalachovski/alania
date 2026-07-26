from aiogram.utils.keyboard import InlineKeyboardBuilder

# ── Внешние ссылки ───────────────────────────────────────────────────
DM_URL = "https://t.me/LanaLeonovich"
PAY_RUB_URL = "https://web.tribute.tg/p/rTr"
PAY_EUR_URL = "https://web.tribute.tg/p/tse"
GAME_URL = "https://t.me/tvoya_vechnost_bot"
CHANNEL_URL = "https://t.me/+yL84pnnJCUNlZjJk"
GUIDE_URL = "https://t.me/c/2260920571/433"


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
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def consultation_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Кому подойдет?", callback_data="consultation_who")
    builder.button(text="Как проходит сессия?", callback_data="consultation_how")
    builder.button(text="Отзывы", callback_data="consultation_reviews")
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="Оставить заявку", callback_data="lead_start:consultation")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="personal_work")
    builder.adjust(1)
    return builder.as_markup()


# ── Запись на слот (календарь) ───────────────────────────────────────
def booking_days_kb(days: "list[tuple[str, str]]"):
    """days — список (подпись «Пн 21.07», iso-дата)."""
    builder = InlineKeyboardBuilder()
    for label, iso in days:
        builder.button(text=label, callback_data=f"book_day:{iso}")
    builder.button(text="⇦ Назад", callback_data="consultation")
    builder.adjust(2)
    return builder.as_markup()


def booking_times_kb(iso_date: str, free_times: "list[str]"):
    builder = InlineKeyboardBuilder()
    for t in free_times:
        builder.button(text=t, callback_data=f"book_slot:{iso_date}:{t}")
    builder.button(text="⇦ К выбору дня", callback_data="booking_start")
    builder.adjust(3, 1)
    return builder.as_markup()


def booking_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="Оплатить в рублях", url=PAY_RUB_URL)
    builder.button(text="Оплатить в евро", url=PAY_EUR_URL)
    builder.button(text="✓ Я оплатил(а)", callback_data=f"paid:{booking_id}")
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.adjust(1)
    return builder.as_markup()


def admin_confirm_pay_kb(booking_id: int):
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить оплату", callback_data=f"confirm_pay:{booking_id}")
    builder.adjust(1)
    return builder.as_markup()


def followup_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="Оставить заявку", callback_data="lead_start:consultation")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ В главное меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def consultation_sub_kb(back_to: str = "consultation"):
    builder = InlineKeyboardBuilder()
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data=back_to)
    builder.adjust(1)
    return builder.as_markup()


def consultation_how_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Забрать гайд", callback_data="get_guide")
    builder.button(text="Записаться", callback_data="booking_start")
    builder.button(text="Задать вопрос в ЛС", url=DM_URL)
    builder.button(text="⇦ Назад", callback_data="consultation")
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


def gift_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Забрать гайд", callback_data="get_guide")
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def guide_link_kb():
    """Фолбэк, пока админ не загрузил файл гайда через /set_guide."""
    builder = InlineKeyboardBuilder()
    builder.button(text="Открыть гайд", url=GUIDE_URL)
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
    """options — список (текст варианта, балл) в порядке показа."""
    builder = InlineKeyboardBuilder()
    for text, score in options:
        builder.button(text=text, callback_data=f"quiz_ans:{score}")
    if not is_first:
        builder.button(text="⇦ Назад", callback_data="quiz_back")
    builder.button(text="✕ Прервать", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()


def quiz_result_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="Пройти заново", callback_data="quiz_begin")
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
