import json
import os
from datetime import datetime

from nhk_easy.flows.daily_fetch import (
    article_url,
    entry_to_article,
    extract_video_m3u8,
    filter_recent,
)

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures")


def load_entries() -> list[dict]:
    with open(os.path.join(FIXTURE_DIR, "news_list.json"), encoding="utf-8") as f:
        data = json.load(f)
    entries = []
    for day_map in data:
        for day_entries in day_map.values():
            entries.extend(day_entries)
    return entries


def test_article_url():
    assert (
        article_url("ne2026061113593")
        == "https://news.web.nhk/news/easy/ne2026061113593/ne2026061113593.html"
    )


def test_extract_video_m3u8():
    uri = (
        "https://news.web.nhk/n-data/conf/player/index.html"
        "?mrurl=https://media.vd.st.nhk/news/k10015146971/index.m3u8&mrposter=/x.jpg"
    )
    assert (
        extract_video_m3u8(uri)
        == "https://media.vd.st.nhk/news/k10015146971/index.m3u8"
    )
    assert extract_video_m3u8(None) is None
    assert extract_video_m3u8("") is None


def test_filter_recent():
    entries = [
        {"news_id": "a", "news_prearranged_time": "2026-06-11 20:00:00"},
        {"news_id": "b", "news_prearranged_time": "2026-06-01 20:00:00"},
        {"news_id": "c"},  # no timestamp: dropped when filtering
    ]
    now = datetime(2026, 6, 12, 9, 0)
    assert [e["news_id"] for e in filter_recent(entries, 1, now)] == ["a"]
    assert [e["news_id"] for e in filter_recent(entries, 30, now)] == ["a", "b"]
    assert filter_recent(entries, None, now) == entries


def test_entry_to_article_from_fixture():
    entries = load_entries()
    assert len(entries) > 0
    entry = next(e for e in entries if e["news_id"] == "ne2026061118568")
    article = entry_to_article(entry)
    assert article.news_id == "ne2026061118568"
    assert article.title.startswith("神奈川県")
    assert "<ruby>" in article.title_with_ruby
    assert article.published_at is not None
    assert article.audio_voice_id.endswith(".m4a")
    assert article.video_m3u8 is None or article.video_m3u8.endswith(".m3u8")
