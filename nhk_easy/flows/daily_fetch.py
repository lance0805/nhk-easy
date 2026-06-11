"""Daily NHK News Web Easy fetch flow.

Run locally:  uv run python -m nhk_easy.flows.daily_fetch
Deploy:       uv run python multi-deploy.py   (builds image + registers deployment)
"""

import asyncio
import os
import re
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from crawl4ai import AsyncWebCrawler
from prefect import flow, get_run_logger, task
from prefect.cache_policies import NO_CACHE

from nhk_easy.audio import download_audio
from nhk_easy.browser import (
    EASY_TOP_URL,
    build_browser_config,
    fetch_article_html,
    fetch_media_token,
    fetch_news_list,
    open_easy_top,
)
from nhk_easy.db import create_engine, existing_news_ids, init_db, upsert_article
from nhk_easy.models import Article
from nhk_easy.parser import parse_article
from nhk_easy.prefect_settings import DEFAULT_SETTINGS_BLOCK, resolve_settings
from nhk_easy.settings import Settings

_NEWS_ID_RE = re.compile(r"^ne\d+")


def article_url(news_id: str) -> str:
    return f"{EASY_TOP_URL}{news_id}/{news_id}.html"


def extract_video_m3u8(movie_uri: str | None) -> str | None:
    """news_web_movie_uri is a player URL carrying the stream in ?mrurl=."""
    if not movie_uri:
        return None
    query = parse_qs(urlparse(movie_uri).query)
    return query.get("mrurl", [None])[0]


def entry_to_article(entry: dict) -> Article:
    published_at = None
    raw_time = entry.get("news_prearranged_time") or entry.get(
        "news_publication_time"
    )
    if raw_time:
        published_at = datetime.strptime(raw_time, "%Y-%m-%d %H:%M:%S")
    voice_uri = (
        entry.get("news_easy_voice_uri")
        if entry.get("has_news_easy_voice")
        else None
    )
    return Article(
        news_id=entry["news_id"],
        title=entry.get("title", ""),
        title_with_ruby=entry.get("title_with_ruby"),
        published_at=published_at,
        url=article_url(entry["news_id"]),
        image_url=entry.get("news_web_image_uri")
        or entry.get("news_easy_image_uri")
        or None,
        video_m3u8=extract_video_m3u8(entry.get("news_web_movie_uri")),
        audio_voice_id=voice_uri,
    )


# crawler/engine arguments hold locks and cannot be cache-keyed
@task(retries=2, retry_delay_seconds=30, cache_policy=NO_CACHE)
async def process_article(
    crawler: AsyncWebCrawler, settings: Settings, engine, entry: dict
) -> str:
    logger = get_run_logger()
    article = entry_to_article(entry)
    logger.info(f"Processing {article.news_id}: {article.title}")

    page_html = await fetch_article_html(crawler, article.url)
    parsed = parse_article(page_html)
    article.body_html = parsed.body_html
    article.body_text = parsed.body_text
    if parsed.published_at:
        article.published_at = parsed.published_at

    if article.audio_voice_id:
        # Tokens expire after ~10 minutes; fetch a fresh one per article.
        token = await fetch_media_token(crawler)
        dest = os.path.join(settings.audio_dir, f"{article.news_id}.m4a")
        article.audio_path = await download_audio(
            settings, article.audio_voice_id, token, dest
        )
    else:
        logger.warning(f"{article.news_id} has no narration audio")

    await upsert_article(engine, article)
    return article.news_id


@flow(name="nhk-easy-daily-fetch")
async def daily_fetch(
    limit: int | None = None,
    settings_block_name: str = DEFAULT_SETTINGS_BLOCK,
) -> list[str]:
    """Fetch all new articles (text + audio) into PostgreSQL.

    Args:
        limit: Process at most this many new articles (small-scale validation).
        settings_block_name: Prefect Secret block holding the JSON config
            (MiraiGuard pattern). Pass "" to use .env/env vars instead.
    """
    logger = get_run_logger()
    settings = await resolve_settings(settings_block_name)
    logger.info(
        f"Settings: postgres={settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}"
        f"/{settings.POSTGRES_DATABASE}, proxy={settings.HTTP_PROXY_URL or 'off'}"
    )
    engine = create_engine(settings)
    await init_db(engine)

    saved: list[str] = []
    async with AsyncWebCrawler(config=build_browser_config(settings)) as crawler:
        await open_easy_top(crawler)
        entries = await fetch_news_list(crawler)
        entries = [e for e in entries if _NEWS_ID_RE.match(e.get("news_id", ""))]
        logger.info(f"Site lists {len(entries)} articles")

        known = await existing_news_ids(engine)
        new_entries = [e for e in entries if e["news_id"] not in known]
        new_entries.sort(key=lambda e: e.get("news_prearranged_time") or "")
        if limit is not None:
            new_entries = new_entries[:limit]
        logger.info(f"{len(new_entries)} new articles to process")

        for entry in new_entries:
            saved.append(await process_article(crawler, settings, engine, entry))

    logger.info(f"Done: {len(saved)} articles saved")
    return saved


if __name__ == "__main__":
    asyncio.run(daily_fetch())
