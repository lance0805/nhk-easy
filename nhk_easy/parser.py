"""Parse rendered NHK News Web Easy article pages.

The article page is a client-side rendered SPA; this module expects the HTML
of the page AFTER JavaScript rendering (as returned by crawl4ai). Structure:

    <h1 class="article-title">...<ruby>KANJI<rt>KANA</rt></ruby>...</h1>
    <p class="article-date" id="js-article-date">2026年6月11日 20時03分</p>
    <div class="article-body"><p><span class="color4"><ruby>...</ruby></span>...</p></div>
"""

import re
from dataclasses import dataclass
from datetime import datetime

from lxml import html as lxml_html


@dataclass
class ParsedArticle:
    title: str
    title_html: str
    published_at: datetime | None
    body_html: str
    body_text: str


_DATE_RE = re.compile(r"(\d{4})年(\d{1,2})月(\d{1,2})日\s*(\d{1,2})時(\d{1,2})分")


def _plain_text(element) -> str:
    """Text content with furigana (<rt>) and other annotations removed."""
    clone = lxml_html.fromstring(lxml_html.tostring(element))
    for rt in clone.findall(".//rt"):
        rt.getparent().remove(rt)
    for rp in clone.findall(".//rp"):
        rp.getparent().remove(rp)
    return clone.text_content().strip()


def parse_article_date(text: str) -> datetime | None:
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    year, month, day, hour, minute = (int(g) for g in m.groups())
    return datetime(year, month, day, hour, minute)


def parse_article(page_html: str) -> ParsedArticle:
    doc = lxml_html.fromstring(page_html)

    title_el = doc.cssselect("h1.article-title")
    if not title_el:
        raise ValueError("article title not found; page may not be fully rendered")
    title_el = title_el[0]
    title_html = (title_el.text or "") + "".join(
        lxml_html.tostring(child, encoding="unicode") for child in title_el
    )

    date_el = doc.cssselect("p.article-date")
    published_at = parse_article_date(date_el[0].text_content()) if date_el else None

    body_el = doc.cssselect("div.article-body")
    if not body_el:
        raise ValueError("article body not found; page may not be fully rendered")
    body_el = body_el[0]
    body_html = "".join(
        lxml_html.tostring(child, encoding="unicode") for child in body_el
    )

    return ParsedArticle(
        title=_plain_text(title_el),
        title_html=title_html.strip(),
        published_at=published_at,
        body_html=body_html.strip(),
        body_text=_plain_text(body_el),
    )
