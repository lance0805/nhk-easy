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

# Register the daily deployment (21:00 Asia/Tokyo): builds nhk-easy:latest
# from ./Dockerfile and registers it on the docker work pool (local-pool),
# mirroring MiraiGuard's multi-deploy.py. Run on the worker host.
uv run python multi-deploy.py

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

## Docker deployment

`multi-deploy.py` (MiraiGuard pattern) does everything in one step on the
worker host: it builds `nhk-easy:latest` from `./Dockerfile`
(`image_pull_policy: Never`, no registry push) and registers the
`fetch-nhk-easy-daily` deployment on the `local-pool` docker work pool.
Flow-run containers get these mounts from `COMMON_JOB_VARS`:

- `<repo>/.chromium-docker` -> `/data/chromium` - container browser profile.
  Kept separate from the host-run `.chromium`: a macOS-created profile is
  unusable on Linux (Chromium encrypts cookies via the OS keychain). The
  first flow run passes the NHK consent gate by itself.
- `<repo>/data` -> `/data/nhk` - downloaded audio (`data/audio/*.m4a`).

One-off manual container run for testing:

```bash
docker build -t nhk-easy .
docker run --rm \
  -v "$PWD/.chromium-docker:/data/chromium" \
  -v "$PWD/data:/data/nhk" \
  --shm-size 1g \
  nhk-easy
```

## Tests

```bash
uv run pytest
```
