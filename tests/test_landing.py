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
