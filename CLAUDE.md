# CLAUDE.md

Продающий Telegram-бот (воронка) для эксперта Ланы: прогрев, презентация услуг,
запись на консультацию по слотам, заявки, выдача бесплатного гайда-лид-магнита,
рассылки и дожим-напоминания.

## Стек

- Python 3.12, **aiogram 3.x** (FSM, роутеры, middleware)
- SQLAlchemy 2.0 (async, `Mapped`/`mapped_column` style) + asyncpg
- PostgreSQL (Railway), в тестах — sqlite+aiosqlite
- Docker (`python:3.12-slim`), деплой на Railway (polling, не webhook)

## Запуск

```bash
pip install -r requirements.txt
# заполнить .env по образцу .env.example
python main.py
```

Обязательные env-переменные: `BOT_TOKEN`, `ADMIN_IDS`, `DATABASE_URL`.
`ADMIN_IDS` — список Telegram ID через запятую (`111,222`). Старый `ADMIN_ID`
(один id) поддерживается как fallback. `TZ=Europe/Prague`.

## Архитектура

- `main.py` — точка входа. Парсит `ADMIN_IDS`, вешает middleware, регистрирует
  глобальный `dp.errors()`, запускает фоновую задачу дожима (`followup_loop`),
  прокидывает `admin_ids` в polling (доступны в хендлерах и фильтрах как
  workflow data — аргумент `admin_ids: list[int]`).
- `database.py` — модели (`User`, `Lead`, `Booking`, `Setting`, `Event`) и
  подключение. Схема создаётся через `create_all` при старте (создаёт только
  отсутствующие таблицы, колонки в существующих не меняет). Поверх этого
  `init_db` на Postgres идемпотентно доводит схему списком `_MIGRATIONS`
  (`ALTER TABLE bookings ADD COLUMN IF NOT EXISTS ...` для полей переноса) —
  для добавления новых колонок ручной `DROP TABLE` не нужен, только когда
  меняется тип/состав колонок несовместимо. На sqlite (тесты) миграции не
  нужны — `create_all` сразу создаёт таблицу по актуальным моделям.
- `followup.py` — дожим: пользователь открыл экран консультации и за час не
  оставил заявку/не выбрал слот → один раз приходит «могу ли чем-то помочь?».
  Работает поверх таблицы `events` (переживает рестарты), окно 48 часов,
  повторно не шлёт (маркер — событие `followup_sent`).
- `middlewares.py`:
  - `CallbackSafetyMiddleware` — всегда шлёт `callback.answer()` в `finally`
    и гасит `TelegramBadRequest: message is not modified`.
  - `EventLoggingMiddleware` — пишет каждое нажатие/команду в таблицу `events`.
- `filters.py` — `IsAdmin` (сверяет `from_user.id` с `admin_ids`).
- `booking_config.py` — читает из env расписание (`WORK_TIMES`,
  `WORK_WEEKDAYS`), горизонт/лид-тайм/холд (`BOOKING_HORIZON_DAYS`,
  `BOOKING_LEAD_HOURS`, `BOOKING_HOLD_MINUTES`) и таймзону в один
  frozen-датакласс `BookingConfig`, прокидывается в polling как workflow
  data (`booking_config: BookingConfig` в хендлерах).
- `google_calendar.py` — `GoogleCalendar`: `busy()` (freebusy-запрос по двум
  календарям — рабочему `CALENDAR_ID_BOOKINGS` и личному
  `CALENDAR_ID_PERSONAL`), `create_event()` / `delete_event()` в
  `CALENDAR_ID_BOOKINGS`. `GoogleCalendar.from_env()` читает
  `GOOGLE_SA_CREDENTIALS` (путь к JSON-файлу или сам JSON строкой),
  прокидывается в polling как `gcal: GoogleCalendar`.
- `slots.py` — чистая функция `free_slots(now, busy, holds, ...)`: считает
  свободные слоты по расписанию `BookingConfig` минус занятость Google
  минус активные холды в БД. Без побочных эффектов, легко тестируется.
- `formatting.py` — `format_slot_human()` (слот в Праге + Мск, день недели),
  `PRICE_TEXT` (цена консультации).
- `ui.py` — два хелпера для гигиены сообщений, на них держится вся уборка
  переписки в handlers/: `delete_safe(bot, chat_id, message_id)` — удалить
  сообщение, глотая `TelegramAPIError` (старше 48ч, уже удалено, нет прав);
  `edit_screen(bot, chat_id, message_id, text, reply_markup=None)` —
  отредактировать «экран» тем же способом, глотая «not modified» /
  «message to edit not found». Оба — no-op при ошибке, вызывающему коду не
  нужно оборачивать их в try/except.
- `handlers/` — по одному роутеру на файл, собираются в `setup_routers()`;
  `reply_router` зарегистрирован **перед** `fallback_router`, но порядок
  между ними функционально не важен: `fallback.py` ловит только
  колбэки (`quiz_ans:*`, `quiz_back`), без единого message-хендлера, так что
  перехватить текст кнопок нижней клавиатуры он в принципе не может. Тексты
  кнопок безопасны сами по себе — за счёт `StateFilter(None)` + точного
  `F.text == "..."` в `reply.py` (см. ниже):
  - `admin.py` — `/set_guide`, `/broadcast`, `/admin`, `/cancel`, `/bookings`
    (список ближайших `pay_claimed`/`confirmed` записей), подтверждение
    (`confirm_pay:<id>`, здесь же создаётся событие в календаре) и
    отклонение (`reject_pay:<id>`) оплаты, подтверждение (`resched_ok:<id>`)
    и отклонение (`resched_no:<id>`) переноса записи. После каждого действия
    карточка-уведомление у Ланы схлопывается в короткую итоговую строку
    (`callback.message.edit_text("✅ … — оплата подтверждена")` и т.п.) —
    вместо того чтобы оставлять развёрнутое уведомление висеть в чате.
    Роутер целиком под `IsAdmin`.
  - `booking.py` — выбор дня/времени из реальных Google-слотов, холд слота в
    `bookings` на `BOOKING_HOLD_MINUTES`, экран оплаты, «Я оплатил(а)»,
    лимит активных записей (`MAX_ACTIVE_BOOKINGS`), «Мои записи»
    (`my_bookings`) и перенос (`resched:<id>` → выбор нового слота →
    сразу или через согласие Ланы, `RESCHEDULE_THRESHOLD`). Экраны записи
    вынесены в переиспользуемые функции `open_calendar(message, gcal, cfg,
    *, send)` и `open_my_bookings(message, tg_id, *, send)` — `send=True`
    шлёт новым сообщением (зовёт `handlers/reply.py` из нижней клавиатуры),
    `send=False` редактирует переданное `message` (зовут inline-колбэки).
    Перенос <24ч использует паттерн «якорь»: id сообщения с вопросом о
    причине сохраняется в FSM (`resched_screen_id`), а хендлер
    `RescheduleForm.reason` при ответе клиента удаляет его текст
    (`delete_safe`) и редактирует тот же якорь (`edit_screen`) — один экран
    вместо цепочки сообщений «спроси → ответь → спасибо».
  - `fallback.py` — ловит колбэки старого квиза (`quiz_ans:*`, `quiz_back`),
    оставшиеся в сообщениях после рестарта бота и сброса FSM меню.
  - `lead.py` — FSM-заявка (имя → запрос → контакт), уведомление админам.
  - `start.py` — `/start`, `/id`, возврат в главное меню. `/start` шлёт
    приветственный текст с `reply_markup=main_reply_kb()` (нижняя
    клавиатура), пришпиливает пользователя в БД; богатое inline-меню
    (`main_menu_kb()`) само по себе на `/start` не шлётся — оно открывается
    функцией `open_main_menu(message, *, send)` по кнопке «🏠 Меню» или
    колбэку `start_menu`.
  - `reply.py` — хендлеры нижней клавиатуры (`keyboards/reply.py`):
    «📅 Записаться» → `open_calendar(..., send=True)`, «📋 Мои записи» →
    `open_my_bookings(..., send=True)`, «🏠 Меню» → `open_main_menu(...,
    send=True)`, «💬 Вопрос Лане» → текст со ссылкой (`ask_lana_kb()`).
    Каждый хендлер сперва удаляет сообщение с текстом кнопки
    (`delete_safe`), затем шлёт экран. Все фильтруются `StateFilter(None)`
    (`F.text == BTN_*`) — не перехватывают текст, пока пользователь в
    какой-то FSM-форме (например, вводит причину переноса).
  - `consultation.py`, `info.py` — контентные экраны (тексты + клавиатуры).
- `keyboards/inline.py` — все inline-клавиатуры и внешние URL (одним блоком сверху).
- `keyboards/reply.py` — `main_reply_kb()`: постоянная `ReplyKeyboardMarkup`
  (`resize_keyboard=True`, `is_persistent=True`) на 4 кнопки — константы
  `BTN_BOOK` (📅 Записаться), `BTN_MY` (📋 Мои записи), `BTN_MENU` (🏠 Меню),
  `BTN_ASK` (💬 Вопрос Лане).

## Флоу записи на слот (booking)

`Записаться` → бот дёргает `GoogleCalendar.busy()` по обоим календарям и
считает `slots.free_slots()` (будни по `WORK_TIMES`, минус занятость, минус
занятые слоты в БД, минус `BOOKING_LEAD_HOURS`/`BOOKING_HORIZON_DAYS`) →
выбор дня → выбор времени → перед вставкой проверяется лимит
`MAX_ACTIVE_BOOKINGS = 5` активных записей клиента (`_active_booking_count`:
`held` неистёкшие + `pay_claimed`/`confirmed` в будущем) → слот **держится**
за клиентом: `Booking(status="held", held_until=now+BOOKING_HOLD_MINUTES)`
(никакого события в календаре ещё нет) → экран оплаты (Tribute-ссылки ₽/€,
`PRICE_TEXT`) → «✓ Я оплатил(а)» проверяет, что бронь всё ещё `held`
(защита от гонки двойного клика), переводит статус в `pay_claimed` (клиенту
«Принято, проверяем», админам — кнопки «✅ Подтвердить» / «❌ Отклонить»);
событие в `CALENDAR_ID_BOOKINGS` **ещё не создаётся** — до подтверждения
слот занят только записью в БД. Занятость для `free_slots()` на этом
участке считает `_occupied_slots()`: `held` неистёкшие **и** `pay_claimed`
(и то, и другое — ещё без события в календаре).

Лана подтверждает (`cb_confirm_pay`) — только на этом шаге вызывается
`gcal.create_event()`, статус переходит в `confirmed`, клиенту «Вы
оплатили, спасибо…»; если `create_event()` упал — `calendar_sync_failed=True`,
админам предупреждение «оформи вручную», но статус всё равно `confirmed`.
Или отклоняет (`cb_reject_pay`, status `cancelled`; событие удалять не
нужно, т.к. оно ещё не создавалось на этом статусе — `delete_event()`
вызывается только если `google_event_id` уже был проставлен), клиенту
«оплату не нашли, слот освобождён».

**Мои записи / перенос.** «Мои записи» (`my_bookings`) — список будущих
`pay_claimed`/`confirmed` записей клиента, у каждой кнопка «Перенести»
(`resched:<id>`) → тот же календарь свободных слотов (`_render_calendar` с
`prefix="resched"`) → выбор дня/времени. Если до исходного `slot_start`
ещё ≥ `RESCHEDULE_THRESHOLD` (`timedelta(hours=24)`) — перенос применяется
сразу через `apply_reschedule()` (для записи с уже созданным событием —
`delete_event()` старого + `create_event()` нового, `slot_start` меняется).
Если осталось < 24ч — бот просит причину (FSM `RescheduleForm.reason`), при
этом вопрос о причине остаётся единственным сообщением-«якорем» (id
сохранён в `resched_screen_id`): ответ клиента удаляется (`delete_safe`), а
сам якорь редактируется (`edit_screen`) вместо того, чтобы плодить новую
переписку. Дальше бот ставит
`Booking.reschedule_to/reschedule_reason/reschedule_status="pending"`,
админам приходят кнопки «✅ Подтвердить перенос» (`resched_ok:<id>`) /
«❌ Отклонить перенос» (`resched_no:<id>`). Approve — перепроверяет, что
`reschedule_to` всё ещё в `free_slots()`; если свободен — двигает через
`apply_reschedule()` и чистит поля переноса; если уже заняли — оставляет
запись на старом слоте, поля переноса тоже чистятся, клиенту и админу
сообщение «слот заняли, перенос не выполнен». Reject (`resched_no`) —
**отменяет саму запись** (`status="cancelled"`, `delete_event()` если
событие уже было), оплата не возвращается, клиенту сообщение «перенос
отклонён, запись отменена, оплата не возвращается».

Просроченные холды (`held`, `held_until` в прошлом) никто явно не чистит —
они просто перестают попадать в `free_slots()`/`_occupied_slots()` и не
мешают новым бронированиям; фоновой задачи-уборщика нет (лениво, по
конструкции). Google недоступен на любом из шагов (показ слотов/дней,
бронирование, оплата, перенос) → пользователю понятный текст + кнопка
«Попробовать снова» / «Написать в ЛС», не мёртвая кнопка.

Tribute не шлёт вебхуков — оплата подтверждается вручную админом, автоматики
здесь нет и быть не может без смены платёжки. Гонка «два клиента бронируют
один и тот же слот одновременно» подавляется проверкой «слот всё ещё в
`free_slots()`» перед вставкой, но не UNIQUE-констрейнтом на уровне БД —
для объёма этого бота риск принят как есть. Та же проверка «слот ещё
свободен» защищает и перенос — как самостоятельный (`cb_resched_slot`),
так и подтверждаемый Ланой (`cb_resched_ok`).

## Конвенции

- Хендлеры колбэков **не вызывают** `callback.answer()` вручную — это делает
  `CallbackSafetyMiddleware`. Исключение: ответ с текстом/алертом
  (`callback.answer("…", show_alert=True)`) — можно, повторный пустой answer
  от middleware подавляется.
- Фильтруй колбэки через `F.data == "..."`, а не `lambda` (единообразие).
- `callback_data` с параметром — через двоеточие: `lead_start:consultation`,
  `book_slot:2026-07-21:14:00`, `paid:5`. Разбор — `split(":", n)`, значения
  валидировать (whitelist / диапазон / принадлежность записи пользователю).
- Переименовал колбэк, который уже ушёл пользователям в старых сообщениях? —
  оставь алиас (`F.data.in_({"new", "old"})`), пример: `booking_start` +
  legacy `consultation_pay`.
- Любой пользовательский текст, попадающий в HTML-сообщение (уведомления
  админам), экранируй через `aiogram.html.quote(...)` — `parse_mode=HTML`
  включён глобально.
- Тексты сообщений — модульные константы (`UPPER_SNAKE`) рядом с хендлером.
- Декоративная типографика: `○─── ☾ ───○`, символы `✦ ☾ ⇨ ●`. Цветные эмодзи
  на кнопках не используем (осознанное решение владельца).

## Подводные камни

- **Бот не может писать первым.** Уведомления о заявках/бронях и рассылка
  доходят только до тех, кто нажал `/start` у бота. Новый админ обязан открыть
  бота и нажать `/start`, иначе уведомления ему не придут.
- **Приватные ссылки на канал** (`t.me/c/...`) открываются только у подписчиков.
  Лид-магнит (гайд) поэтому отдаётся файлом через `/set_guide` (file_id хранится
  в таблице `settings`), а не ссылкой. Ссылка осталась как фолбэк.
- Рассылка `/broadcast` использует `copy_message` — работает с **любым** типом
  контента (текст, фото, видео, голосовые, кружки), без пометки «переслано»,
  с паузой ~0.05с между отправками и обработкой `TelegramRetryAfter`.
- `zoneinfo("Europe/Prague")` требует пакет `tzdata` (есть в requirements) —
  без него упадёт на Windows и в slim-образах.
- Каждый новый `callback_data` в клавиатуре должен иметь хендлер — иначе кнопка
  молча ничего не делает.
- Сравнение дат из БД: sqlite отдаёт наивные datetime, postgres — aware.
  В `followup.py` есть `_as_utc()` — используй его при сравнениях.

## Проверка изменений

```bash
python -m py_compile main.py database.py middlewares.py filters.py followup.py slots.py google_calendar.py booking_config.py formatting.py ui.py handlers/*.py keyboards/*.py
```

Автотесты есть (`tests/`, pytest) — гоняют хендлеры через фейковую сессию
(`BaseSession` с подменённым `make_request`) на `sqlite+aiosqlite:///:memory:`
и `dp.feed_update()`, плюс юнит-тесты чистых функций (`slots.free_slots`,
`formatting.format_slot_human`, `booking_config.load`). Так проверялись
FSM-заявка, бронирование слотов из Google-занятости, холд/оплата/отклонение,
дожим, напоминание за 24ч и рассылка. Важно: workflow data в тесте задаётся
`dp["admin_ids"] = [...]`, `dp["booking_config"] = ...`, `dp["gcal"] = ...`
(или фейковый `GoogleCalendar`), FSM-ключ — пара (chat, user), поэтому у
фейковых колбэков chat должен быть личкой пользователя. Прогон:
`PYTHONIOENCODING=utf-8 python -m pytest -q`. На Windows-консоли обязательно
с `PYTHONIOENCODING=utf-8`, иначе падает на кириллице в выводе.
