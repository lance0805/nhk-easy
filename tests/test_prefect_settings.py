import os
from unittest.mock import patch

from nhk_easy.prefect_settings import settings_from_config


def test_settings_from_config_postgres():
    config = {
        "postgres": {
            "host": "db.example.com",
            "port": 15432,
            "user": "nhk",
            "password": "secret",
            "database": "nhk_easy",
        },
        "http_proxy_url": "http://proxy:7890",
    }
    s = settings_from_config(config)
    assert s.POSTGRES_HOST == "db.example.com"
    assert s.POSTGRES_PORT == 15432
    assert s.postgres_dsn == (
        "postgresql+asyncpg://nhk:secret@db.example.com:15432/nhk_easy"
    )
    assert s.HTTP_PROXY_URL == "http://proxy:7890"


def test_settings_from_config_defaults_and_empty_proxy():
    s = settings_from_config({"postgres": {}, "http_proxy_url": ""})
    assert s.POSTGRES_DATABASE == "nhk_easy"
    assert s.HTTP_PROXY_URL is None


def test_settings_from_config_env_dirs_take_precedence():
    config = {
        "postgres": {},
        "directories": {"data_dir": "/from/block", "profile_dir": "/from/block/p"},
    }
    with patch.dict(os.environ, {"DATA_DIR": "/from/env"}, clear=False):
        s = settings_from_config(config)
    assert s.DATA_DIR == "/from/env"
    assert s.PROFILE_DIR == "/from/block/p"
