# Обновление структуры, текстов и тест «Кто управляет твоей жизнью?» — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Обновить меню/тексты бота (убрать менторство, сдвиг тона) и добавить интерактивный тест из 15 вопросов с 3 итоговыми уровнями.

**Architecture:** Тексты — правки строк-констант в существующих хендлерах. Тест — новый модуль данных `quiz_data.py` (чистые данные + функции подсчёта, покрыты pytest) и роутер `handlers/quiz.py` на FSM (как `lead.py`), одно редактируемое сообщение, кнопка «Назад» с перевыбором, без записи в БД.

**Tech Stack:** Python 3.11+, aiogram 3.x (FSM, InlineKeyboardBuilder), pytest (dev-зависимость, только для `quiz_data`).

## Global Constraints

- Полный источник финальных текстов: `docs/superpowers/specs/2026-07-26-bot-structure-texts-quiz-design.md`. При расхождении плана и спека — прав спек.
- `parse_mode=HTML` включён глобально; любой пользовательский текст в сообщения не подставляется (тест статичен).
- Стиль: символы `○ ☾ ● ★ ✦ ☆ ◯ ◐ ⇦ ⇨`, без цветных эмодзи на кнопках. Разрешён только 🤍 (уже используется в боте).
- Колбэки колбэков **не** вызывают `callback.answer()` вручную — это делает `CallbackSafetyMiddleware`.
- `callback_data` с параметром — через двоеточие, разбор `split(":", 1)`, значение валидировать.
- Тест: 15 вопросов, у каждого 4 варианта с баллами-перестановкой {1,2,3,4}; порядок показа «вразнобой» (не по возрастанию); суммы 15–60; уровни 15–30 / 31–46 / 47–60.
- Цена консультации: 70 минут, 100 € / 10000 ₽. Обе кнопки оплаты остаются.
- Кодировка Windows-консоли при прогоне: `PYTHONIOENCODING=utf-8`.

---

### Task 1: Тексты и удаление менторства

**Files:**
- Modify: `handlers/consultation.py` (тексты, отзывы; удалить `MENTORING_TEXT`, `cb_mentoring`, импорт `mentoring_kb`)
- Modify: `handlers/info.py` (`CHANNEL_TEXT`, `GAME_TEXT`)
- Modify: `handlers/lead.py:16-19` (убрать `"mentoring"` из `PRODUCTS`)
- Modify: `keyboards/inline.py` (убрать кнопку менторства из `personal_work_kb`; удалить `mentoring_kb`)

**Interfaces:**
- Produces: `personal_work_kb()` — теперь только «Точка сборки» + «Назад». `mentoring_kb` больше не существует (Task 5 её не использует).

- [ ] **Step 1: `keyboards/inline.py` — почистить менторство**

В `personal_work_kb()` удалить строку с кнопкой «Менторство (4 недели)». Должно остаться:
```python
def personal_work_kb():
    builder = InlineKeyboardBuilder()
    builder.button(text="Личная консультация «Точка сборки»", callback_data="consultation")
    builder.button(text="⇦ Назад", callback_data="start_menu")
    builder.adjust(1)
    return builder.as_markup()
```
Удалить функцию `mentoring_kb()` целиком (строки def…as_markup()).

- [ ] **Step 2: `handlers/consultation.py` — импорты и удаление менторства**

В импорте `from keyboards.inline import (...)` убрать `mentoring_kb`. Удалить константу `MENTORING_TEXT` целиком и хендлер `cb_mentoring` (декоратор `@router.callback_query(F.data == "mentoring")` + функция).

- [ ] **Step 3: `handlers/consultation.py` — переписать 3 текста**

Заменить `PERSONAL_WORK_TEXT` на:
```python
PERSONAL_WORK_TEXT = (
    "○─── ☾ ───○\n\n"
    "В личной работе я использую интегративный подход, работая сразу на нескольких "
    "уровнях: психология, коучинг и духовность.\n"
    "⇨ Это позволяет достигать фундаментальных изменений и менять не только состояние, "
    "но и саму логику выбора, которая в дальнейшем меняет результат и приводит "
    "к релевантному и желаемому опыту.\n\n"
    "Выбери подходящий тебе формат ⇩"
)
```
Заменить `CONSULTATION_TEXT` на:
```python
CONSULTATION_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>★ Личная консультация «Точка сборки»</b>\n\n"
    "Это глубокое погружение через соединение нескольких форматов.\n\n"
    "Я работаю в интегративном подходе, используя сразу несколько инструментов: "
    "психология, коучинг, духовность.\n\n"
    "● Длительность: 70 минут\n"
    "● Формат: онлайн (видеозвонок)\n"
    "● Стоимость: 100 € / 10000 ₽\n\n"
    "Во время встречи мы можем разобрать один или несколько запросов. "
    "Ты получишь конкретные рекомендации, практики и методы, которые дадут "
    "новый результат в жизни."
)
```
Заменить `CONSULTATION_HOW_TEXT` на:
```python
CONSULTATION_HOW_TEXT = (
    "<b>☾ Как проходит сессия?</b>\n\n"
    "● Онлайн через видеосвязь\n"
    "● Длительность: 70 минут\n\n"
    "Мы разбираем твой запрос или проблему, находя не только ответы на вопросы, "
    "но и выстраивая новую стратегию действия.\n\n"
    "<b>✦ Важно:</b> если конкретного запроса нет — мы сформируем его на встрече, "
    "либо я рекомендую тебе сначала забрать мой бесплатный гайд «Карта запроса» "
    "в главном меню, он идеально помогает выявить ключевые темы.\n\n"
    "⇨ После сессии я даю рекомендации и практики, составленные специально для тебя, "
    "чтобы закрепить результат."
)
```

- [ ] **Step 4: `handlers/consultation.py` — правки в отзывах (REVIEWS)**

В отзыве 2 (индекс 1) заменить `«коучинг сочетается с ченнелингом»` → `«коучинг сочетается с глубинной работой»`. Точная строка сейчас:
`"Это такой невероятный микс, когда коучинг сочетается с ченнелингом. Вовремя сказанные нужные слова "`
→ заменить `ченнелингом` на `глубинной работой`.

В отзыве 4 (индекс 3) строка:
`"Это был микс женского разговора, психологической консультации и сессии ченнелинга. "`
→ заменить `сессии ченнелинга` на `глубинной проработки`.

- [ ] **Step 5: `handlers/info.py` — CHANNEL_TEXT и GAME_TEXT**

Заменить `CHANNEL_TEXT` на:
```python
CHANNEL_TEXT = (
    "○─── ☾ ───○\n\n"
    "<b>☾ Бесплатный Telegram-канал</b>\n\n"
    "В своём канале я рассказываю про психологию и не только — делюсь полезными "
    "материалами, подкастами и практиками. Они помогут тебе гармонизировать "
    "состояние и найти ответы на вопросы даже раньше, чем они у тебя возникнут ✦"
)
```
В `GAME_TEXT` заменить последнюю строку `"● подробнее — в хайлайте игра"` на:
```python
    "Я собирала их через личный опыт, терапию и десятки диалогов с парами.\n\n"
    "● подробнее — в хайлайте игра"
```

- [ ] **Step 6: `handlers/lead.py` — убрать mentoring из PRODUCTS**

`PRODUCTS` привести к:
```python
PRODUCTS = {
    "consultation": "Консультация «Точка сборки»",
}
```

- [ ] **Step 7: Компиляция**

Run: `python -m py_compile handlers/consultation.py handlers/info.py handlers/lead.py keyboards/inline.py`
Expected: без ошибок, вывода нет.

- [ ] **Step 8: Проверка отсутствия мёртвых ссылок на менторство**

Run: `grep -rn "mentoring\|MENTORING\|Менторство" handlers keyboards`
Expected: пусто (совпадений нет).

- [ ] **Step 9: Commit**

```bash
git add handlers/consultation.py handlers/info.py handlers/lead.py keyboards/inline.py
git commit -m "Тексты: интегративный подход, удалено менторство, цена 100€/10000₽"
```

---

### Task 2: Данные теста `quiz_data.py` (+ pytest)

**Files:**
- Create: `quiz_data.py`
- Create: `tests/__init__.py` (пустой)
- Create: `tests/test_quiz_data.py`
- Create: `requirements-dev.txt`

**Interfaces:**
- Produces:
  - `INTRO_TEXT: str`
  - `QUESTIONS: list[dict]` — каждый `{"text": str, "options": list[tuple[str, int]]}`; ровно 15 элементов; у каждого 4 варианта; баллы каждого вопроса = перестановка `{1,2,3,4}`.
  - `MIN_SCORE = 15`, `MAX_SCORE = 60`
  - `def result_for_score(score: int) -> tuple[str, str, str]` → `(symbol, title, body)`; `body` уже содержит подставленный `{score}` и итоговую строку CTA.

- [ ] **Step 1: dev-зависимость**

Создать `requirements-dev.txt`:
```
pytest>=8.0
```
Установить: `pip install -r requirements-dev.txt`

- [ ] **Step 2: Написать падающий тест `tests/test_quiz_data.py`**

```python
import quiz_data as q


def test_fifteen_questions():
    assert len(q.QUESTIONS) == 15


def test_each_question_has_four_scored_options():
    for i, question in enumerate(q.QUESTIONS):
        opts = question["options"]
        assert len(opts) == 4, f"Q{i+1}: не 4 варианта"
        scores = sorted(s for _, s in opts)
        assert scores == [1, 2, 3, 4], f"Q{i+1}: баллы не {{1,2,3,4}}"


def test_options_not_in_ascending_score_order():
    # «вразнобой»: хотя бы у части вопросов порядок не по возрастанию,
    # и ни у одного вопроса варианты не идут строго 1,2,3,4 сверху вниз
    for i, question in enumerate(q.QUESTIONS):
        shown = [s for _, s in question["options"]]
        assert shown != [1, 2, 3, 4], f"Q{i+1}: варианты идут по возрастанию баллов"


def test_score_bounds():
    assert q.MIN_SCORE == 15
    assert q.MAX_SCORE == 60


def test_result_tiers_boundaries():
    assert q.result_for_score(15)[1].startswith("«В плену")
    assert q.result_for_score(30)[1].startswith("«В плену")
    assert q.result_for_score(31)[1].startswith("«На пороге")
    assert q.result_for_score(46)[1].startswith("«На пороге")
    assert q.result_for_score(47)[1].startswith("«Автономия")
    assert q.result_for_score(60)[1].startswith("«Автономия")


def test_result_full_range_covered():
    for score in range(15, 61):
        symbol, title, body = q.result_for_score(score)
        assert symbol and title and body
        assert str(score) in body  # балл подставлен в текст


def test_intro_present():
    assert "Анатомия свободы" in q.INTRO_TEXT
```

- [ ] **Step 3: Запустить тест — убедиться, что падает**

Run: `python -m pytest tests/test_quiz_data.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'quiz_data'`.

- [ ] **Step 4: Создать `quiz_data.py`**

Скопировать финальный контент из спека
`docs/superpowers/specs/2026-07-26-bot-structure-texts-quiz-design.md` (разделы «Экран-интро»,
«Вопросы (15)», «Результаты») в структуры ниже. Порядок вариантов в `options` — ровно как показан
в спеке (там уже «вразнобой»), второй элемент кортежа — балл из скобок.

```python
INTRO_TEXT = (
    "○─── ☾ ───○\n\n"
    "Рада видеть тебя в этом разделе 🤍\n\n"
    "Задумывалась ли ты, почему при обилии знаний в жизни всё равно будто что-то "
    "не складывается? Ты ставишь цели, но сливаешь их, постоянно откладывая «на потом». "
    "Мечтаешь о свободе, но подсознательно выбираешь тот же привычный режим выживания.\n\n"
    "Правда в том, что ты можешь жить по чужому сценарию. Психика и подсознание — "
    "живые системы. Если в них есть скрытые утечки, ты годами будешь ходить "
    "по замкнутому кругу.\n\n"
    "Этот интерактивный тест из 15 вопросов — твоя личная Анатомия свободы.\n"
    "Я не ищу «поломки». Я смотрю на твою жизнь объёмно и разделяю ответы на две зоны:\n\n"
    "☾ Тени (дефициты): где твоя свобода омрачается прошлым и страхами.\n"
    "★ Активы (ресурсы): твоя интуиция, амбиции и уникальная внутренняя сила.\n\n"
    "<b>✦ Что ты получишь в конце:</b>\n"
    "● Честный срез по направлениям: психология, коучинг, баланс сфер.\n"
    "● Автоматический подсчёт личной ёмкости: от сценарного плена до мастерства жизни.\n"
    "● Пошаговый вектор: как синтез психологии и работа с подсознанием бережно "
    "переводят «минусы» в мощную батарейку для изменений.\n\n"
    "Как проходить: выдели несколько спокойных минут, отвечай честно, выбирай вариант, "
    "который первым кажется верным.\n\n"
    "Готова узнать, где застрял твой истинный масштаб?\n"
    "⇩ Нажимай кнопку ниже."
)

# Каждый вопрос: {"text": ..., "options": [(текст, балл), ...]} в показанном порядке.
QUESTIONS = [
    {
        "text": "Когда перед тобой стоит выбор, который может кардинально изменить "
                "жизнь, на что ты опираешься в первую очередь?",
        "options": [
            ("Прислушиваюсь к мнениям, но принимаю решение сам/а, даже если "
             "столкнусь с чужим недовольством.", 3),
            ("Испытываю тревогу и панику. Ищу авторитетов и советы извне, "
             "потому что боюсь ошибиться.", 1),
            ("Опираюсь на свои ценности, внутреннюю устойчивость и собственный "
             "анализ, не оглядываясь на чужие ожидания.", 4),
            ("Пытаюсь нащупать свои желания, но если близкие не одобрят — "
             "скорее уступлю их мнению.", 2),
        ],
    },
    # ... Q2..Q15 — перенести из спека в том же формате и порядке ...
]

MIN_SCORE = 15
MAX_SCORE = 60

# (нижняя граница, верхняя граница, символ, заголовок, тело с {score})
_TIERS = [
    (15, 30, "◯", "«В плену сценарных автоматизмов»",
     "Твоя жизнь сейчас сильно напоминает заученный сценарий. Большая часть "
     "ресурса уходит не на развитие, а на то, чтобы «заслуживать» одобрение, "
     "соответствовать правилам и защищаться от тревоги и чужих ожиданий. "
     "Истинный масштаб пока заблокирован страхом ошибки.\n\n"
     "⇨ Чтобы разобрать свои сценарные блоки индивидуально и понять, как бережно "
     "перевести дефициты в мощный жизненный прорыв — напиши мне в личные сообщения, "
     "и мы подберём время для установочного разбора."),
    (31, 46, "◐", "«На пороге своего Я: точка роста»",
     "У тебя отличный уровень осознанности и рефлексии. Ты всё понимаешь, но на "
     "выходе на новый уровень (доход, проявление, масштаб) включаются "
     "предохранители — прокрастинация и самосаботаж. Пробивать этот потолок на силе "
     "воли может приводить к выгоранию.\n\n"
     "⇨ Чтобы разобрать, где именно стоят предохранители, и перевести дефициты "
     "в ресурс — напиши мне в личные сообщения, и мы подберём время для "
     "установочного разбора."),
    (47, 60, "●", "«Автономия и мастерство жизни»",
     "Поздравляю. Ты свободна от навязанных установок, умеешь выстраивать границы "
     "и опираться на свои ценности. Ты выдерживаешь неопределённость и действуешь "
     "интуитивно, чувствуя, что будет лучше для тебя.\n\n"
     "⇨ Если захочешь усилить масштаб и разобрать точки следующего роста — напиши "
     "мне в личные сообщения, и мы подберём время для установочного разбора."),
]


def result_for_score(score: int) -> tuple[str, str, str]:
    """Вернуть (символ, заголовок, тело) для суммы баллов. Тело со вставленным score."""
    for lo, hi, symbol, title, body in _TIERS:
        if lo <= score <= hi:
            full = (
                "○─── ☾ ───○\n\n"
                f"{symbol} Твой результат: {score}/60\n"
                f"{title}\n\n"
                f"{body}"
            )
            return symbol, title, full
    # score вне 15..60 быть не может (15 вопросов × 1..4), но подстрахуемся
    raise ValueError(f"score {score} вне диапазона {MIN_SCORE}..{MAX_SCORE}")
```
Затем перенести Q2–Q15 из спека (там 15 блоков с точными формулировками и баллами в скобках)
в список `QUESTIONS` в том же порядке вариантов.

- [ ] **Step 5: Запустить тесты — убедиться, что проходят**

Run: `python -m pytest tests/test_quiz_data.py -v`
Expected: PASS (8 тестов). Если `test_each_question_has_four_scored_options` падает — в каком-то
вопросе баллы не образуют {1,2,3,4}; сверить со спеком.

- [ ] **Step 6: Commit**

```bash
git add quiz_data.py tests/__init__.py tests/test_quiz_data.py requirements-dev.txt
git commit -m "Данные теста «Кто управляет твоей жизнью?» + юнит-тесты подсчёта"
```

---

### Task 3: Клавиатуры теста

**Files:**
- Modify: `keyboards/inline.py` (добавить 3 функции; `DM_URL` уже определён вверху)

**Interfaces:**
- Consumes: `DM_URL` (уже есть в файле).
- Produces:
  - `quiz_intro_kb()`
  - `quiz_question_kb(options: "list[tuple[str, int]]", is_first: bool)`
  - `quiz_result_kb()`

- [ ] **Step 1: Добавить функции в конец `keyboards/inline.py`**

```python
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
```

- [ ] **Step 2: Компиляция**

Run: `python -m py_compile keyboards/inline.py`
Expected: без ошибок.

- [ ] **Step 3: Commit**

```bash
git add keyboards/inline.py
git commit -m "Клавиатуры теста: интро, вопрос, результат"
```

---

### Task 4: Хендлер теста `handlers/quiz.py`

**Files:**
- Create: `handlers/quiz.py`

**Interfaces:**
- Consumes: `quiz_data.INTRO_TEXT`, `quiz_data.QUESTIONS`, `quiz_data.result_for_score`;
  `keyboards.inline.quiz_intro_kb`, `quiz_question_kb`, `quiz_result_kb`.
- Produces: `router` (aiogram Router) — подключается в Task 5.

- [ ] **Step 1: Создать `handlers/quiz.py`**

FSM хранит `answers` (dict индекс→балл) и `idx` (текущий вопрос). Одно сообщение редактируется.
```python
from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery

from keyboards.inline import quiz_intro_kb, quiz_question_kb, quiz_result_kb
from quiz_data import INTRO_TEXT, QUESTIONS, result_for_score

router = Router()


class Quiz(StatesGroup):
    in_progress = State()


def _question_text(idx: int) -> str:
    q = QUESTIONS[idx]
    return (
        "○─── ☾ ───○\n\n"
        f"Вопрос {idx + 1}/{len(QUESTIONS)}\n\n"
        f"{q['text']}"
    )


async def _show_question(callback: CallbackQuery, idx: int) -> None:
    await callback.message.edit_text(
        _question_text(idx),
        reply_markup=quiz_question_kb(QUESTIONS[idx]["options"], is_first=(idx == 0)),
    )


@router.callback_query(F.data == "quiz_intro")
async def cb_quiz_intro(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text(INTRO_TEXT, reply_markup=quiz_intro_kb())


@router.callback_query(F.data == "quiz_begin")
async def cb_quiz_begin(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(Quiz.in_progress)
    await state.update_data(answers={}, idx=0)
    await _show_question(callback, 0)


@router.callback_query(Quiz.in_progress, F.data.startswith("quiz_ans:"))
async def cb_quiz_answer(callback: CallbackQuery, state: FSMContext) -> None:
    try:
        score = int(callback.data.split(":", 1)[1])
    except ValueError:
        return
    if not 1 <= score <= 4:
        return
    data = await state.get_data()
    answers = dict(data.get("answers", {}))
    idx = data.get("idx", 0)
    answers[idx] = score

    if idx + 1 < len(QUESTIONS):
        idx += 1
        await state.update_data(answers=answers, idx=idx)
        await _show_question(callback, idx)
    else:
        total = sum(answers.values())
        await state.clear()
        _, _, body = result_for_score(total)
        await callback.message.edit_text(body, reply_markup=quiz_result_kb())


@router.callback_query(Quiz.in_progress, F.data == "quiz_back")
async def cb_quiz_back(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    idx = data.get("idx", 0)
    if idx == 0:
        return
    idx -= 1
    await state.update_data(idx=idx)
    await _show_question(callback, idx)
```

Примечание: FSM-хранилище — dict-ключи `answers` могут сериализоваться как строки при некоторых
storage; используем MemoryStorage (по умолчанию в проекте), где ключи-int сохраняются. Сумма
берётся из `answers.values()`, поэтому тип ключа роли не играет.

- [ ] **Step 2: Компиляция**

Run: `python -m py_compile handlers/quiz.py`
Expected: без ошибок.

- [ ] **Step 3: Commit**

```bash
git add handlers/quiz.py
git commit -m "Хендлер теста: интро, вопросы на FSM, Назад, результат"
```

---

### Task 5: Подключение роутера, кнопка в меню, финальная проверка

**Files:**
- Modify: `handlers/__init__.py` (импорт и include `quiz_router`)
- Modify: `keyboards/inline.py` (`main_menu_kb` — добавить кнопку теста)

**Interfaces:**
- Consumes: `handlers.quiz.router`, `cb_quiz_intro` (callback `quiz_intro`).

- [ ] **Step 1: Зарегистрировать роутер в `handlers/__init__.py`**

Добавить импорт `from .quiz import router as quiz_router` и `router.include_router(quiz_router)`
(после `info_router`).

- [ ] **Step 2: Кнопка теста в `main_menu_kb` (`keyboards/inline.py`)**

Добавить последней кнопкой перед `builder.adjust(1)`:
```python
    builder.button(
        text="✦ Пройти тест «Кто управляет твоей жизнью?»",
        callback_data="quiz_intro",
    )
```

- [ ] **Step 3: Полная компиляция**

Run: `python -m py_compile main.py database.py middlewares.py filters.py followup.py handlers/*.py keyboards/inline.py quiz_data.py`
Expected: без ошибок.

- [ ] **Step 4: Тесты данных ещё раз**

Run: `python -m pytest tests/ -v`
Expected: PASS.

- [ ] **Step 5: Проверка полноты колбэков (каждый callback_data имеет хендлер)**

Run: `grep -rn "callback_data" keyboards/inline.py`
Сверить, что для каждого `callback_data` теста (`quiz_intro`, `quiz_begin`, `quiz_ans:*`,
`quiz_back`, `start_menu`) есть хендлер в `handlers/quiz.py` или `handlers/start.py`.
Expected: мёртвых кнопок нет.

- [ ] **Step 6: Рантайм-смоук (через /verify или ручной прогон)**

Запустить бота с тестовым токеном (или прогнать поток через фейковую сессию, как описано в
`CLAUDE.md`): `/start` → «Пройти тест» → «Начать тест» → ответить на 15 вопросов →
убедиться, что показывается корректный уровень; проверить «Назад» (возврат и перевыбор);
проверить «Пройти заново» и «В меню». Крайние суммы: все ответы «1» → 15 → ◯; все «4» → 60 → ●.

- [ ] **Step 7: Commit**

```bash
git add handlers/__init__.py keyboards/inline.py
git commit -m "Подключён тест в меню и роутер; финальная сборка"
```

---

## Self-Review (выполнено при написании плана)

**Покрытие спека:**
- Меню +кнопка теста → Task 5. Удаление менторства → Task 1. Сдвиг тона (личная работа,
  консультация, «как проходит», канал, игра, отзывы) → Task 1. Цена 100€/10000₽ → Task 1.
  Тест (интро/15 вопросов/3 результата, подсчёт, границы) → Task 2. Клавиатуры теста → Task 3.
  Хендлер FSM + Назад + результат → Task 4. Регистрация → Task 5.
- `CONSULTATION_WHO_TEXT`, `GIFT_TEXT`, `MAIN_MENU_TEXT` (кроме кнопки) — вне скоупа (не трогаем).
- Обновление сумм Tribute — вне скоупа (делает Лана).

**Плейсхолдеры:** в `QUESTIONS` намеренно оставлен маркер `# ... Q2..Q15` — это указание перенести
вербатим-контент из in-repo спека (полные формулировки там), а не «додумать». Остальной код полный.

**Согласованность типов:** `quiz_question_kb(options, is_first)` вызывается с
`QUESTIONS[idx]["options"]` (list[tuple[str,int]]) и `idx==0` — совпадает. `result_for_score`
возвращает `(symbol, title, body)`, хендлер использует `body` — совпадает. Колбэки
`quiz_intro/quiz_begin/quiz_ans/quiz_back` определены в Task 4 и используются в клавиатурах Task 3 —
имена совпадают.
