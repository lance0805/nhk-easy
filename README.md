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

## Docker

```bash
docker compose build fetcher        # build the runtime image (nhk-easy:latest)
docker compose up -d postgres       # database

# One-off fetch run (first run passes the consent gate automatically;
# the browser profile persists in the named volume "chromium")
docker compose run --rm fetcher

# Web reader at http://127.0.0.1:8000
docker compose --profile reader up -d reader
```

Audio files land in `./data/audio/` (bind-mounted as `/data/nhk` in the
container). Note: the container keeps its own browser profile in a named
volume - a macOS host profile cannot be reused on Linux because Chromium
encrypts cookies with the OS keychain.

For Prefect-scheduled runs, point a docker-type work pool at the
`nhk-easy:latest` image with the same environment and volumes as the
`fetcher` service.

## Tests

```bash
uv run pytest
```
