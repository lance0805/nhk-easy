# nhk-easy

Daily pipeline that downloads NHK News Web Easy articles (text + furigana + audio)
into a local PostgreSQL database, plus a local web reader. Orchestrated by Prefect.

## Goal

Visit https://news.web.nhk/news/easy/ every day with a real browser, download all
new articles including their narration audio, store everything locally, and browse
the saved articles offline through a simple web UI.

## Site facts (investigated 2026-06-11)

- First visit shows an NHK ONE consent gate (checkbox + usage type + region).
  Passing it triggers an anonymous auth flow (`/tix/build_authorize?...&ctu=in`)
  that sets session cookies. State persists in the browser profile.
- News list JSON: `https://news.web.nhk/news/easy/top-list.json` - requires JWT
  in Authorization header when fetched outside the page (401 otherwise). The
  rendered DOM contains the same list, so DOM parsing is the fallback.
- Article URL: `https://news.web.nhk/news/easy/ne<id>/ne<id>.html`
  (e.g. `ne2026061118568`).
- Article body uses `<ruby>KANJI<rt>KANA</rt></ruby>` furigana markup.
  Title in `h1.article-title`.
- Narration audio: link `a.js-open-audio` opens iframe
  `/news/easy/player/audio-v6.html?voiceId=<voiceId>.m4a&title=...`.
  Real stream: `https://media.vd.st.nhk/news/easy_audio/<voiceId>/index.m3u8`
  (HLS). Disaster pages use `https://media.vd.st.nhk/news/easy/<voiceId>/index.m3u8`.
- Embedded news video (optional): iframe src contains
  `mrurl=https://media.vd.st.nhk/news/<videoId>/index.m3u8`.
- `media.vd.st.nhk` is Akamai-protected: direct anonymous fetch returns 403.
  Segment URLs carry an `hdntl` token. Downloads must reuse the browser session
  (cookies + same UA), to be verified at implementation time; fallback is
  fetching inside the page context via JS.

## Architecture

One Prefect flow `daily_fetch`, scheduled daily (cron, Asia/Tokyo):

1. Open the list page with crawl4ai using a persistent browser profile
   (`user_data_dir`). Auto-pass the consent gate if it appears.
2. Get the article list (page-context `top-list.json` if reachable, else parse
   the rendered DOM).
3. Diff against `articles.news_id` in PostgreSQL; keep only new articles.
4. For each new article: fetch the article page, parse title / body (ruby HTML,
   plain text, kana-annotated text) / genre / image / voiceId / video m3u8;
   download the narration audio via HLS and merge to m4a with ffmpeg.
5. Upsert rows into PostgreSQL; audio saved to `data/audio/<news_id>.m4a`.

Idempotent: re-running never duplicates rows or re-downloads existing audio.

## Components

- `nhk_easy/settings.py` - pydantic-settings, `.env` file. Fields: `POSTGRES_*`,
  `HTTP_PROXY_URL` (optional, both browser and httpx honor it - mirrors
  MiraiGuard), `PROFILE_DIR`, `DATA_DIR`, `RUN_IN_DOCKER`.
- `nhk_easy/prefect_settings.py` - production config comes from a Prefect
  Secret block (default `nhk-easy-settings-secret`) holding a JSON document
  with postgres / http_proxy_url / directories sections (MiraiGuard pattern;
  the postgres section mirrors `miraiguard-settings-secret`). The flow takes
  `settings_block_name` and falls back to env vars when empty or missing.
- `nhk_easy/models.py` - SQLModel table `articles`: `news_id` (PK), `title`,
  `published_at`, `url`, `genre` (nullable, site-provided), `body_html`,
  `body_text`, `body_text_ruby`, `image_url`, `video_m3u8`, `audio_voice_id`,
  `audio_path`, `fetched_at`.
- `nhk_easy/db.py` - async engine (asyncpg), create tables, upsert helpers.
- `nhk_easy/browser.py` - crawl4ai wrapper: persistent profile, consent gate
  auto-pass (check the checkbox, click start, wait for reload), list fetch,
  article fetch, cookie export for media downloads. Proxy via
  `ProxyConfig(server=HTTP_PROXY_URL)` when set.
- `nhk_easy/parser.py` - lxml parsing of article HTML: strip `<rt>` for plain
  text, keep `<ruby>` markup for display, extract voiceId / video mrurl /
  image / published time.
- `nhk_easy/audio.py` - download `index.m3u8` + segments with httpx using
  exported browser cookies and matching UA (proxy honored), merge with ffmpeg
  to `.m4a`.
- `nhk_easy/flows/daily_fetch.py` - Prefect `@flow` + `@task`s wiring the above.
- `nhk_easy/webapp/` - FastAPI + Jinja2 local reader: article list page and
  detail page rendering the stored ruby HTML, `<audio>` tag serving the local
  m4a. Run: `uv run uvicorn nhk_easy.webapp.app:app`.

## Deployment

- `prefect.yaml` (declarative, like MiraiGuard's): deployment
  `fetch-nhk-easy-daily`, entrypoint `nhk_easy/flows/daily_fetch.py:daily_fetch`,
  cron `0 21 * * *` Asia/Tokyo (after the evening article batch ~20:00),
  work pool `default`. Deploy: `uv run prefect deploy --all`.

## System dependencies

ffmpeg (audio merge), PostgreSQL, Prefect server + worker, Chromium via
crawl4ai/Playwright (`uv run playwright install chromium`).

## Testing

- Parser unit tests with saved HTML fixtures (no network).
- Small-scale validation first: fetch a single article end-to-end before
  enabling the full daily run.

## Non-goals (for now)

- LLM-based classification (site-provided genre only).
- Downloading embedded news videos (URL is stored, file is not downloaded).
- Cloud storage; everything is local.
