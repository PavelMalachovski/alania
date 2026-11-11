from datetime import datetime, timezone

from handlers.booking import LEGAL_NOTICE, pay_screen_text
from handlers.consultation import PERSONAL_WORK_TEXT
from formatting import PRICE_TEXT
from keyboards.inline import quiz_result_kb


def test_personal_work_price_is_canonical():
    assert PRICE_TEXT in PERSONAL_WORK_TEXT
    assert "111" not in PERSONAL_WORK_TEXT and "11111" not in PERSONAL_WORK_TEXT


def test_personal_work_lists_four_request_groups():
    for group in ("Эмоциональная сфера и психофизиология",
                  "Самооценка и идентичность",
                  "Отношения и границы",
                  "Реализация и автономия"):
        assert group in PERSONAL_WORK_TEXT


def _pay_screen():
    slot = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    hold = datetime(2026, 9, 1, 12, 20, tzinfo=timezone.utc)
    return pay_screen_text(slot, hold)


def test_pay_screen_carries_price_and_legal_notice():
    pay = _pay_screen()
    assert PRICE_TEXT in pay
    assert LEGAL_NOTICE in pay
    assert "18 лет" in pay and "Публичной оферты" in pay


def test_no_crypto_left_in_payment_texts():
    """Крипто-оплату убрали вместе с переездом на lava.top."""
    pay = _pay_screen()
    assert "lava.top" in pay
    for gone in ("USDT", "крипто", "Tribute"):
        assert gone not in pay and gone not in LEGAL_NOTICE


def test_quiz_result_has_booking_button():
    kb = quiz_result_kb().inline_keyboard
    cbs = [b.callback_data for row in kb for b in row if b.callback_data]
    assert "booking_start" in cbs
