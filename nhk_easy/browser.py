"""Browser access to NHK News Web Easy via crawl4ai.

Uses a persistent Chromium profile so the NHK ONE consent gate (which sets
anonymous-auth cookies through /tix/build_authorize) only has to be passed
once. All JSON endpoints that need the page session (news-list.json,
mediatoken) are fetched inside the page context.
"""

import json
from typing import Any

from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig
from crawl4ai.async_configs import ProxyConfig
from loguru import logger

from nhk_easy.settings import Settings

EASY_TOP_URL = "https://news.web.nhk/news/easy/"
NEWS_LIST_URL = "https://news.web.nhk/news/easy/news-list.json"
MEDIA_TOKEN_URL = "https://mediatoken.web.nhk/v1/token"

SESSION_ID = "nhk-easy"

CONSENT_GATE_MARKER = "ご利用にあたって"

# NOTE: crawl4ai wraps each js_code snippet as the BODY of an async function
# (`return await (async () => { <script> })()`), so snippets must be written
# as top-level statements with await/return. An IIFE expression would run
# detached (its promise neither awaited nor returned) and its value would be
# discarded.

# Tick the confirmation checkbox and click through the consent gate. The gate
# may show a second step (usage type / region); defaults are fine, so clicking
# the same start button again completes it. The final click navigates through
# /tix/build_authorize, which destroys the JS context - crawl4ai reports
# "Navigation triggered" and the caller verifies the gate via a reload.
_CONSENT_JS = """
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
for (let attempt = 0; attempt < 3; attempt++) {
  const checkbox = document.querySelector('input[type=checkbox]');
  if (!checkbox) return 'no-gate';
  if (!checkbox.checked) checkbox.click();
  await sleep(500);
  const button = [...document.querySelectorAll('button')]
    .find((b) => b.textContent.includes('サービスの利用を開始する'));
  if (!button || button.disabled) return 'gate-stuck';
  button.click();
  await sleep(3000);
  if (!document.body.textContent.includes('ご利用にあたって')) return 'consented';
}
return 'gate-stuck';
"""

_FETCH_JSON_JS_TEMPLATE = """
const res = await fetch({url!r}, {{credentials: 'include'}});
return {{status: res.status, body: await res.text()}};
"""


def build_browser_config(settings: Settings) -> BrowserConfig:
    proxy_config = None
    if settings.HTTP_PROXY_URL:
        proxy_config = ProxyConfig(server=settings.HTTP_PROXY_URL)
    return BrowserConfig(
        headless=True,
        user_data_dir=settings.PROFILE_DIR,
        use_persistent_context=True,
        user_agent=settings.USER_AGENT,
        proxy_config=proxy_config,
    )


def _run_config(**kwargs: Any) -> CrawlerRunConfig:
    return CrawlerRunConfig(
        session_id=SESSION_ID,
        cache_mode=CacheMode.BYPASS,
        **kwargs,
    )


async def open_easy_top(crawler: AsyncWebCrawler) -> None:
    """Open the list page, passing the consent gate if it appears."""
    result = await crawler.arun(EASY_TOP_URL, config=_run_config())
    if CONSENT_GATE_MARKER not in (result.html or ""):
        return
    logger.info("Consent gate detected, passing it")
    # The consent click navigates away; crawl4ai may flag the intermediate
    # redirect page (no <body>) as "anti-bot" and report failure. Ignore the
    # result here - the reload below is the source of truth.
    await crawler.arun(
        EASY_TOP_URL,
        config=_run_config(js_code=[_CONSENT_JS], js_only=True),
    )
    # Reload so the SPA restarts with the new session cookies.
    result = await crawler.arun(EASY_TOP_URL, config=_run_config())
    if CONSENT_GATE_MARKER in (result.html or ""):
        raise RuntimeError("failed to pass the NHK ONE consent gate")
    logger.info("Consent gate passed")


async def _fetch_json_in_page(crawler: AsyncWebCrawler, url: str) -> Any:
    """Fetch a JSON endpoint inside the current page context (session cookies
    and headers apply)."""
    js = _FETCH_JSON_JS_TEMPLATE.format(url=url)
    result = await crawler.arun(
        EASY_TOP_URL,
        config=_run_config(js_code=[js], js_only=True),
    )
    payload = result.js_execution_result
    if isinstance(payload, dict) and "results" in payload:
        payload = payload["results"][0]
    if not isinstance(payload, dict) or "status" not in payload:
        raise RuntimeError(f"unexpected js execution result for {url}: {payload!r}")
    if payload["status"] != 200:
        raise RuntimeError(f"GET {url} returned {payload['status']}")
    return json.loads(payload["body"])


async def fetch_news_list(crawler: AsyncWebCrawler) -> list[dict]:
    """Return the flat list of article entries from news-list.json.

    The endpoint returns `[{"<date>": [entry, ...], ...}]`; entries contain
    news_id, title, title_with_ruby, news_prearranged_time,
    news_easy_voice_uri, news_web_image_uri, news_web_movie_uri, etc.
    """
    data = await _fetch_json_in_page(crawler, NEWS_LIST_URL)
    entries: list[dict] = []
    for day_map in data:
        for day_entries in day_map.values():
            entries.extend(day_entries)
    return entries


async def fetch_media_token(crawler: AsyncWebCrawler) -> str:
    """Get an Akamai `hdnts` token for media.vd.st.nhk downloads."""
    data = await _fetch_json_in_page(crawler, MEDIA_TOKEN_URL)
    return data["token"]


async def fetch_article_html(crawler: AsyncWebCrawler, url: str) -> str:
    """Return the rendered article page HTML (body present)."""
    result = await crawler.arun(
        url,
        config=_run_config(wait_for="css:div.article-body"),
    )
    if not result.success:
        raise RuntimeError(f"failed to fetch article {url}: {result.error_message}")
    return result.html
