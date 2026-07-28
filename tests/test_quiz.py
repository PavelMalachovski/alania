from handlers.quiz import _question_text
from keyboards.inline import quiz_question_kb
from quiz_data import QUESTIONS


def test_quiz_buttons_are_short_numbers():
    opts = QUESTIONS[0]["options"]
    kb = quiz_question_kb(opts, is_first=True)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    # варианты — короткие номера 1..N (не длинный обрезаемый текст)
    assert [l for l in labels if l.isdigit()] == [str(i) for i in range(1, len(opts) + 1)]
    assert "✕ Прервать" in labels
    assert "⇦ Назад" not in labels          # на первом вопросе «Назад» нет


def test_quiz_back_button_from_second_question():
    kb = quiz_question_kb(QUESTIONS[1]["options"], is_first=False)
    labels = [b.text for row in kb.inline_keyboard for b in row]
    assert "⇦ Назад" in labels


def test_quiz_question_text_shows_full_options():
    text = _question_text(0)
    # полный текст каждого варианта виден в сообщении (ничего не обрезано)
    for opt_text, _score in QUESTIONS[0]["options"]:
        assert opt_text in text
