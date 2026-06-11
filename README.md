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

## Configuration via Prefect Secret block

Like MiraiGuard, runtime config lives in a Prefect Secret block
(default name `nhk-easy-settings-secret`) holding one JSON document:

```json
{
  "postgres": {"host": "...", "port": 5432, "user": "...",
               "password": "...", "database": "nhk_easy"},
  "http_proxy_url": "",
  "directories": {"data_dir": "/data/nhk", "profile_dir": "/data/chromium"}
}
```

The postgres section can be copied from the `miraiguard-settings-secret`
block (set `database` to nhk-easy's own database). The flow falls back to
`.env`/env vars when the block is missing or when
`settings_block_name=""` is passed (local development).

## Docker

```bash
docker build -t nhk-easy .

# One-off fetch run. First run passes the NHK consent gate automatically;
# keep the browser profile in a named volume so it only happens once.
docker run --rm \
  -v nhk-easy-chromium:/data/chromium \
  -v nhk-easy-data:/data/nhk \
  -e PREFECT_API_URL=... -e PREFECT_API_KEY=... \
  --shm-size 1g \
  nhk-easy
```

Audio files land in `/data/nhk/audio` (the `nhk-easy-data` volume). For
Prefect-scheduled runs, point a docker-type work pool at the `nhk-easy`
image with the same volumes, plus `--shm-size 1g` (Chromium needs more
shared memory than the 64MB docker default). Note: the container keeps its
own browser profile - a macOS host profile cannot be reused on Linux
because Chromium encrypts cookies with the OS keychain.

## Tests

```bash
uv run pytest
```
