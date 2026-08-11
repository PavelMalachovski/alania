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
