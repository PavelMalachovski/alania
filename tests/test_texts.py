from handlers.consultation import PERSONAL_WORK_TEXT
from formatting import PRICE_TEXT
from keyboards.inline import quiz_result_kb


def test_personal_work_price_is_canonical():
    assert PRICE_TEXT in PERSONAL_WORK_TEXT
    assert "111" not in PERSONAL_WORK_TEXT and "11111" not in PERSONAL_WORK_TEXT


def test_quiz_result_has_booking_button():
    kb = quiz_result_kb().inline_keyboard
    cbs = [b.callback_data for row in kb for b in row if b.callback_data]
    assert "booking_start" in cbs
