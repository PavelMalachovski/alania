"""Структурные проверки лендинга: страница статическая, без рантайма,
все локальные ссылки существуют, юр-ссылки проставлены."""
import json
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


def test_no_framework_only_tiny_inline_script():
    """React выброшен целиком, внешних скриптов нет. Единственный
    оставшийся — инлайновая обвязка стрелок ленты отзывов: на десктопе
    свайпа нет, а полосу прокрутки у ленты мы прячем, поэтому без стрелок
    она не листается ничем, кроме Shift+колесо. Тест сторожит, чтобы
    скрипт не разросся и чтобы фреймворк не вернулся."""
    page = html()
    assert "<script src" not in page, "внешних скриптов быть не должно"
    # application/ld+json — разметка для поиска, браузер её не исполняет;
    # считаем только настоящие скрипты.
    attrs = re.findall(r"<script\b([^>]*)>", page)
    executable = [a for a in attrs if 'type="application/ld+json"' not in a]
    assert len(executable) == 1, "ровно один инлайновый скрипт"
    assert "react" not in page.lower()
    body = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
    assert len(body) < 1400, f"скрипт разросся до {len(body)} символов"


def test_reviews_have_arrow_controls():
    """Стрелки — единственный способ пролистать ленту мышью."""
    page = html()
    assert 'class="reviews-arrow reviews-arrow--prev"' in page
    assert 'class="reviews-arrow reviews-arrow--next"' in page
    assert 'aria-label="Предыдущие отзывы"' in page
    assert 'aria-label="Следующие отзывы"' in page
    # показываются только мыши: на тачскрине листают пальцем
    assert "@media (hover:hover) and (pointer:fine){.reviews-arrow{display:flex}}" in page


def test_result_section_columns_do_not_stretch():
    """Четыре карточки «Результата» лежат своей сеткой 2x2 слева, блок
    про 66 дней — отдельной колонкой справа. Раньше все пятеро были в
    одной сетке, и высокий блок задирал высоту ряда: под верхними
    карточками зияли дыры в пол-экрана."""
    page = html()
    assert "grid-template-columns:minmax(0,1.55fr) minmax(0,1fr)" in page
    assert "grid-template-columns:repeat(2,minmax(0,1fr))" in page
    assert "align-items:start" in page


def test_no_runtime_placeholders():
    page = html()
    assert not re.search(r"\{\{\s*\w+\s*\}\}", page), "остались плейсхолдеры"
    assert "sc-camel-on-click" not in page
    assert "style-hover" not in page


def test_faq_is_native_details():
    page = html()
    assert page.count("<details") == 8, "восемь вопросов FAQ"
    assert page.count('name="faq"') == 8, "эксклюзивный аккордеон"
    # В бандле первый вопрос был раскрыт (state.open стартовал с нуля).
    # По решению владельца FAQ открывается свёрнутым: раскрытый ответ
    # оттягивал на себя внимание и удлинял секцию на первый взгляд.
    # Порядок атрибутов у <details> не фиксируем — ищем регуляркой.
    opened = re.findall(r"<details\b[^>]*\bopen\b", page)
    assert not opened, "все вопросы свёрнуты по умолчанию"


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


def test_handle_label_points_to_instagram():
    """@alania.sky в футере — инстаграм. В бандле эта ссылка вела в бота
    и дублировала кнопку записи; телеграм-канал живёт отдельной ссылкой
    рядом (см. test_channel_link_returned)."""
    m = re.search(r'<a href="([^"]+)"[^>]*>@alania\.sky</a>', html())
    assert m, "не нашёл ссылку с подписью @alania.sky"
    assert m.group(1).startswith("https://www.instagram.com/alania.sky"), \
        f"ведёт в {m.group(1)}"


def test_channel_link_returned():
    """Проверка идёт по href целиком: голая подстрока https://t.me/alania_sky
    является префиксом ссылки на бота alania_sky_bot и зеленела бы ложно."""
    assert 'href="https://t.me/alania_sky"' in html()


def test_no_pasted_background_artifacts():
    """Инлайновые background-color — следы вставки текста из редактора:
    цвета СТАРОЙ палитры (#F4F3EF фарфоровый, #EAE8E2 жемчужный), которых
    на этой странице больше нет. Рисуются серыми подложками под текстом.
    Настоящие фоны в дизайне записаны как background:#… — их не трогаем."""
    assert "background-color: rgb(" not in html()


def test_list_markers_are_consistent():
    """53 из 60 пунктов несут маркер-тире в терракоте, а регалии в герое —
    сырую звёздочку, оставшуюся от markdown при вставке.

    \\b после li обязателен: без него [^>]* спокойно проглатывает "nk ..." из
    <link> в head, нежадный DOTALL склеивает такой "<li>" со всем до первого
    настоящего </li> в один гигантский матч, который не начинается с "*" —
    и тест перестаёт видеть первый пункт регалий. Проверено на дореформенном
    web/index.html (git show 568925d): старый вариант регулярки ловил 2
    звёздочки из 3, с \\b — все три (см. task-10-cleanup-report.md)."""
    lis = re.findall(r"<li\b[^>]*>(.*?)</li>", html(), re.S)
    starred = [re.sub(r"<[^>]+>", "", x).strip()[:40]
               for x in lis if re.sub(r"<[^>]+>", "", x).strip().startswith("*")]
    assert not starred, f"пункты со звёздочкой: {starred}"


def test_head_carries_seo_and_preview():
    """Ссылку на сайт шлют в Telegram — без og-блока она не развернётся
    в превью, а og.jpg собирается и весит, но никем не используется."""
    page = html()
    for needle in ('name="description"', 'rel="canonical"',
                   'property="og:title"', 'property="og:image"',
                   'name="twitter:card"', "assets/og.jpg"):
        assert needle in page, f"в head нет {needle}"


def test_search_finds_latin_name():
    """По запросу «lanaleonovich» Google сайт не находил: имя было только
    кириллицей, а о самом сайте поисковику ничего не сообщали. Латиница —
    в title, в видимом подвале и в JSON-LD; robots.txt указывает на
    sitemap.xml. Все адреса — абсолютные и совпадают с canonical."""
    page = html()
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page).group(1)
    title = re.search(r"<title>(.*?)</title>", page).group(1)
    assert "Lana Leonovich" in title
    assert "© 2026 Лана Леонович (Lana Leonovich)" in page, "латиница в видимом тексте"

    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', page, re.S)
    assert len(blocks) == 1
    graph = {n["@type"]: n for n in json.loads(blocks[0])["@graph"]}
    person = graph["Person"]
    assert {"Lana Leonovich", "lanaleonovich"} <= set(person["alternateName"])
    assert person["url"] == graph["WebSite"]["url"] == canonical
    assert "https://www.instagram.com/alania.sky" in person["sameAs"]

    robots = (WEB / "robots.txt").read_text(encoding="utf-8")
    assert f"Sitemap: {canonical}sitemap.xml" in robots
    assert "Disallow: /\n" not in robots
    assert f"<loc>{canonical}</loc>" in (WEB / "sitemap.xml").read_text(encoding="utf-8")


def test_own_domain_is_the_only_address():
    """Сайт живёт на lanaleonovich.com. Старый alania.vercel.app — только
    постоянный редирект на него: два адреса с одной страницей Google
    считает дублями и сам выбирает, какой показывать."""
    page = html()
    canonical = re.search(r'<link rel="canonical" href="([^"]+)"', page).group(1)
    assert canonical == "https://lanaleonovich.com/"
    for name in ("index.html", "robots.txt", "sitemap.xml"):
        assert "alania.vercel.app" not in (WEB / name).read_text(encoding="utf-8"), name
    redirects = json.loads((WEB / "vercel.json").read_text(encoding="utf-8"))["redirects"]
    old = [r for r in redirects if {"type": "host", "value": "alania.vercel.app"} in r["has"]]
    assert len(old) == 1 and old[0]["permanent"] is True
    assert old[0]["source"] == "/:path*"
    assert old[0]["destination"] == canonical + ":path*"


def test_exactly_one_h1_and_it_has_text():
    """В бандле два ПУСТЫХ h1, а имя лежало в h2 — страница уехала бы
    в прод без единого заголовка первого уровня."""
    h1s = re.findall(r"<h1\b[^>]*>(.*?)</h1>", html(), re.S)
    assert len(h1s) == 1, f"ожидается один h1, найдено {len(h1s)}"
    assert re.sub(r"<[^>]+>", "", h1s[0]).strip(), "h1 пустой"


def test_reviews_are_a_swipe_track():
    """Отзывы листаются вбок нативным scroll-snap, без JS."""
    page = html()
    assert page.count('class="review-card"') == 7, "семь карточек в ленте"
    assert "scroll-snap-type:x mandatory" in page
    assert "scroll-snap-align:start" in page
    assert "columns:2" not in page, "мульти-колонка заменена лентой"
    assert "break-inside" not in page, "вне мульти-колонки свойство мертво"


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


def _jpeg_size(data: bytes) -> tuple[int, int]:
    """(ширина, высота) из SOF-маркера — без Pillow в зависимостях."""
    i = 2
    while i < len(data):
        marker = data[i + 1]
        if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
            return (int.from_bytes(data[i + 7:i + 9], "big"),
                    int.from_bytes(data[i + 5:i + 7], "big"))
        i += 2 + int.from_bytes(data[i + 2:i + 4], "big")
    raise ValueError("SOF не найден")


def test_portrait_attributes_match_file():
    """width/height у <img> портрета — реальный размер кадра. Фото меняют
    целиком, и старые атрибуты легко забыть: браузер резервирует место
    по ним, и при другой пропорции картинка прыгает при загрузке."""
    m = re.search(r'<img src="assets/lana\.jpg"[^>]*width="(\d+)" height="(\d+)"', html())
    assert m, "не нашёл <img> портрета"
    actual = _jpeg_size((WEB / "assets" / "lana.jpg").read_bytes())
    assert (int(m.group(1)), int(m.group(2))) == actual


def test_course_card_leads_to_bot():
    """Оплата курса — в боте (экран «Курс-практикум», кнопки Tribute там),
    на сайте только кнопка в бота с deep link на этот экран."""
    page = html()
    assert "Курс-практикум «ВЗЛОМАЙ РЕАЛЬНОСТЬ»" in page
    assert "tribute.tg" not in page, "оплата курса переехала в бота"
    assert re.search(r'href="https://t\.me/alania_sky_bot\?start=course"[^>]*>Перейти в Telegram-бот<', page)
    # курс стоит после VECHNOST внутри #services
    assert page.index("Игра для пар «VECHNOST»") < page.index("ВЗЛОМАЙ РЕАЛЬНОСТЬ") \
        < page.index("Как записаться на сессию")
