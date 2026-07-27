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
  подключение. Схема создаётся через `create_all` при старте — **миграций нет**
  (`create_all` не меняет существующие таблицы, только создаёт новые).
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
- `handlers/` — по одному роутеру на файл, собираются в `setup_routers()`:
  - `admin.py` — `/set_guide`, `/broadcast`, `/admin`, `/cancel`, `/bookings`
    (список ближайших `pay_claimed`/`confirmed` записей), подтверждение
    (`confirm_pay:<id>`) и отклонение (`reject_pay:<id>`) оплаты. Роутер
    целиком под `IsAdmin`.
  - `booking.py` — выбор дня/времени из реальных Google-слотов, холд слота в
    `bookings` на `BOOKING_HOLD_MINUTES`, экран оплаты, «Я оплатил(а)».
  - `fallback.py` — ловит колбэки старого квиза (`quiz_ans:*`, `quiz_back`),
    оставшиеся в сообщениях после рестарта бота и сброса FSM меню.
  - `lead.py` — FSM-заявка (имя → запрос → контакт), уведомление админам.
  - `start.py` — `/start`, `/id`, возврат в главное меню.
  - `consultation.py`, `info.py` — контентные экраны (тексты + клавиатуры).
- `keyboards/inline.py` — все inline-клавиатуры и внешние URL (одним блоком сверху).

## Флоу записи на слот (booking)

`Записаться` → бот дёргает `GoogleCalendar.busy()` по обоим календарям и
считает `slots.free_slots()` (будни по `WORK_TIMES`, минус занятость, минус
активные холды, минус `BOOKING_LEAD_HOURS`/`BOOKING_HORIZON_DAYS`) → выбор
дня → выбор времени → слот **держится** за клиентом: `Booking(status="held",
held_until=now+BOOKING_HOLD_MINUTES)` (никакого события в календаре ещё нет)
→ экран оплаты (Tribute-ссылки ₽/€, `PRICE_TEXT`) → «✓ Я оплатил(а)»
проверяет, что бронь всё ещё `held` (защита от гонки двойного клика),
создаёт событие в `CALENDAR_ID_BOOKINGS` через `gcal.create_event()`,
переводит статус в `pay_claimed` (клиенту «Принято, проверяем», админам —
кнопки «✅ Подтвердить» / «❌ Отклонить»; если `create_event()` упал —
`calendar_sync_failed=True`, админам предупреждение «оформи вручную») →
Лана подтверждает (status `confirmed`, клиенту «Вы оплатили, спасибо…») или
отклоняет (status `cancelled`, `gcal.delete_event()`, клиенту «оплату не
нашли, слот освобождён»).

Просроченные холды (`held`, `held_until` в прошлом) никто явно не чистит —
они просто перестают попадать в `free_slots()`/`_active_holds()` и не мешают
новым бронированиям; фоновой задачи-уборщика нет (лениво, по конструкции).
Google недоступен на любом из трёх шагов (показ слотов/дней, бронирование,
оплата) → пользователю понятный текст + кнопка «Попробовать снова» /
«Написать в ЛС», не мёртвая кнопка.

Tribute не шлёт вебхуков — оплата подтверждается вручную админом, автоматики
здесь нет и быть не может без смены платёжки. Гонка «два клиента бронируют
один и тот же слот одновременно» подавляется проверкой «слот всё ещё в
`free_slots()`» перед вставкой, но не UNIQUE-констрейнтом на уровне БД —
для объёма этого бота риск принят как есть.

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
python -m py_compile main.py database.py middlewares.py filters.py followup.py slots.py google_calendar.py booking_config.py formatting.py handlers/*.py keyboards/inline.py
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
