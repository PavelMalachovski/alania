"""Курс-практикум «Взломай Реальность»: кнопка нижней клавиатуры, экран
с оплатой через Tribute и deep link ?start=course с лендинга."""
import pytest

from handlers.info import COURSE_TEXT, GAME_TEXT
from keyboards.inline import COURSE_PAY_EUR_URL, COURSE_PAY_RUB_URL, course_kb
from keyboards.reply import BTN_COURSE, main_reply_kb
from tests.test_booking_flow import CLIENT_ID, env  # харнес
from tests.test_reply_keyboard import _send_text


def _last_send(session):
    return [d for n, d in session.log
            if n == "SendMessage" and d.get("chat_id") == CLIENT_ID][-1]


def _buttons(msg):
    return [b for row in msg.get("reply_markup", {}).get("inline_keyboard", [])
            for b in row]


def test_course_button_is_full_width_row():
    rows = main_reply_kb().keyboard
    assert [b.text for b in rows[1]] == [BTN_COURSE]
    assert sum(len(r) for r in rows) == 8


def test_course_kb_pays_only_via_tribute():
    """Как у личной работы — рубли и евро, но без крипты и «Я оплатил(а)»:
    доступ к курсу Tribute выдаёт сам, подтверждать Лане нечего."""
    buttons = [b for row in course_kb().inline_keyboard for b in row]
    urls = {b.text: b.url for b in buttons if b.url}
    assert urls["Оплатить в рублях"] == COURSE_PAY_RUB_URL == "https://web.tribute.tg/p/Ezz"
    assert urls["Оплатить в евро"] == COURSE_PAY_EUR_URL == "https://web.tribute.tg/p/Ezx"
    cbs = [b.callback_data for b in buttons if b.callback_data]
    assert cbs == ["start_menu"]


def test_course_text_matches_landing():
    for needle in ("«ВЗЛОМАЙ РЕАЛЬНОСТЬ»", "5-дневная программа", "База практик",
                   "Для кого практикум", "11 € / 1000 ₽"):
        assert needle in COURSE_TEXT


def test_game_text_lists_new_contents():
    for needle in ("300+ терапевтических вопросов", "36 вопросов, чтобы влюбиться",
                   "Идеи для свиданий", "тест на совместимость", "«69 ступеней» (18+)",
                   "Мастер-класс по нюдсам", "Практики для любви к себе",
                   "Практики для сближения в паре"):
        assert needle in GAME_TEXT
    assert "Территория искушения" not in GAME_TEXT


@pytest.mark.asyncio
async def test_reply_course_opens_course_screen(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "/start", mid=7500)
    await _send_text(dp, bot, BTN_COURSE, mid=7501)
    assert any(n == "DeleteMessage" and d.get("message_id") == 7501
               for n, d in session.log), "тап по кнопке не удалён"
    last = _last_send(session)
    assert last["text"] == COURSE_TEXT
    assert {b.get("url") for b in _buttons(last)} >= {COURSE_PAY_RUB_URL, COURSE_PAY_EUR_URL}


@pytest.mark.asyncio
async def test_start_course_deep_link_opens_course(env):
    """Кнопка на лендинге ведёт на ?start=course — человек сразу попадает
    на экран курса, а нижняя клавиатура всё равно ставится."""
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "/start course", mid=7600)
    sends = [d for n, d in session.log
             if n == "SendMessage" and d.get("chat_id") == CLIENT_ID]
    assert any("keyboard" in d.get("reply_markup", {}) for d in sends), "нет якоря клавиатуры"
    assert sends[-1]["text"] == COURSE_TEXT
    assert not any("Это пространство создано" in (d.get("text") or "") for d in sends)


@pytest.mark.asyncio
async def test_start_other_payload_shows_welcome(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "/start site", mid=7700)
    assert "Это пространство создано" in _last_send(session)["text"]
