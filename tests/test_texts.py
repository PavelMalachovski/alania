from handlers.consultation import CONSULTATION_TEXT
from formatting import PRICE_TEXT
from keyboards.inline import quiz_result_kb


def test_consultation_price_is_canonical():
    assert PRICE_TEXT in CONSULTATION_TEXT
    assert "111" not in CONSULTATION_TEXT and "11111" not in CONSULTATION_TEXT


def test_quiz_result_has_booking_button():
    kb = quiz_result_kb().inline_keyboard
    cbs = [b.callback_data for row in kb for b in row if b.callback_data]
    assert "booking_start" in cbs
