"""Load Settings from a Prefect Secret block (MiraiGuard pattern).

The block stores one JSON document; the relevant sections for nhk-easy:

    {
      "postgres": {"host": "...", "port": 5432, "user": "...",
                   "password": "...", "database": "nhk_easy"},
      "http_proxy_url": "http://...",          // optional
      "directories": {"data_dir": "/data/nhk", // optional
                      "profile_dir": "/data/chromium"}
    }

The postgres section can be copied from MiraiGuard's
"miraiguard-settings-secret" block (change `database` to nhk_easy's own).
"""

import os

from loguru import logger
from prefect.blocks.system import Secret

from nhk_easy.settings import Settings

DEFAULT_SETTINGS_BLOCK = "nhk-easy-settings-secret"


def settings_from_config(config: dict) -> Settings:
    """Build Settings from the Secret block's JSON document.

    Deployment-injected env vars (DATA_DIR/PROFILE_DIR set in the image) take
    precedence over the directories section, mirroring MiraiGuard's handling
    of mounted paths.
    """
    postgres = config.get("postgres", {})
    directories = config.get("directories", {})
    return Settings(
        POSTGRES_HOST=postgres.get("host", "localhost"),
        POSTGRES_PORT=postgres.get("port", 5432),
        POSTGRES_USER=postgres.get("user", "postgres"),
        POSTGRES_PASSWORD=postgres.get("password", ""),
        POSTGRES_DATABASE=postgres.get("database", "nhk_easy"),
        HTTP_PROXY_URL=config.get("http_proxy_url") or None,
        DATA_DIR=os.environ.get("DATA_DIR")
        or directories.get("data_dir")
        or Settings.model_fields["DATA_DIR"].default,
        PROFILE_DIR=os.environ.get("PROFILE_DIR")
        or directories.get("profile_dir")
        or Settings.model_fields["PROFILE_DIR"].default,
    )


async def load_settings_from_secret_block(
    secret_block_name: str = DEFAULT_SETTINGS_BLOCK,
) -> Settings:
    """Load Settings from a Prefect Secret block containing JSON config.

    Raises if the block does not exist or holds invalid content.
    """
    logger.info(f"Loading settings from Prefect Secret block: {secret_block_name}")
    secret_block = await Secret.load(secret_block_name)
    config = secret_block.get()
    if not isinstance(config, dict):
        raise ValueError(
            f"Secret block {secret_block_name} must contain a JSON object"
        )
    return settings_from_config(config)


async def resolve_settings(settings_block_name: str) -> Settings:
    """Settings from the Secret block when a name is given (falling back to
    env vars on failure), or from .env/env vars when the name is empty."""
    if settings_block_name:
        try:
            return await load_settings_from_secret_block(settings_block_name)
        except Exception as e:
            logger.warning(
                f"Failed to load Secret block {settings_block_name}: {e}; "
                "falling back to environment variables"
            )
    return Settings()
