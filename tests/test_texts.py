from datetime import datetime, timezone

from handlers.booking import LEGAL_NOTICE, _crypto_screen_text, _pay_screen_text
from handlers.consultation import PERSONAL_WORK_TEXT
from formatting import CRYPTO_ADDRESS, PRICE_TEXT
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


def _screens():
    slot = datetime(2026, 9, 1, 12, 0, tzinfo=timezone.utc)
    hold = datetime(2026, 9, 1, 12, 20, tzinfo=timezone.utc)
    return _pay_screen_text(slot, hold), _crypto_screen_text(slot, hold)


def test_paid_button_wording_starts_new_line():
    pay, _ = _screens()
    assert "нажми\n«✓ Я оплатил(а)»" in pay


def test_pay_screens_carry_legal_notice():
    pay, crypto = _screens()
    assert LEGAL_NOTICE in pay
    assert "18 лет" in pay and "Публичной оферты" in pay
    # на крипто-экране — только строка про дисклеймер
    assert "Дисклеймера по крипто-платежам" in crypto


def test_crypto_screen_has_address_amount_and_network():
    _, crypto = _screens()
    assert f"<code>{CRYPTO_ADDRESS}</code>" in crypto
    assert "58 USDT" in crypto and "TRC20" in crypto


def test_quiz_result_has_booking_button():
    kb = quiz_result_kb().inline_keyboard
    cbs = [b.callback_data for row in kb for b in row if b.callback_data]
    assert "booking_start" in cbs
