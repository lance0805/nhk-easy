# nhk-easy

Daily pipeline that downloads NHK News Web Easy (https://news.web.nhk/news/easy/)
articles - text with furigana plus narration audio - into a local PostgreSQL
database, orchestrated by Prefect, with a local web reader.

See `SPEC.md` for the full design.

## Setup

```bash
uv sync
uv run playwright install chromium   # browser for crawl4ai
cp .env.example .env                  # fill in POSTGRES_*
```

System dependencies: PostgreSQL, ffmpeg, a running Prefect server + worker.

## Run

```bash
# One-off local run
uv run python -m nhk_easy.flows.daily_fetch

# Register the daily deployment (cron 21:00 Asia/Tokyo)
uv run prefect deploy --all

# Local web reader at http://127.0.0.1:8000
uv run uvicorn nhk_easy.webapp.app:app
```

## Tests

```bash
uv run pytest
```
