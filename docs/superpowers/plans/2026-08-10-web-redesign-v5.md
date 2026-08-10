# Лендинг v5 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Перенести новый лендинг Ланы из self-contained бандла в `web/` как
обычную статику — без React, без сборки, со своими шрифтами и пережатым фото.

**Architecture:** Одноразовый python-скрипт распаковывает бандл (ассеты в
`web/assets/`, разметка в `web/index.html`), после чего страница доводится
руками: аккордеон FAQ на `<details>`, hover-стили в CSS, ссылки. Скрипт живёт
в scratchpad и в репозиторий не коммитится — исходного бандла (16,8 МБ) в репо
тоже нет, так что коммитить скрипт-сироту незачем; воспроизводимость держит
этот план. Регрессии ловит новый pytest-файл, проверяющий готовую страницу
структурно.

**Tech Stack:** Python 3.12 + Pillow (пережатие фото), pytest (проверки
страницы), статический HTML/CSS без JS, Vercel без сборки.

## Global Constraints

- Спека: `docs/superpowers/specs/2026-08-10-web-redesign-v5-design.md`.
- Исходный бандл: `C:/Users/Dell/Downloads/Lana Leonovich - сайт.html`.
- Рабочая ветка: `feature/web-redesign-v5` (уже создана от `master`).
- **На готовой странице не должно остаться ни одного `<script>`.**
- Разметка и CSS переносятся дословно; переписывается только то, что явно
  перечислено в задачах. Вёрстку не «улучшаем».
- Палитра: `#C8705A` акцент, `#1C1C2E` текст, `#6B6560` вторичный,
  `#2B3366` тёмный блок, `#E8DDD4` границы, `#F5EDE3` подложка,
  `#FAFAF7` фон, `#E0A48F` акцент на тёмном.
- Шрифты только свои: `fonts.googleapis.com` и `fonts.gstatic.com` на странице
  встречаться не должны.
- Ссылки — точные значения:
  - бот `https://t.me/alania_sky_bot?start=site`
  - игра `https://t.me/tvoya_vechnost_bot`
  - личка `https://t.me/LanaLeonovich`
  - канал `https://t.me/alania_sky`
  - оферта `https://docs.google.com/document/d/1uKkXGBah_qI0jlRUBaD0SyylDStKr2sP/preview`
  - политика `https://docs.google.com/document/d/1_ZJE1ejwbpGsbt3tkF89EyuyiA2WPeVm/preview`
  - согласие `https://docs.google.com/document/d/1CPsoI6U1nC1gN6O8_QanG1fi4-mSHa-w/preview`
- Кириллица в выводе тестов на Windows требует `PYTHONIOENCODING=utf-8`.

## Поправка к спеке

Спека обещает добавить в `vercel.json` кеш-заголовки для `assets/fonts/`.
Проверено: правило `"source": "/assets/(.*)"` там уже есть и покрывает
вложенные пути. **`vercel.json` не трогаем** — задачи на него нет.

## File Structure

| Файл | Ответственность |
|---|---|
| `web/index.html` | вся страница: разметка, `<style>`, без JS |
| `web/assets/fonts/*.woff2` | 8 файлов, Golos Text ×4 сабсета и Prata ×4 |
| `web/assets/lana.webp` / `lana.jpg` | портрет 1600×2000 в двух форматах |
| `web/assets/og.jpg` | 1200×630 для превью ссылки |
| `web/assets/favicon.svg` | монограмма ЛЛ |
| `tests/test_landing.py` | структурные проверки готовой страницы |
| `web/README.md` | как устроена страница и её грабли |
| `web/legal/` | **удаляется** |

## Что в бандле держится на выброшенном рантайме

Инвентарь, снятый с файла, — это исчерпывающий список того, что сломается,
если просто вырезать `<script>`:

| Конструкция | Сколько | Что делает | Куда переезжает |
|---|---|---|---|
| `sc-camel-on-click="{{ tN }}"` | 6 | открыть/закрыть пункт FAQ | `<summary>` |
| `{{ mN }}` | 6 | знак `+` / `–` | CSS-псевдоэлемент |
| `{{ dN }}` | 6 | `display` тела ответа | сам `<details>` |
| `style-hover="…"` | 9 | ховер кнопок | CSS `:hover` |
| `data-nav`, `data-stack`, `data-cols` | по 1 | — | **ничего не делаем**, это обычные CSS-хуки внутри медиазапросов |

Логика аккордеона из бандла: `state.open` стартует с `0`, повторный клик по
открытому пункту закрывает его, открытие другого — закрывает предыдущий.
То есть первый вопрос открыт при загрузке, открыт всегда максимум один.

---

### Task 1: Тесты на готовую страницу

Пишем проверки заранее — они красные до конца работы и служат чек-листом.
Файл добавляется в общий прогон pytest, где уже 96 тестов бота.

**Files:**
- Create: `tests/test_landing.py`

**Interfaces:**
- Consumes: ничего.
- Produces: `PAGE` (`pathlib.Path` до `web/index.html`), `html()` — читает
  страницу как `str`; ими пользуются все последующие задачи при проверке.

- [ ] **Step 1: Написать падающие тесты**

```python
"""Структурные проверки лендинга: страница статическая, без рантайма,
все локальные ссылки существуют, юр-ссылки проставлены."""
import re
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parent.parent / "web"
PAGE = WEB / "index.html"

DOC_OFFER = "1uKkXGBah_qI0jlRUBaD0SyylDStKr2sP"
DOC_PRIVACY = "1_ZJE1ejwbpGsbt3tkF89EyuyiA2WPeVm"
DOC_CONSENT = "1CPsoI6U1nC1gN6O8_QanG1fi4-mSHa-w"


def html() -> str:
    return PAGE.read_text(encoding="utf-8")


def test_page_exists():
    assert PAGE.is_file(), "web/index.html не собран"


def test_no_javascript():
    """React выброшен целиком: ни одного script на странице."""
    assert "<script" not in html().lower()


def test_no_runtime_placeholders():
    page = html()
    assert not re.search(r"\{\{\s*\w+\s*\}\}", page), "остались плейсхолдеры"
    assert "sc-camel-on-click" not in page
    assert "style-hover" not in page


def test_faq_is_native_details():
    page = html()
    assert page.count("<details") == 6, "шесть вопросов FAQ"
    assert page.count('name="faq"') == 6, "эксклюзивный аккордеон"
    # порядок атрибутов у <details> не фиксируем — ищем регуляркой
    opened = re.findall(r"<details\b[^>]*\bopen\b", page)
    assert len(opened) == 1, "раскрыт ровно первый вопрос"


def test_fonts_are_self_hosted():
    page = html()
    assert "fonts.googleapis.com" not in page
    assert "fonts.gstatic.com" not in page
    assert page.count("assets/fonts/") >= 8


def test_no_stray_inter():
    """Inter в бандле остался от вставки текста и на сайте не грузится."""
    assert not re.search(r"font-family:\s*Inter", html())


def test_legal_links_point_to_google_docs():
    page = html()
    assert 'href="#"' not in page, "пустых ссылок быть не должно"
    for doc in (DOC_OFFER, DOC_PRIVACY, DOC_CONSENT):
        assert doc in page, f"нет ссылки на документ {doc}"


def test_channel_link_returned():
    assert "https://t.me/alania_sky" in html()


def test_local_assets_exist():
    """Каждый локальный путь из src/href/url() лежит на диске."""
    page = html()
    refs = set(re.findall(r'(?:src|srcset|href)="((?!https?:|#|mailto:)[^"]+)"', page))
    refs |= set(re.findall(r'url\("((?!https?:|data:)[^"]+)"\)', page))
    missing = sorted(r for r in refs if not (WEB / r).is_file())
    assert not missing, f"нет файлов: {missing}"


@pytest.mark.parametrize("name,limit_kb", [
    ("lana.webp", 200),
    ("lana.jpg", 400),
    ("og.jpg", 200),
])
def test_image_weight_budget(name, limit_kb):
    path = WEB / "assets" / name
    assert path.is_file(), f"{name} не собран"
    kb = path.stat().st_size / 1024
    assert kb < limit_kb, f"{name} весит {kb:.0f} КБ, бюджет {limit_kb} КБ"
```

- [ ] **Step 2: Убедиться, что тесты падают**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q`
Expected: FAIL — `test_page_exists` и почти все остальные красные, потому что
`web/index.html` ещё старый, а `assets/fonts/` не существует.

- [ ] **Step 3: Коммит**

```bash
git add tests/test_landing.py
git commit -m "Тесты лендинга: страница без JS, свои шрифты, живые ссылки"
```

---

### Task 2: Ассеты из бандла — шрифты и фото

**Files:**
- Create: `web/assets/fonts/*.woff2` (8 файлов)
- Create: `web/assets/lana.webp`, `web/assets/lana.jpg`, `web/assets/og.jpg`
- Delete: старые `web/assets/lana.webp`, `web/assets/lana.jpg`, `web/assets/og.jpg` (перезаписываются)
- Create (вне репозитория): `<scratchpad>/extract_assets.py`

**Interfaces:**
- Consumes: ничего.
- Produces: файлы шрифтов с именами вида `golos-cyrillic.woff2`,
  `prata-latin.woff2` — Task 3 подставляет ровно эти имена в `@font-face`,
  выводя их тем же правилом (семейство + сабсет из комментария Google).

- [ ] **Step 1: Написать скрипт извлечения**

Создать `<scratchpad>/extract_assets.py`:

```python
"""Достать из бандла шрифты и фото, разложить в web/assets/."""
import base64
import gzip
import json
import re
import zlib
from pathlib import Path

from PIL import Image

SRC = Path(r"C:/Users/Dell/Downloads/Lana Leonovich - сайт.html")
WEB = Path(r"C:/Git/alania/web")
FONTS = WEB / "assets" / "fonts"
FONTS.mkdir(parents=True, exist_ok=True)

raw = SRC.read_text(encoding="utf-8", errors="replace")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", raw, re.S | re.I)
assets = json.loads(scripts[1].strip())
page = json.loads(scripts[4].strip())


def blob(uuid: str) -> bytes:
    v = assets[uuid]
    data = base64.b64decode(v["data"])
    if not v.get("compressed"):
        return data
    for fn in (gzip.decompress, zlib.decompress, lambda b: zlib.decompress(b, -15)):
        try:
            return fn(data)
        except Exception:
            continue
    raise RuntimeError(f"не распаковал {uuid}")


# ── шрифты: имя выводим из комментария Google и семейства ────────────
SLUG = {"Golos Text": "golos", "Prata": "prata"}
pattern = re.compile(
    r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", re.S)
mapping: dict[str, str] = {}
for subset, body in pattern.findall(page):
    family = re.search(r"font-family:\s*'([^']+)'", body).group(1)
    uuid = re.search(r'url\("([^"]+)"\)', body).group(1)
    mapping[uuid] = f"{SLUG[family]}-{subset}.woff2"

for uuid, name in mapping.items():
    (FONTS / name).write_bytes(blob(uuid))
    print(f"шрифт {name}: {(FONTS / name).stat().st_size / 1024:.0f} КБ")

# ── фото ─────────────────────────────────────────────────────────────
photo_uuid = next(u for u, v in assets.items() if v["mime"] == "image/jpeg")
src_jpg = Path(__file__).parent / "lana-src.jpg"
src_jpg.write_bytes(blob(photo_uuid))

im = Image.open(src_jpg).convert("RGB")
portrait = im.resize((1600, 2000), Image.LANCZOS)
portrait.save(WEB / "assets" / "lana.webp", "WEBP", quality=82, method=6)
portrait.save(WEB / "assets" / "lana.jpg", "JPEG", quality=85,
              optimize=True, progressive=True)

# og: ширина 1200, полоса 630 вокруг фокуса 30% по высоте — как
# object-position:50% 30% у портрета на странице
wide = im.resize((1200, 1500), Image.LANCZOS)
top = int(1500 * 0.30) - 630 // 2
wide.crop((0, top, 1200, top + 630)).save(
    WEB / "assets" / "og.jpg", "JPEG", quality=86, optimize=True)

for name in ("lana.webp", "lana.jpg", "og.jpg"):
    kb = (WEB / "assets" / name).stat().st_size / 1024
    print(f"{name}: {kb:.0f} КБ")
```

- [ ] **Step 2: Запустить скрипт**

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/extract_assets.py`
Expected: восемь строк «шрифт …» и три строки с весами. Ожидаемые порядки:
шрифты 7–37 КБ каждый, `lana.webp` ~110 КБ, `lana.jpg` ~310 КБ, `og.jpg` ~90 КБ.

Если `lana.webp` вылез за 200 КБ или `lana.jpg` за 400 КБ — снизить `quality`
шагом по 3 и перезапустить. Бюджеты заданы в `test_image_weight_budget`.

- [ ] **Step 3: Проверить бюджеты весов**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q -k image_weight`
Expected: PASS — три теста весов зелёные. Остальные ещё красные.

- [ ] **Step 4: Коммит**

```bash
git add web/assets
git commit -m "Ассеты лендинга v5: свои шрифты, новое фото, новый og"
```

---

### Task 3: Собрать index.html из бандла

Механическая часть: структура, стили, пути к шрифтам, фото. После этой задачи
страница уже открывается и выглядит правильно везде, кроме FAQ и ховеров.

**Files:**
- Modify: `web/index.html` (полностью перезаписывается)
- Create (вне репозитория): `<scratchpad>/build_page.py`

**Interfaces:**
- Consumes: имена файлов шрифтов из Task 2 (то же правило именования).
- Produces: `web/index.html` со всей разметкой; Task 4–6 правят его точечно.

- [ ] **Step 1: Написать скрипт сборки**

Создать `<scratchpad>/build_page.py`:

```python
"""Собрать web/index.html из бандла: снять обёртки рантайма, склеить стили,
подставить локальные шрифты и <picture> вместо <img>."""
import json
import re
from pathlib import Path

SRC = Path(r"C:/Users/Dell/Downloads/Lana Leonovich - сайт.html")
OUT = Path(r"C:/Git/alania/web/index.html")

raw = SRC.read_text(encoding="utf-8", errors="replace")
scripts = re.findall(r"<script[^>]*>(.*?)</script>", raw, re.S | re.I)
page = json.loads(scripts[4].strip())

# 1. стили — вынуть все блоки в порядке появления, тело оставить без них
styles = re.findall(r"<style[^>]*>(.*?)</style>", page, re.S)
body = re.sub(r"<style[^>]*>.*?</style>", "", page, flags=re.S)

# 2. снять обёртки рантайма и его скрипты
body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.S)
body = re.sub(r"</?(x-dc|helmet)>", "", body)
inner = re.search(r"<body>(.*)</body>", body, re.S).group(1).strip()
# внутри <helmet> лежал дубликат viewport-меты — в <body> ему не место
inner = re.sub(r'<meta name="viewport"[^>]*>\s*', "", inner)

# 3. пути шрифтов: uuid -> assets/fonts/<семейство>-<сабсет>.woff2
SLUG = {"Golos Text": "golos", "Prata": "prata"}
css = "\n".join(styles)
for subset, block in re.findall(r"/\*\s*([\w-]+)\s*\*/\s*@font-face\s*\{(.*?)\}", css, re.S):
    family = re.search(r"font-family:\s*'([^']+)'", block).group(1)
    uuid = re.search(r'url\("([^"]+)"\)', block).group(1)
    css = css.replace(f'url("{uuid}")', f'url("assets/fonts/{SLUG[family]}-{subset}.woff2")')

# 4. фото -> <picture> с webp и jpg, с явными размерами
photo = re.search(r'<img[^>]*alt="Лана Леонович"[^>]*>', inner).group(0)
inner = inner.replace(photo, (
    '<picture>'
    '<source srcset="assets/lana.webp" type="image/webp">'
    '<img src="assets/lana.jpg" alt="Лана Леонович" width="1600" height="2000" '
    'style="width:100%;height:100%;object-fit:cover;object-position:50% 30%;display:block">'
    '</picture>'
))

OUT.write_text(
    "<!DOCTYPE html>\n"
    '<html lang="ru"><head>\n'
    '<meta charset="utf-8">\n'
    '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
    "<title>Лана Леонович — психолог, коуч, телесный практик</title>\n"
    '<link rel="icon" href="assets/favicon.svg" type="image/svg+xml">\n'
    '<link rel="preload" as="font" type="font/woff2" crossorigin '
    'href="assets/fonts/golos-cyrillic.woff2">\n'
    '<link rel="preload" as="font" type="font/woff2" crossorigin '
    'href="assets/fonts/prata-cyrillic.woff2">\n'
    f"<style>{css}</style>\n"
    "</head>\n<body>\n"
    f"{inner}\n"
    "</body></html>\n",
    encoding="utf-8",
)
print(f"index.html: {OUT.stat().st_size / 1024:.0f} КБ")
```

- [ ] **Step 2: Запустить и проверить**

Run: `PYTHONIOENCODING=utf-8 python <scratchpad>/build_page.py`
Expected: `index.html: ~70 КБ`.

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q`
Expected: зелёные `test_page_exists`, `test_no_javascript`,
`test_fonts_are_self_hosted`, тесты весов. Красные — `test_local_assets_exist`
(нет `favicon.svg`), `test_no_runtime_placeholders`, `test_faq_is_native_details`,
`test_no_stray_inter`, `test_legal_links_point_to_google_docs`,
`test_channel_link_returned`.

- [ ] **Step 3: Коммит**

```bash
git add web/index.html
git commit -m "Лендинг v5: разметка и стили из бандла, свои шрифты, picture"
```

---

### Task 4: FAQ на нативном `<details>`

**Files:**
- Modify: `web/index.html` — шесть карточек FAQ и один новый блок CSS

**Interfaces:**
- Consumes: `web/index.html` из Task 3.
- Produces: разметку без `{{ tN }}`, `{{ mN }}`, `{{ dN }}`.

- [ ] **Step 1: Заменить каждую из шести карточек**

Было (на примере первой; отличаются только номер и текст):

```html
<div style="background:#fff;border-radius:14px;overflow:hidden">
  <div sc-camel-on-click="{{ t0 }}" style="display:flex;gap:20px;align-items:baseline;justify-content:space-between;padding:24px 28px;cursor:pointer;font-size:1.02rem;color:#1C1C2E">
    <span>Сомневаюсь, подойдёт ли мне ваш метод</span><span style="color:#C8705A;font-size:1.3rem;line-height:1">{{ m0 }}</span>
  </div>
  <div style="padding:0 28px 24px;font-size:0.97rem;line-height:1.7;color:#6B6560;display:{{ d0 }}">…ответ…</div>
</div>
```

Стало — `open` ставится **только у первой** карточки, `name="faq"` у всех
шести (так браузер сам закрывает соседние, как делал рантайм):

```html
<details class="faq-item" name="faq" open>
  <summary>Сомневаюсь, подойдёт ли мне ваш метод</summary>
  <div style="padding:0 28px 24px;font-size:0.97rem;line-height:1.7;color:#6B6560">…ответ…</div>
</details>
```

`…ответ…` здесь — заглушка для чтения плана: в файле на этом месте лежит
готовый текст ответа, местами в несколько абзацев со `<span>`, `<ul>` и
`<blockquote>`. Он **переносится посимвольно, без единой правки**. Меняется
ровно две вещи: `<div sc-camel-on-click=…>` превращается в `<summary>`
(с текстом вопроса и без второго `<span>` со знаком), а из `style` у
контейнера ответа вырезается `;display:{{ dN }}` — остальные свойства
в этом же `style` остаются.

- [ ] **Step 2: Добавить стили аккордеона**

В конец блока `<style>` дописать. Здесь же живёт знак `+`/`–`, который
раньше приходил через `{{ mN }}`:

```css
.faq-item{background:#fff;border-radius:14px;overflow:hidden}
.faq-item+.faq-item{margin-top:12px}
.faq-item summary{display:flex;gap:20px;align-items:baseline;
  justify-content:space-between;padding:24px 28px;cursor:pointer;
  font-size:1.02rem;color:#1C1C2E;list-style:none}
.faq-item summary::-webkit-details-marker{display:none}
.faq-item summary::after{content:"+";color:#C8705A;font-size:1.3rem;
  line-height:1;flex:none}
.faq-item[open] summary::after{content:"–"}
```

Родительский `<div style="display:flex;flex-direction:column;gap:12px">`,
в котором лежали карточки, остаётся — `margin-top` в `.faq-item+.faq-item`
подстраховывает на случай, если у браузера нет поддержки `gap` во flex.

- [ ] **Step 3: Проверить**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q -k "placeholders or details"`
Expected: PASS — `test_no_runtime_placeholders` и `test_faq_is_native_details`
зелёные.

- [ ] **Step 4: Коммит**

```bash
git add web/index.html
git commit -m "FAQ на нативном details: рантайм дизайн-системы больше не нужен"
```

---

### Task 5: Ховеры кнопок в CSS

`style-hover` понимал только выброшенный рантайм. Девять элементов: восемь
светлых кнопок и одна тёмная в футере.

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Заменить атрибуты на классы**

Восемь элементов с `style-hover="background:#C8705A;color:#fff"` — убрать
атрибут, добавить `class="btn-accent"`. Единственный элемент с
`style-hover="background:#fff;color:#2B3366"` (кнопка «Записаться на сессию»
в футере) — убрать атрибут, добавить `class="btn-invert"`.

Найти все девять:

```bash
grep -o 'style-hover="[^"]*"' web/index.html | sort | uniq -c
```

- [ ] **Step 2: Дописать правила в конец `<style>`**

```css
.btn-accent:hover{background:#C8705A;color:#fff}
.btn-invert:hover{background:#fff;color:#2B3366}
```

- [ ] **Step 3: Проверить**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q -k placeholders`
Expected: PASS — `style-hover` в странице больше нет.

- [ ] **Step 4: Коммит**

```bash
git add web/index.html
git commit -m "Ховеры кнопок перенесены из style-hover в CSS"
```

---

### Task 6: Вычистить Inter из инлайновых стилей

28 инлайновых `font-family: Inter, …` — следы вставки текста из редактора.
Inter на странице не грузится: свои шрифты только Golos Text и Prata. Сейчас
эти абзацы отрисуются Inter'ом у того, у кого он стоит в системе, и системным
гротеском у всех остальных — то есть страница выглядит по-разному на разных
машинах. Убираем объявление, текст наследует Golos Text.

**Files:**
- Modify: `web/index.html`

- [ ] **Step 1: Посмотреть, что именно вырезается**

```bash
grep -o 'font-family: Inter[^;"]*[;"]' web/index.html | sort | uniq -c
```

- [ ] **Step 2: Вырезать объявление**

Убрать подстроку `font-family: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;`
(и её варианты с `&quot;` вместо кавычек) из всех инлайновых `style`.
Остальные свойства в тех же `style` — размеры, цвета, отступы — **не трогать**.

Точечная замена регуляркой по файлу:

```python
import re
from pathlib import Path

p = Path(r"C:/Git/alania/web/index.html")
s = p.read_text(encoding="utf-8")
s2 = re.sub(r"font-family:\s*Inter[^;\"]*;\s*", "", s)
p.write_text(s2, encoding="utf-8")
print("вырезано:", len(re.findall(r"font-family:\s*Inter", s)) - len(re.findall(r"font-family:\s*Inter", s2)))
```

Ожидается `вырезано: 28`.

- [ ] **Step 3: Проверить**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q -k inter`
Expected: PASS.

- [ ] **Step 4: Коммит**

```bash
git add web/index.html
git commit -m "Убран Inter из инлайновых стилей: текст наследует Golos Text"
```

---

### Task 7: Ссылки и favicon

**Files:**
- Modify: `web/index.html` — юр-блок и строка контактов в футере
- Create: `web/assets/favicon.svg`

- [ ] **Step 1: Проставить юр-ссылки**

Три `href="#"` в футере. Было:

```html
<a href="#" style="color:rgba(255,255,255,0.8)">Публичная оферта</a>
<span style="color:rgba(255,255,255,0.3)">·</span>
<a href="#" style="color:rgba(255,255,255,0.8)">Политика конфиденциальности</a>
<span style="color:rgba(255,255,255,0.3)">·</span>
<a href="#" style="color:rgba(255,255,255,0.8)">Информированное согласие</a>
```

Стало:

```html
<a href="https://docs.google.com/document/d/1uKkXGBah_qI0jlRUBaD0SyylDStKr2sP/preview" target="_blank" rel="noopener" style="color:rgba(255,255,255,0.8)">Публичная оферта</a>
<span style="color:rgba(255,255,255,0.3)">·</span>
<a href="https://docs.google.com/document/d/1_ZJE1ejwbpGsbt3tkF89EyuyiA2WPeVm/preview" target="_blank" rel="noopener" style="color:rgba(255,255,255,0.8)">Политика конфиденциальности</a>
<span style="color:rgba(255,255,255,0.3)">·</span>
<a href="https://docs.google.com/document/d/1CPsoI6U1nC1gN6O8_QanG1fi4-mSHa-w/preview" target="_blank" rel="noopener" style="color:rgba(255,255,255,0.8)">Информированное согласие</a>
```

- [ ] **Step 2: Вернуть ссылку на бесплатный канал**

В строке контактов футера сейчас две ссылки, и `@alania.sky` ведёт **в бота**,
а не в канал. Добавляем канал третьей, ничего не переставляя:

```html
<a href="https://t.me/alania_sky" target="_blank" rel="noopener" style="color:#E0A48F">Бесплатный Telegram-канал</a>
```

Вставить сразу после ссылки `@alania.sky`, внутри того же
`<div style="display:flex;flex-wrap:wrap;gap:20px;font-size:0.9rem">`.

- [ ] **Step 3: Создать favicon**

`web/assets/favicon.svg` — монограмма терракотой на фоне страницы:

```svg
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64">
  <rect width="64" height="64" rx="14" fill="#FAFAF7"/>
  <text x="32" y="43" text-anchor="middle" font-family="Georgia, 'Times New Roman', serif"
        font-size="30" fill="#C8705A">ЛЛ</text>
</svg>
```

- [ ] **Step 4: Прогнать весь файл тестов**

Run: `PYTHONIOENCODING=utf-8 python -m pytest tests/test_landing.py -q`
Expected: PASS — все тесты зелёные, включая `test_local_assets_exist`,
`test_legal_links_point_to_google_docs` и `test_channel_link_returned`.

- [ ] **Step 5: Коммит**

```bash
git add web/index.html web/assets/favicon.svg
git commit -m "Юр-ссылки на Google Docs, канал в футере, favicon"
```

---

### Task 8: Удалить web/legal/ и переписать README

**Files:**
- Delete: `web/legal/oferta.html`, `privacy.html`, `consent.html`, `crypto.html`, `legal.css`
- Modify: `web/README.md`

- [ ] **Step 1: Убедиться, что на страницы никто не ссылается**

```bash
grep -rn "legal/" web/index.html handlers/ keyboards/ || echo "ссылок нет"
```

Expected: `ссылок нет`. Если что-то нашлось — остановиться и разобраться,
а не удалять.

- [ ] **Step 2: Удалить**

```bash
git rm -r web/legal
```

- [ ] **Step 3: Переписать README**

`web/README.md` описывает прежнюю страницу целиком — палитру, Inter,
кадрирование старого фото, юридические страницы, расхождение с ботом.
Переписать под новую, сохранив разделы «Локальный просмотр» и «Деплой
на Vercel» как есть и обязательно перенеся эти грабли:

- фото: `width`/`height` у `<img>` обязаны идти вместе с `height: auto`
  в CSS, иначе презентационная подсказка перебивает `aspect-ratio`;
- `og.jpg` — отдельный кадр 1200×630, в самой странице не используется;
- на странице нет и не должно появляться JS: аккордеон держится на
  `<details name="faq">`, ховеры — на классах `.btn-accent` / `.btn-invert`;
- юр-тексты живут только в Google Docs, копий в репозитории больше нет;
- `?start=site` бот пока не разбирает — человек попадёт на главный экран.

- [ ] **Step 4: Полный прогон тестов**

Run: `PYTHONIOENCODING=utf-8 python -m pytest -q`
Expected: PASS — 96 тестов бота плюс тесты лендинга.

- [ ] **Step 5: Коммит**

```bash
git add -A web
git commit -m "Удалены web/legal: юр-тексты живут в Google Docs. README под v5"
```

---

### Task 9: Проверка в браузере

Тесты проверяют структуру, но не то, как страница выглядит. Этот шаг —
единственный, где смотрим глазами.

**Files:**
- Modify: `web/index.html` — только если проверка найдёт дефекты

- [ ] **Step 1: Поднять сервер**

Через `preview_start` с конфигурацией из `.claude/launch.json`; если её нет —
создать запись:

```json
{
  "name": "landing",
  "runtimeExecutable": "python",
  "runtimeArgs": ["-m", "http.server", "4321", "--directory", "web"],
  "port": 4321
}
```

- [ ] **Step 2: Проверить консоль и сеть**

`read_console_messages` — ошибок нет.
`read_network_requests` — ни одного 404, шрифты отдаются, фото одно.

- [ ] **Step 3: Проверить содержимое**

`read_page` — убедиться, что `{{` нигде не отображается, все шесть вопросов
FAQ на месте, футер содержит четыре ссылки (три юр. + канал).

Проверить якорную навигацию: в шапке шесть пунктов (`#top`, `#requests`,
`#method`, `#services`, `#reviews`, `#faq`) — кликнуть каждый и убедиться,
что страница уезжает в свою секцию, а не остаётся на месте.

- [ ] **Step 4: Проверить аккордеон**

Кликнуть по второму вопросу: он раскрывается, первый закрывается.
Кликнуть по нему же ещё раз: закрывается.

- [ ] **Step 5: Проверить обе ширины**

`resize_window` пресетом `mobile`, перезагрузить, снять скриншот;
затем `desktop`, снять скриншот. На обеих ширинах страница не скроллится
вбок, портрет не растянут.

- [ ] **Step 6: Коммит, если что-то правилось**

```bash
git add web/index.html
git commit -m "Правки после проверки страницы в браузере"
```

---

## Definition of done

- `PYTHONIOENCODING=utf-8 python -m pytest -q` — всё зелёное.
- В `web/index.html` нет `<script>`, `{{`, `sc-camel-on-click`, `style-hover`,
  `font-family: Inter`, `href="#"`.
- Страница открывается локально без ошибок в консоли и без 404.
- `web/legal/` удалён, `web/README.md` описывает новую страницу.
- Ветка `feature/web-redesign-v5` готова к PR.
