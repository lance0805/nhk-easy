"""Programmatic Prefect deployment (mirrors MiraiGuard's multi-deploy.py).

Run from the repo root on the worker host:

    uv run python multi-deploy.py

This builds the nhk-easy:latest image from ./Dockerfile and registers the
deployment on the docker work pool. Flow-run containers mount writable dirs
from the repo root (browser profile, downloaded audio).
"""

from datetime import datetime, timedelta

from prefect import deploy
from prefect.client.schemas.schedules import IntervalSchedule
from prefect.docker import DockerImage

from nhk_easy.flows.daily_fetch import daily_fetch

# Volume mounts are NOT set here: the nhk-easy-pool work pool's base job
# template provides the defaults (<repo>/.chromium-docker:/data/chromium and
# <repo>/data:/data/nhk on the worker host). The browser profile dir is kept
# separate from any host-run .chromium profile: a profile created by macOS
# Chromium is unusable inside the Linux container (cookies are encrypted via
# the OS keychain); the container passes the NHK consent gate itself on
# first run and the profile persists afterwards.
COMMON_JOB_VARS = {
    "image_pull_policy": "Never",
    "env": {
        "PREFECT_API_URL": "http://prefect-server:4200/api",
        "PREFECT_EVENTS_API_URL": "ws://prefect-server:4200/api/events",
        "RUN_IN_DOCKER": "true",
        # Keep mutable state outside /app: Prefect copies the deployment
        # workspace into /tmp/prefect-flow-run-* before execution; anything
        # under /app can be duplicated per flow-run container.
        "PROFILE_DIR": "/data/chromium",
        "DATA_DIR": "/data/nhk",
    },
}


if __name__ == "__main__":
    deploy(
        daily_fetch.to_deployment(
            "fetch-nhk-easy-daily",
            description=(
                "Daily download of NHK News Web Easy articles "
                "(text + furigana + audio)."
            ),
            parameters={
                "settings_block_name": "nhk-easy-settings-secret",
            },
            job_variables=COMMON_JOB_VARS,
            tags=["nhk-easy", "news-fetcher"],
            schedules=[
                IntervalSchedule(
                    interval=timedelta(days=1),
                    anchor_date=datetime.fromisoformat("2024-01-01T21:00:00+09:00"),
                    timezone="Asia/Tokyo",
                )
            ],
        ),
        image=DockerImage(
            name="nhk-easy:latest",
            dockerfile="Dockerfile",
            pull=False,
        ),
        push=False,
        work_pool_name="nhk-easy-pool",
    )
