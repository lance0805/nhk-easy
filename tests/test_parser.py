import os
from datetime import datetime

import pytest

from nhk_easy.parser import parse_article, parse_article_date

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="module")
def article_html() -> str:
    path = os.path.join(FIXTURE_DIR, "article_ne2026061113593.html")
    with open(path, encoding="utf-8") as f:
        return f.read()


def test_parse_article_title(article_html):
    parsed = parse_article(article_html)
    assert parsed.title == "京都の天橋立　熊が出た"
    assert "<ruby>京都<rt>きょうと</rt></ruby>" in parsed.title_html


def test_parse_article_date(article_html):
    parsed = parse_article(article_html)
    assert parsed.published_at == datetime(2026, 6, 11, 20, 3)


def test_parse_article_body_keeps_ruby(article_html):
    parsed = parse_article(article_html)
    assert "<ruby>" in parsed.body_html
    assert "<rt>" in parsed.body_html


def test_parse_article_body_text_strips_furigana(article_html):
    parsed = parse_article(article_html)
    assert "旅行" in parsed.body_text
    # furigana readings must not leak into the plain text
    assert "りょこう" not in parsed.body_text
    assert "<" not in parsed.body_text


def test_parse_article_date_helper():
    assert parse_article_date("2026年6月11日 20時03分") == datetime(2026, 6, 11, 20, 3)
    assert parse_article_date("no date here") is None


def test_parse_article_raises_on_shell_page():
    with pytest.raises(ValueError):
        parse_article("<html><body><div id='root'></div></body></html>")
