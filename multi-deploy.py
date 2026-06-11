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

import os

# Repo root on the WORKER host (not the machine running this script) - the
# bind-mount sources must exist where flow-run containers are spawned.
# Deployment-level job_variables override the work pool's volume defaults,
# so this rides MiraiGuard's existing local-pool worker; no extra worker
# container or dedicated pool is needed.
_WORKER_HOST_ROOT = os.environ.get(
    "NHK_EASY_HOST_ROOT", "/Users/hyl/Documents/source/lance/nhk-easy"
)

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
    "volumes": [
        # Kept separate from any host-run .chromium profile: a profile
        # created by macOS Chromium is unusable inside the Linux container
        # (cookies are encrypted via the OS keychain). The container passes
        # the NHK consent gate itself on first run.
        f"{_WORKER_HOST_ROOT}/.chromium-docker:/data/chromium",
        f"{_WORKER_HOST_ROOT}/data:/data/nhk",
    ],
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
        work_pool_name="local-pool",
    )
