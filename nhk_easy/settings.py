import os

from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Settings(BaseSettings):
    model_config: SettingsConfigDict = SettingsConfigDict(
        env_file=os.path.join(PROJECT_ROOT, ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Directories ---
    PROFILE_DIR: str = os.path.join(PROJECT_ROOT, ".chromium")
    DATA_DIR: str = os.path.join(PROJECT_ROOT, "data")

    # --- PostgreSQL ---
    POSTGRES_HOST: str = "localhost"
    POSTGRES_PORT: int = 5432
    POSTGRES_USER: str = "postgres"
    POSTGRES_PASSWORD: str = ""
    POSTGRES_DATABASE: str = "nhk_easy"

    # --- Network ---
    # Optional proxy applied to both the crawl4ai browser and httpx/ffmpeg
    # downloads (mirrors MiraiGuard's HTTP_PROXY_URL convention).
    HTTP_PROXY_URL: str | None = None
    RUN_IN_DOCKER: bool = False

    USER_AGENT: str = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    )

    @property
    def postgres_dsn(self) -> str:
        return (
            f"postgresql+asyncpg://{self.POSTGRES_USER}:{self.POSTGRES_PASSWORD}"
            f"@{self.POSTGRES_HOST}:{self.POSTGRES_PORT}/{self.POSTGRES_DATABASE}"
        )

    @property
    def audio_dir(self) -> str:
        return os.path.join(self.DATA_DIR, "audio")
