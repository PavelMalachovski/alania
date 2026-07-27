from datetime import date

from keyboards.inline import booking_calendar_kb


def _flat(kb):
    return [b for row in kb.inline_keyboard for b in row]


def test_free_day_is_button_others_noop():
    kb = booking_calendar_kb(
        2026, 8, {date(2026, 8, 11)}, has_prev=True, has_next=False
    )
    cbs = [b.callback_data for b in _flat(kb)]
    # свободный день — активная кнопка book_day
    assert "book_day:2026-08-11" in cbs
    # ровно один book_day (остальные дни неактивны)
    assert sum(c.startswith("book_day:") for c in cbs) == 1


def test_nav_prev_present_next_disabled():
    kb = booking_calendar_kb(2026, 8, set(), has_prev=True, has_next=False)
    cbs = [b.callback_data for b in _flat(kb)]
    assert "book_month:2026-07" in cbs          # ‹ ведёт на июль
    assert "book_month:2026-09" not in cbs       # › отключена
    # заголовок и отключённая стрелка — noop
    assert "noop" in cbs


def test_january_prev_wraps_year():
    kb = booking_calendar_kb(2026, 1, set(), has_prev=True, has_next=True)
    cbs = [b.callback_data for b in _flat(kb)]
    assert "book_month:2025-12" in cbs
    assert "book_month:2026-02" in cbs


def test_weekday_header_and_back_present():
    kb = booking_calendar_kb(2026, 8, set(), has_prev=False, has_next=True)
    texts = [b.text for b in _flat(kb)]
    for wd in ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]:
        assert wd in texts
    assert any(b.callback_data == "consultation" for b in _flat(kb))
