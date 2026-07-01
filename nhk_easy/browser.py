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
// The gate is SPA-rendered; poll for the checkbox before concluding it is
// absent, so a race with the render is not mistaken for "no gate". This is
// what lets the recovery path (forced consent after a 401) succeed even when
// the gate had not finished rendering during the initial page load.
let checkbox = null;
for (let i = 0; i < 10; i++) {
  checkbox = document.querySelector('input[type=checkbox]');
  if (checkbox) break;
  await sleep(500);
}
if (!checkbox) return 'no-gate';
for (let attempt = 0; attempt < 3; attempt++) {
  const cb = document.querySelector('input[type=checkbox]');
  if (!cb) return 'consented';
  if (!cb.checked) cb.click();
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

_FETCH_BINARY_JS_TEMPLATE = """
const res = await fetch({url!r}, {{credentials: 'include'}});
if (res.status !== 200) return {{status: res.status, b64: ''}};
const bytes = new Uint8Array(await res.arrayBuffer());
let bin = '';
const chunk = 0x8000;
for (let i = 0; i < bytes.length; i += chunk) {{
  bin += String.fromCharCode.apply(null, bytes.subarray(i, i + chunk));
}}
return {{status: 200, b64: btoa(bin)}};
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


async def _probe_session_status(crawler: AsyncWebCrawler) -> int:
    """HTTP status of a news-list.json fetch in the current page session.

    Unlike _fetch_json_in_page this never raises on a non-200 - it returns the
    status so the caller can decide whether the session needs re-consent.
    Returns -1 when the fetch could not run at all (JS did not report a status).
    """
    js = _FETCH_JSON_JS_TEMPLATE.format(url=NEWS_LIST_URL)
    result = await crawler.arun(
        EASY_TOP_URL,
        config=_run_config(js_code=[js], js_only=True),
    )
    payload = result.js_execution_result
    if isinstance(payload, dict) and "results" in payload:
        payload = payload["results"][0]
    if isinstance(payload, dict) and "status" in payload:
        return int(payload["status"])
    return -1


async def _pass_consent_gate(crawler: AsyncWebCrawler) -> None:
    """Run the consent click-through on the currently loaded page, then reload
    so the SPA restarts with the new session cookies. Raises if the gate is
    still present after the reload. The consent JS polls for the gate to
    render, so this is safe to call whenever the session looks unauthorized -
    if no gate is actually shown it is a no-op click-through."""
    logger.info("Passing NHK ONE consent gate")
    # The consent click navigates away; crawl4ai may flag the intermediate
    # redirect page (no <body>) as "anti-bot" and report failure. Ignore the
    # result here - the reload below is the source of truth.
    await crawler.arun(
        EASY_TOP_URL,
        config=_run_config(js_code=[_CONSENT_JS], js_only=True),
    )
    result = await crawler.arun(EASY_TOP_URL, config=_run_config())
    if CONSENT_GATE_MARKER in (result.html or ""):
        raise RuntimeError("failed to pass the NHK ONE consent gate")


async def open_easy_top(crawler: AsyncWebCrawler) -> None:
    """Open the list page and guarantee an authorized session.

    Passing the visible consent gate is not enough on its own: a lapsed
    anonymous-auth cookie (or an SPA render that outraces our HTML snapshot)
    can leave the gate unseen while the JSON endpoints still 401. So after the
    initial gate pass we *verify* the session by probing news-list.json, and on
    failure we force one more consent attempt before giving up. Flow-level
    Prefect retries cover the residual case where the session cannot recover
    within a single run.
    """
    result = await crawler.arun(EASY_TOP_URL, config=_run_config())
    if CONSENT_GATE_MARKER in (result.html or ""):
        await _pass_consent_gate(crawler)

    status = await _probe_session_status(crawler)
    if status == 200:
        logger.info("NHK ONE session authorized")
        return

    # Unauthorized despite the check above - the gate likely raced the initial
    # HTML snapshot, or the cookie lapsed. The consent JS waits for the gate to
    # render, so run it against the live page, reload, and re-probe once.
    logger.warning(f"Session probe returned {status}; forcing re-consent")
    await _pass_consent_gate(crawler)
    status = await _probe_session_status(crawler)
    if status != 200:
        raise RuntimeError(
            "NHK ONE session not authorized after re-consent "
            f"(news-list.json returned {status})"
        )
    logger.info("NHK ONE session recovered after re-consent")


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


async def fetch_binary_in_page(crawler: AsyncWebCrawler, url: str) -> bytes | None:
    """Fetch a binary resource (e.g. article image) inside the page session.

    NHK images live behind the same JWT gateway as the JSON endpoints
    (anonymous requests get 401), so they must be fetched with the page's
    credentials. Returns None when the resource is not accessible.
    """
    import base64

    js = _FETCH_BINARY_JS_TEMPLATE.format(url=url)
    result = await crawler.arun(
        EASY_TOP_URL,
        config=_run_config(js_code=[js], js_only=True),
    )
    payload = result.js_execution_result
    if isinstance(payload, dict) and "results" in payload:
        payload = payload["results"][0]
    if not isinstance(payload, dict) or payload.get("status") != 200:
        logger.warning(f"binary fetch failed for {url}: {payload!r}")
        return None
    return base64.b64decode(payload["b64"])


async def fetch_article_html(crawler: AsyncWebCrawler, url: str) -> str:
    """Return the rendered article page HTML (body present)."""
    result = await crawler.arun(
        url,
        config=_run_config(wait_for="css:div.article-body"),
    )
    if not result.success:
        raise RuntimeError(f"failed to fetch article {url}: {result.error_message}")
    return result.html
