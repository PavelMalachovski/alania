# Уборка сообщений + нижняя клавиатура — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Бот перестаёт плодить сообщения (поток «причина переноса» схлопывается в одно редактируемое сообщение, текст клиента удаляется; уведомления Ланы после действия сворачиваются в одну строку) и получает постоянную нижнюю клавиатуру с быстрыми действиями.

**Architecture:** Тонкие хелперы `delete_safe`/`edit_screen` (модуль `ui.py`) над Bot API, глотающие ошибки. FSM-поток переноса хранит `screen_id` якорного сообщения и редактирует его вместо отправки нового. Экраны (календарь, «Мои записи», меню) выносятся в функции с флагом send/edit, чтобы их дёргали и inline-колбэки, и текстовые хендлеры нижней клавиатуры (`ReplyKeyboardMarkup`, фильтр `StateFilter(None)`).

**Tech Stack:** Python 3.12, aiogram 3.x (FSM, ReplyKeyboardMarkup), pytest + pytest-asyncio.

## Global Constraints

- Python 3.12, aiogram 3.x, HTML parse mode. Колбэки — `F.data ==`/`.startswith`; тексты reply-кнопок — `F.text == "..."` (точный матч с эмодзи).
- Хендлеры колбэков не зовут пустой `callback.answer()` (middleware). Алерт `callback.answer("...", show_alert=True)` — можно.
- Все удаления/редактирования — через `delete_safe`/`edit_screen`, глотают `TelegramBadRequest`/`TelegramAPIError` (сообщение >48ч, уже удалено, «message is not modified», «message to edit not found») — никогда не падают.
- FSM-поток переноса: якорь `screen_id` в FSM-данных; текст клиента удаляется; при потере `screen_id` — фолбэк на `message.answer`.
- Заявка (`lead.py`) — ВНЕ ОБЪЁМА (кнопка убрана в PR #8, поток недостижим).
- Нижняя клавиатура: `ReplyKeyboardMarkup`, `resize_keyboard=True`, `is_persistent=True`, кнопки «📅 Записаться», «📋 Мои записи», «🏠 Меню», «💬 Вопрос Лане».
- reply-текст-хендлеры фильтруются `StateFilter(None)` (работают только вне FSM-потоков).
- `/start` (одобрено): приветствие с нижней клавиатурой; богатое inline-меню открывается «🏠 Меню».
- Экранирование тестов на Windows: `PYTHONIOENCODING=utf-8 python -m pytest -q`.
- Компиляция: `python -m py_compile main.py database.py followup.py slots.py google_calendar.py booking_config.py formatting.py ui.py handlers/*.py keyboards/*.py`.

---

## File Structure

- **Create** `ui.py` — `delete_safe(bot, chat_id, message_id)`, `edit_screen(bot, chat_id, message_id, text, reply_markup=None)`.
- **Create** `keyboards/reply.py` — `main_reply_kb()` (ReplyKeyboardMarkup), константы текстов кнопок.
- **Create** `handlers/reply.py` — роутер текстовых хендлеров нижней клавиатуры (`StateFilter(None)`).
- **Modify** `handlers/booking.py` — вынести `open_calendar`/`open_my_bookings` (send/edit); в потоке причины переноса хранить якорь и редактировать его + удалять текст клиента.
- **Modify** `handlers/admin.py` — свернуть уведомления Ланы (confirm/reject pay, resched ok/no) в короткую строку.
- **Modify** `handlers/start.py` — `open_main_menu`(send/edit); `/start` вешает нижнюю клавиатуру.
- **Modify** `handlers/__init__.py` — подключить `reply_router`.
- **Test** `tests/test_ui.py`, `tests/test_reply_keyboard.py`, дополнения к `tests/test_reschedule.py`, `tests/test_booking_flow.py`.

---

## Task 1: ui.py — безопасные delete/edit

**Files:**
- Create: `ui.py`
- Create: `tests/test_ui.py`

**Interfaces:**
- Produces: `async delete_safe(bot, chat_id: int, message_id: int) -> None` — `bot.delete_message`, глотает `TelegramAPIError`.
- Produces: `async edit_screen(bot, chat_id: int, message_id: int, text: str, reply_markup=None) -> None` — `bot.edit_message_text`, глотает `TelegramBadRequest`/`TelegramAPIError`.

- [ ] **Step 1: Тесты — не падают на ошибке API**

`tests/test_ui.py`:
```python
import pytest
from aiogram.exceptions import TelegramBadRequest, TelegramAPIError
from ui import delete_safe, edit_screen


class BoomBot:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []
    async def delete_message(self, chat_id, message_id):
        self.calls.append(("delete", chat_id, message_id))
        raise self.exc
    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.calls.append(("edit", chat_id, message_id, text))
        raise self.exc


class OkBot:
    def __init__(self):
        self.calls = []
    async def delete_message(self, chat_id, message_id):
        self.calls.append(("delete", chat_id, message_id))
    async def edit_message_text(self, text, chat_id=None, message_id=None, reply_markup=None):
        self.calls.append(("edit", chat_id, message_id, text))


def _bad(msg):
    from aiogram.methods.base import TelegramMethod
    return TelegramBadRequest(method=None, message=msg)


@pytest.mark.asyncio
async def test_delete_safe_swallows_errors():
    bot = BoomBot(TelegramAPIError(method=None, message="too old"))
    await delete_safe(bot, 1, 2)   # не должно бросить
    assert bot.calls == [("delete", 1, 2)]


@pytest.mark.asyncio
async def test_edit_screen_swallows_not_modified():
    bot = BoomBot(_bad("message is not modified"))
    await edit_screen(bot, 1, 2, "text")   # не должно бросить
    assert bot.calls[0][0] == "edit"


@pytest.mark.asyncio
async def test_edit_screen_passes_through_on_ok():
    bot = OkBot()
    await edit_screen(bot, 5, 6, "hello", reply_markup=None)
    assert bot.calls == [("edit", 5, 6, "hello")]
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_ui.py -v`
Expected: FAIL (нет модуля ui).

- [ ] **Step 3: Реализовать ui.py**

```python
import logging

from aiogram.exceptions import TelegramAPIError

logger = logging.getLogger(__name__)


async def delete_safe(bot, chat_id: int, message_id: int) -> None:
    """Удалить сообщение, не падая на ошибке (старше 48ч, уже удалено, нет прав)."""
    try:
        await bot.delete_message(chat_id, message_id)
    except TelegramAPIError:
        logger.debug("delete_safe: не удалил %s/%s", chat_id, message_id)


async def edit_screen(bot, chat_id: int, message_id: int, text: str,
                      reply_markup=None) -> None:
    """Отредактировать «экран», глотая «not modified»/«to edit not found» и пр."""
    try:
        await bot.edit_message_text(
            text, chat_id=chat_id, message_id=message_id, reply_markup=reply_markup
        )
    except TelegramAPIError:
        logger.debug("edit_screen: не отредактировал %s/%s", chat_id, message_id)
```
(`TelegramBadRequest` — подкласс `TelegramAPIError`, ловится тем же except.)

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_ui.py -v`
Expected: PASS (3 теста).

- [ ] **Step 5: Commit**

```bash
git add ui.py tests/test_ui.py
git commit -m "ui.py: delete_safe/edit_screen — безопасные удаление и редактирование"
```

---

## Task 2: Уборка потока «причина переноса»

**Files:**
- Modify: `handlers/booking.py` (`cb_resched_slot` <24ч ветка + `resched_reason`)
- Modify: `tests/test_reschedule.py`

**Interfaces:**
- Consumes: `ui.delete_safe`, `ui.edit_screen`.
- FSM-данные получают ключ `resched_screen_id` — id якорного сообщения (промпт «напиши причину»).

- [ ] **Step 1: Тест — причина не плодит новое сообщение, текст клиента удалён**

Добавить в `tests/test_reschedule.py`:
```python
@pytest.mark.asyncio
async def test_reschedule_reason_edits_anchor_and_deletes_user_text(env):
    dp, bot, gcal, session = env
    # бронь через 2 часа (<24ч), заводим перенос
    slot = datetime.now(timezone.utc) + timedelta(hours=2)
    eid = await gcal.create_event(slot, "Клиент", "desc")
    from slots import free_slots
    import booking_config
    cfg = booking_config.load()
    free = free_slots(datetime.now(timezone.utc), [], [], work_times=cfg.work_times,
                      work_weekdays=cfg.work_weekdays, horizon_days=cfg.horizon_days,
                      lead=cfg.lead, tz=cfg.tz)
    new_slot = next(s for s in free if s - datetime.now(timezone.utc) >= timedelta(days=1))
    async with get_session() as s:
        b = Booking(telegram_id=CLIENT_ID, slot_start=slot, status="confirmed",
                    google_event_id=eid)
        s.add(b); await s.commit(); bid = b.id
    # входим в поток: resched → day → slot (доводим до запроса причины)
    await press(dp, bot, f"resched:{bid}")
    await press(dp, bot, find_cb(session, "resched_day:"))
    await press(dp, bot, find_cb(session, "resched_slot:"))
    # шлём причину текстом
    from aiogram.types import Update, Message, Chat, User as TgUser
    before_sends = sum(1 for n, d in session.log
                       if n == "SendMessage" and d.get("chat_id") == CLIENT_ID)
    upd = Update(update_id=99, message=Message(
        message_id=4242, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text="заболел ребёнок"))
    await dp.feed_update(bot, upd)
    after_sends = sum(1 for n, d in session.log
                      if n == "SendMessage" and d.get("chat_id") == CLIENT_ID)
    # клиенту НЕ ушло новое сообщение (отредактирован якорь)
    assert after_sends == before_sends
    # текст клиента удалён
    assert any(n == "DeleteMessage" and d.get("message_id") == 4242
               for n, d in session.log)
    # запрос всё равно создан
    async with get_session() as s:
        b = await s.get(Booking, bid)
    assert b.reschedule_status == "pending"
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v -k reason_edits_anchor`
Expected: FAIL (сейчас `resched_reason` шлёт новое сообщение, текст не удаляется).

- [ ] **Step 3: Хранить якорь + редактировать его**

В `handlers/booking.py` добавить импорт `from ui import delete_safe, edit_screen`.
В `cb_resched_slot`, в <24ч ветке (где ставится состояние reason), сохранить якорь — заменить блок:
```python
    # <24ч — просим причину (new_slot в FSM), pending выставим после причины
    await state.update_data(resched_new_slot=new_slot.isoformat())
    await state.set_state(RescheduleForm.reason)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "До сессии меньше 24 часов — перенос подтверждает Лана.\n\n"
        "Напиши, пожалуйста, причину переноса ⇩"
    )
```
на:
```python
    # <24ч — просим причину; якорь = это же сообщение, его и будем редактировать
    await state.update_data(
        resched_new_slot=new_slot.isoformat(),
        resched_screen_id=callback.message.message_id,
    )
    await state.set_state(RescheduleForm.reason)
    await callback.message.edit_text(
        "○─── ☾ ───○\n\n"
        "До сессии меньше 24 часов — перенос подтверждает Лана.\n\n"
        "Напиши, пожалуйста, причину переноса ⇩"
    )
```
В `resched_reason` заменить финальную выдачу клиенту и «/»-выход на редактирование якоря + удаление текста:
```python
@router.message(RescheduleForm.reason, F.text)
async def resched_reason(message: Message, state: FSMContext, bot: Bot,
                         admin_ids: list[int]) -> None:
    data = await state.get_data()
    screen_id = data.get("resched_screen_id")
    chat_id = message.chat.id

    async def _finish_screen(text: str, kb=None) -> None:
        # убрать текст клиента и обновить якорь (или прислать новое, если якорь потерян)
        await delete_safe(bot, chat_id, message.message_id)
        if screen_id:
            await edit_screen(bot, chat_id, screen_id, text, kb)
        else:
            await message.answer(text, reply_markup=kb)

    if message.text.startswith("/"):
        await state.clear()
        await _finish_screen("Ок, перенос отменён.", lead_done_kb())
        return
    booking_id = data.get("resched_booking_id")
    new_slot_iso = data.get("resched_new_slot")
    await state.clear()
    if not booking_id or not new_slot_iso:
        await _finish_screen("Сессия сброшена, открой «Мои записи» заново.", lead_done_kb())
        return
    new_slot = datetime.fromisoformat(new_slot_iso)
    reason = message.text.strip()[:500]
    async with get_session() as session:
        booking = await session.get(Booking, booking_id)
        if not booking or booking.telegram_id != message.from_user.id:
            await _finish_screen("Запись не найдена.", lead_done_kb())
            return
        old_slot = booking.slot_start if booking.slot_start.tzinfo else booking.slot_start.replace(tzinfo=timezone.utc)
        booking.reschedule_to = new_slot
        booking.reschedule_reason = reason
        booking.reschedule_status = "pending"
        await session.commit()
    await _finish_screen(
        "○─── ☾ ───○\n\n"
        "🤍 Запрос на перенос отправлен Лане. Как решится — пришлём сообщение.",
        lead_done_kb(),
    )
    await _notify_admins(
        bot, admin_ids,
        "🔁 <b>Запрос на перенос (меньше 24ч)</b>\n\n"
        f"Было: {format_slot_human(old_slot)}\n"
        f"Хочет: {format_slot_human(new_slot)}\n"
        f"Причина: {html.quote(reason)}\n"
        f'<b>Клиент:</b> id {message.from_user.id}\n\n'
        "Подтвердить перенос? ⇩",
        reply_markup=admin_resched_kb(booking_id),
    )
```

- [ ] **Step 4: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reschedule.py -v`
Expected: PASS (новый + существующие).

- [ ] **Step 5: Полный прогон**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 6: Commit**

```bash
git add handlers/booking.py tests/test_reschedule.py
git commit -m "Уборка: причина переноса редактирует якорь и удаляет текст клиента"
```

---

## Task 3: Сворачивание уведомлений Ланы

**Files:**
- Modify: `handlers/admin.py` (`cb_confirm_pay`, `cb_reject_pay`, `cb_resched_ok`, `cb_resched_no`)
- Modify: `tests/test_booking_flow.py`, `tests/test_reschedule.py`

**Interfaces:**
- Consumes: `format_slot_human`.
- Produces: итоговые `edit_text` короткие (не содержат исходного полного текста уведомления).

- [ ] **Step 1: Тесты — итоговая строка короткая**

Добавить в `tests/test_booking_flow.py`:
```python
@pytest.mark.asyncio
async def test_confirm_collapses_admin_notification(env):
    dp, bot, gcal, session = env
    paid = await _book_one(dp, bot, session)
    await press(dp, bot, paid)
    confirm = find_cb(session, "confirm_pay:", chat_id=ADMIN_ID)
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, confirm, user=admin, chat_id=ADMIN_ID)
    # последний EditMessageText в чат Ланы — короткая итоговая строка
    edits = [d for n, d in session.log
             if n == "EditMessageText" and d.get("chat_id") == ADMIN_ID]
    last = edits[-1]["text"]
    assert "подтвержд" in last.lower()
    assert "Проверь оплату в Tribute" not in last   # полный исходный текст ушёл
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_booking_flow.py -v -k confirm_collapses`
Expected: FAIL (сейчас дописывается к полному тексту `callback.message.html_text`).

- [ ] **Step 3: Свернуть уведомления**

В `handlers/admin.py`:
`cb_confirm_pay` — заменить финальный `edit_text`:
```python
    warn = " ⚠️ событие оформи вручную" if sync_failed else ""
    await callback.message.edit_text(
        f"✅ {format_slot_human(slot)} — оплата подтверждена{warn}"
    )
```
`cb_reject_pay` — заменить финальный `edit_text`:
```python
    await callback.message.edit_text(
        f"❌ {format_slot_human(slot)} — оплата отклонена, слот освобождён"
    )
```
`cb_resched_ok` — заменить итоговый `edit_text` (успех) на:
```python
    await callback.message.edit_text(
        f"✅ Перенос подтверждён: {format_slot_human(moved)}"
    )
```
и в ветке «новый слот занят» заменить на:
```python
        await callback.message.edit_text(
            "⚠️ Новый слот заняли — перенос не выполнен, запись на прежнем слоте"
        )
```
`cb_resched_no` — заменить итоговый `edit_text` на:
```python
    await callback.message.edit_text(
        "❌ Перенос отклонён, запись отменена"
    )
```
(во всех — без `callback.message.html_text +`; переменные `slot`/`moved` уже посчитаны в этих хендлерах.)

- [ ] **Step 4: Добавить тест сворачивания для переноса**

В `tests/test_reschedule.py` (переиспользует `_pending_near`):
```python
@pytest.mark.asyncio
async def test_resched_reject_collapses_admin_notification(env):
    dp, bot, gcal, session = env
    bid, old_eid, _ = await _pending_near(env)
    from aiogram.types import User as TgUser
    admin = TgUser(id=ADMIN_ID, is_bot=False, first_name="Lana")
    await press(dp, bot, f"resched_no:{bid}", user=admin, chat_id=ADMIN_ID)
    edits = [d for n, d in session.log
             if n == "EditMessageText" and d.get("chat_id") == ADMIN_ID]
    assert "отклонён" in edits[-1]["text"].lower()
    assert "Причина:" not in edits[-1]["text"]
```

- [ ] **Step 5: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное. Существующие тесты, ассертившие приписку «✅ Оплата подтверждена» к полному тексту, обнови под новую короткую строку (не ослабляя: проверяют наличие «подтвержд»/«отклон»).

- [ ] **Step 6: Commit**

```bash
git add handlers/admin.py tests/test_booking_flow.py tests/test_reschedule.py
git commit -m "Уборка: уведомления Ланы сворачиваются в короткую итоговую строку"
```

---

## Task 4: Нижняя клавиатура + переиспользуемые экраны

**Files:**
- Create: `keyboards/reply.py`
- Create: `handlers/reply.py`
- Modify: `handlers/booking.py` (`open_calendar`, `open_my_bookings` — send/edit)
- Modify: `handlers/start.py` (`open_main_menu` — send/edit; `/start` вешает клавиатуру)
- Modify: `handlers/__init__.py` (подключить `reply_router` последним из «контентных»)
- Create: `tests/test_reply_keyboard.py`

**Interfaces:**
- Produces: `keyboards/reply.py`: `main_reply_kb() -> ReplyKeyboardMarkup`; константы `BTN_BOOK="📅 Записаться"`, `BTN_MY="📋 Мои записи"`, `BTN_MENU="🏠 Меню"`, `BTN_ASK="💬 Вопрос Лане"`.
- Produces: `handlers/booking.py`: `async open_calendar(message, gcal, cfg, *, send: bool)`, `async open_my_bookings(message, tg_id, *, send: bool)`.
- Produces: `handlers/start.py`: `async open_main_menu(message, *, send: bool)`.

- [ ] **Step 1: Тесты — /start вешает клавиатуру; тап «Записаться» открывает календарь и удаляет тап**

`tests/test_reply_keyboard.py`:
```python
import pytest
from datetime import datetime
from aiogram.types import Update, Message, Chat, User as TgUser

from tests.test_booking_flow import env, CLIENT_ID  # харнес


def _text(dp_bot_pair):
    pass


async def _send_text(dp, bot, text, mid=7000):
    upd = Update(update_id=mid, message=Message(
        message_id=mid, date=datetime.now(),
        chat=Chat(id=CLIENT_ID, type="private"),
        from_user=TgUser(id=CLIENT_ID, is_bot=False, first_name="Марина"),
        text=text))
    await dp.feed_update(bot, upd)


@pytest.mark.asyncio
async def test_start_sets_reply_keyboard(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "/start")
    sends = [d for n, d in session.log if n == "SendMessage" and d.get("chat_id") == CLIENT_ID]
    kb = sends[-1].get("reply_markup", {})
    assert "keyboard" in kb   # ReplyKeyboardMarkup (не inline_keyboard)
    labels = [b["text"] for row in kb["keyboard"] for b in row]
    assert "📅 Записаться" in labels and "📋 Мои записи" in labels


@pytest.mark.asyncio
async def test_reply_book_opens_calendar_and_deletes_tap(env):
    dp, bot, gcal, session = env
    await _send_text(dp, bot, "📅 Записаться", mid=7010)
    # тап удалён
    assert any(n == "DeleteMessage" and d.get("message_id") == 7010 for n, d in session.log)
    # показан календарь (есть book_day: или noop в новом сообщении)
    last = [d for n, d in session.log if n == "SendMessage" and d.get("chat_id") == CLIENT_ID][-1]
    cbs = [b.get("callback_data", "") for row in last.get("reply_markup", {}).get("inline_keyboard", []) for b in row]
    assert any(c.startswith("book_day:") for c in cbs) or "noop" in cbs
```

- [ ] **Step 2: Прогнать — падает**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reply_keyboard.py -v`
Expected: FAIL (нет клавиатуры/хендлеров).

- [ ] **Step 3: keyboards/reply.py**

```python
from aiogram.types import KeyboardButton, ReplyKeyboardMarkup

BTN_BOOK = "📅 Записаться"
BTN_MY = "📋 Мои записи"
BTN_MENU = "🏠 Меню"
BTN_ASK = "💬 Вопрос Лане"


def main_reply_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text=BTN_BOOK), KeyboardButton(text=BTN_MY)],
            [KeyboardButton(text=BTN_MENU), KeyboardButton(text=BTN_ASK)],
        ],
        resize_keyboard=True,
        is_persistent=True,
    )
```

- [ ] **Step 4: Вынести open_calendar / open_my_bookings в booking.py**

В `handlers/booking.py` из тела `cb_booking_start` вынести функцию (и переиспользовать её в колбэке):
```python
async def open_calendar(message, gcal: GoogleCalendar, cfg: BookingConfig, *, send: bool) -> None:
    """Показать календарь записи. send=True — новым сообщением, иначе редактируя message."""
    try:
        slots = await _load_free(gcal, cfg)
    except Exception:
        logger.exception("Google недоступен при показе слотов")
        text = ("○─── ☾ ───○\n\nРасписание сейчас недоступно 🤍 Попробуй через "
                "минуту или напиши Лане в личку.")
        await (message.answer(text, reply_markup=booking_error_kb()) if send
               else message.edit_text(text, reply_markup=booking_error_kb()))
        return
    if not slots:
        text = ("○─── ☾ ───○\n\nБлижайшее время сейчас занято 🤍 Напиши Лане в ЛС — "
                "подберём индивидуально.")
        await (message.answer(text, reply_markup=booking_error_kb()) if send
               else message.edit_text(text, reply_markup=booking_error_kb()))
        return
    first = slots[0].astimezone(cfg.tz).date()
    await _render_calendar(message, first.year, first.month, slots, cfg, send=send)
```
Расширить `_render_calendar` флагом `send` — заменить сигнатуру и финальную выдачу:
```python
async def _render_calendar(message, year, month, slots, cfg, *, send: bool = False):
    ...  # тело без изменений до формирования text/reply_markup
    kb = booking_calendar_kb(year, month, free_dates,
                             has_prev=cur_mi > min_mi, has_next=cur_mi < max_mi)
    if send:
        await message.answer(_CALENDAR_TEXT, reply_markup=kb)
    else:
        await message.edit_text(_CALENDAR_TEXT, reply_markup=kb)
```
(существующие вызовы `_render_calendar(...)` без `send` продолжают редактировать —
дефолт `send=False`.)
Заменить тело `cb_booking_start` на:
```python
@router.callback_query(F.data.in_({"booking_start", "consultation_pay"}))
async def cb_booking_start(callback: CallbackQuery, gcal: GoogleCalendar,
                           booking_config: BookingConfig) -> None:
    await open_calendar(callback.message, gcal, booking_config, send=False)
```
Аналогично вынести `open_my_bookings` из `cb_my_bookings`:
```python
async def open_my_bookings(message, tg_id: int, *, send: bool) -> None:
    now = datetime.now(timezone.utc)
    async with get_session() as session:
        rows = (await session.execute(
            select(Booking).where(
                Booking.telegram_id == tg_id,
                Booking.status.in_(["pay_claimed", "confirmed"]),
                Booking.slot_start >= now,
            ).order_by(Booking.slot_start)
        )).scalars().all()
    if not rows:
        text = "○─── ☾ ───○\n\nУ тебя пока нет активных записей 🤍"
        kb = my_bookings_kb([])
    else:
        items = []
        for b in rows:
            slot = b.slot_start if b.slot_start.tzinfo else b.slot_start.replace(tzinfo=timezone.utc)
            items.append((format_slot_human(slot), b.id))
        text = "○─── ☾ ───○\n\n<b>✦ Твои записи</b>\n\nВыбери, что перенести ⇩"
        kb = my_bookings_kb(items)
    await (message.answer(text, reply_markup=kb) if send
           else message.edit_text(text, reply_markup=kb))
```
Заменить тело `cb_my_bookings` на `await open_my_bookings(callback.message, callback.from_user.id, send=False)`.

- [ ] **Step 5: open_main_menu в start.py + клавиатура на /start**

В `handlers/start.py`:
```python
from keyboards.reply import main_reply_kb


async def open_main_menu(message, *, send: bool) -> None:
    if send:
        await message.answer(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
    else:
        await message.edit_text(MAIN_MENU_TEXT, reply_markup=main_menu_kb())
```
В `cmd_start` заменить финальную строку на приветствие с нижней клавиатурой:
```python
    await message.answer(
        MAIN_MENU_TEXT + "\n\nБыстрые действия — на клавиатуре ниже 👇",
        reply_markup=main_reply_kb(),
    )
```
`cb_start_menu` оставить редактирующим inline-меню (уже так) — можно через `open_main_menu(callback.message, send=False)`.

- [ ] **Step 6: handlers/reply.py — текстовые хендлеры кнопок**

```python
from aiogram import Bot, F, Router
from aiogram.filters import StateFilter
from aiogram.types import Message

from booking_config import BookingConfig
from google_calendar import GoogleCalendar
from handlers.booking import open_calendar, open_my_bookings
from handlers.start import open_main_menu
from keyboards.inline import ask_lana_kb
from keyboards.reply import BTN_ASK, BTN_BOOK, BTN_MENU, BTN_MY
from ui import delete_safe

router = Router()


@router.message(StateFilter(None), F.text == BTN_BOOK)
async def reply_book(message: Message, gcal: GoogleCalendar,
                     booking_config: BookingConfig, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_calendar(message, gcal, booking_config, send=True)


@router.message(StateFilter(None), F.text == BTN_MY)
async def reply_my(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_my_bookings(message, message.from_user.id, send=True)


@router.message(StateFilter(None), F.text == BTN_MENU)
async def reply_menu(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await open_main_menu(message, send=True)


@router.message(StateFilter(None), F.text == BTN_ASK)
async def reply_ask(message: Message, bot: Bot) -> None:
    await delete_safe(bot, message.chat.id, message.message_id)
    await message.answer(
        "○─── ☾ ───○\n\nНапиши Лане в личные сообщения — она ответит 🤍",
        reply_markup=ask_lana_kb(),
    )
```
Добавить в `keyboards/inline.py`:
```python
def ask_lana_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Написать в ЛС", url=DM_URL)
    builder.button(text="⇦ В меню", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
```

- [ ] **Step 7: Подключить reply_router**

В `handlers/__init__.py` импорт `from .reply import router as reply_router` и в `setup_routers()` включить его ПЕРЕД `fallback_router` (после контентных, чтобы FSM-хендлеры в состоянии срабатывали первыми; reply-хендлеры и так фильтрованы `StateFilter(None)`):
```python
    router.include_router(reply_router)
    router.include_router(fallback_router)
```

- [ ] **Step 8: Прогнать — проходит**

Run: `PYTHONIOENCODING=utf-8 pytest tests/test_reply_keyboard.py -v` затем `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное. Существующие booking-тесты, дёргавшие `cb_booking_start`/`cb_my_bookings`, должны продолжать проходить (поведение колбэков не изменилось — та же правка экрана).

- [ ] **Step 9: py_compile**

Run: `python -m py_compile ui.py keyboards/reply.py handlers/reply.py handlers/booking.py handlers/start.py handlers/__init__.py keyboards/inline.py`
Expected: чисто.

- [ ] **Step 10: Commit**

```bash
git add keyboards/reply.py handlers/reply.py handlers/booking.py handlers/start.py handlers/__init__.py keyboards/inline.py tests/test_reply_keyboard.py
git commit -m "Нижняя клавиатура: быстрые действия + переиспользуемые экраны"
```

---

## Task 5: Доки + финальная проверка

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: Обновить доки**

README: нижняя клавиатура (📅 Записаться / 📋 Мои записи / 🏠 Меню / 💬 Вопрос Лане), уборка сообщений (поток причины переноса — одно сообщение, тексты клиента удаляются; уведомления Ланы сворачиваются). CLAUDE.md: модуль `ui.py`, паттерн якоря FSM, `main_reply_kb`, порядок роутеров (reply перед fallback).

- [ ] **Step 2: Полная компиляция**

Run: `python -m py_compile main.py database.py followup.py slots.py google_calendar.py booking_config.py formatting.py ui.py handlers/*.py keyboards/*.py`
Expected: чисто.

- [ ] **Step 3: Полный прогон**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: всё зелёное.

- [ ] **Step 4: Commit**

```bash
git add README.md CLAUDE.md
git commit -m "Доки: уборка сообщений и нижняя клавиатура"
```

---

## Self-Review (выполнено при написании плана)

**Spec coverage:**
- Хелперы delete_safe/edit_screen → Task 1. ✓
- Уборка причины переноса (якорь + удаление текста клиента) → Task 2. ✓
- Заявка вне объёма → отражено в Global Constraints. ✓
- Сворачивание уведомлений Ланы (confirm/reject pay, resched ok/no) → Task 3. ✓
- Нижняя клавиатура (4 кнопки, /start, StateFilter(None), «Вопрос Лане» с URL) → Task 4. ✓
- Переиспользуемые экраны (open_calendar/open_my_bookings/open_main_menu) → Task 4. ✓
- Порядок фильтрации (reply перед fallback, StateFilter(None)) → Task 4. ✓
- Обработка ошибок (delete_safe/edit_screen глотают) → Task 1, используется везде. ✓
- Доки → Task 5. ✓

**Placeholder scan:** конкретный код в каждом шаге; «обнови существующие тесты» относится к реальным тестам с явной инструкцией не ослаблять. ✓

**Type consistency:** `delete_safe(bot, chat_id, message_id)`, `edit_screen(bot, chat_id, message_id, text, reply_markup=None)` — одинаковы в Task 1 и вызовах Task 2/4. `open_calendar(message, gcal, cfg, *, send)`, `open_my_bookings(message, tg_id, *, send)`, `open_main_menu(message, *, send)` — определены в Task 4 и там же вызываются из reply.py. Константы кнопок `BTN_*` — reply.py и handlers/reply.py. ✓
