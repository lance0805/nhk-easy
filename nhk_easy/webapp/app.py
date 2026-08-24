"""Local web reader for saved NHK Easy articles.

Run: uv run uvicorn nhk_easy.webapp.app:app
"""

import os
import unicodedata
from contextlib import asynccontextmanager
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Annotated, Protocol
from urllib.parse import parse_qs
from zipfile import ZIP_STORED, ZipFile

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from starlette.background import BackgroundTask

from nhk_easy.db import create_engine, init_db
from nhk_easy.models import Article
from nhk_easy.settings import Settings

settings = Settings()
engine = create_engine(settings)


class ArticleRepository(Protocol):
    async def get_all(self) -> list[Article]: ...

    async def get_by_news_ids(self, news_ids: list[str]) -> list[Article]: ...


class DatabaseArticleRepository:
    def __init__(self, database_engine):
        self._engine = database_engine

    async def get_all(self) -> list[Article]:
        async with AsyncSession(self._engine) as session:
            result = await session.exec(
                select(Article).order_by(Article.published_at.desc())
            )
            return list(result.all())

    async def get_by_news_ids(self, news_ids: list[str]) -> list[Article]:
        async with AsyncSession(self._engine) as session:
            result = await session.exec(
                select(Article).where(Article.news_id.in_(news_ids))
            )
            by_id = {article.news_id: article for article in result.all()}
        return [by_id[news_id] for news_id in news_ids if news_id in by_id]


async def get_article_repository() -> ArticleRepository:
    return DatabaseArticleRepository(engine)


def get_settings() -> Settings:
    return settings


def _resolved_audio_path(article: Article, audio_dir: str) -> Path | None:
    if not article.audio_path:
        return None
    try:
        allowed_root = Path(audio_dir).resolve(strict=True)
        resolved_path = Path(article.audio_path).resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not resolved_path.is_file() or not resolved_path.is_relative_to(allowed_root):
        return None
    return resolved_path


def _macos_audio_filename(title: str, suffix: str = "") -> str:
    replacements = {"/": "／", ":": "：", "\\": "＼"}
    normalized = unicodedata.normalize("NFC", title)
    safe_title = "".join(
        "_" if ord(character) < 32 or ord(character) == 127 else replacements.get(character, character)
        for character in normalized
    ).strip(" .")
    if not safe_title:
        safe_title = "news"
    max_title_bytes = 255 - len((suffix + ".m4a").encode("utf-8"))
    safe_title = safe_title.encode("utf-8")[:max_title_bytes].decode(
        "utf-8", errors="ignore"
    ).rstrip(" .")
    return f"{safe_title}{suffix}.m4a"


def _unique_audio_filenames(articles: list[Article]) -> list[str]:
    used: set[str] = set()
    filenames: list[str] = []
    for article in articles:
        occurrence = 1
        while True:
            suffix = "" if occurrence == 1 else f" ({occurrence})"
            filename = _macos_audio_filename(article.title, suffix)
            collision_key = filename.casefold()
            if collision_key not in used:
                used.add(collision_key)
                filenames.append(filename)
                break
            occurrence += 1
    return filenames


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup so the reader works before the first
    # fetch flow run (empty list instead of a missing-relation error).
    await init_db(engine)
    yield


app = FastAPI(title="nhk-easy reader", lifespan=lifespan)
_here = os.path.dirname(__file__)
_static_dir = os.path.join(_here, "static")
templates = Jinja2Templates(directory=os.path.join(_here, "templates"))
app.mount("/static", StaticFiles(directory=_static_dir), name="static")


def _static_version() -> str:
    """Cache-busting token from asset mtimes, so clients fetch fresh CSS/JS
    after a redeploy instead of serving a stale cached copy."""
    try:
        mtimes = [
            os.path.getmtime(os.path.join(_static_dir, f))
            for f in ("app.css", "app.js")
        ]
        return str(int(max(mtimes)))
    except OSError:
        return "1"


templates.env.globals["static_v"] = _static_version()


@app.get("/", response_class=HTMLResponse)
async def article_list(
    request: Request,
    repository: Annotated[ArticleRepository, Depends(get_article_repository)],
    configured_settings: Annotated[Settings, Depends(get_settings)],
):
    articles = await repository.get_all()
    playable_audio_ids = {
        article.news_id
        for article in articles
        if _resolved_audio_path(article, configured_settings.audio_dir) is not None
    }
    # Cards always request /image/{news_id}; the endpoint 404s when no image was
    # downloaded and the client falls back to the placeholder. This avoids a
    # per-article filesystem glob on every list render.
    return templates.TemplateResponse(
        request,
        "list.html",
        {"articles": articles, "playable_audio_ids": playable_audio_ids},
    )


def _local_image_path(news_id: str) -> str | None:
    """Path of the locally downloaded article image, if present."""
    import glob

    if not news_id.replace("_", "").isalnum():  # path-safety for the glob
        return None
    matches = glob.glob(os.path.join(settings.images_dir, f"{news_id}.*"))
    return matches[0] if matches else None


@app.get("/article/{news_id}", response_class=HTMLResponse)
async def article_detail(request: Request, news_id: str):
    async with AsyncSession(engine) as session:
        article = await session.get(Article, news_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return templates.TemplateResponse(
        request,
        "detail.html",
        {"article": article, "has_image": _local_image_path(news_id) is not None},
    )


@app.get("/image/{news_id}")
async def article_image(news_id: str):
    path = _local_image_path(news_id)
    if path is None:
        raise HTTPException(status_code=404, detail="image not found")
    return FileResponse(path)


@app.get("/audio/{news_id}")
async def article_audio(news_id: str):
    async with AsyncSession(engine) as session:
        article = await session.get(Article, news_id)
    if article is None or not article.audio_path or not os.path.exists(
        article.audio_path
    ):
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(article.audio_path, media_type="audio/mp4")


@app.post("/audio/archive")
async def audio_archive(
    request: Request,
    repository: Annotated[ArticleRepository, Depends(get_article_repository)],
    configured_settings: Annotated[Settings, Depends(get_settings)],
):
    try:
        form = parse_qs(
            (await request.body()).decode("utf-8"),
            keep_blank_values=True,
            strict_parsing=True,
            encoding="utf-8",
            errors="strict",
            max_num_fields=2000,
        )
    except (UnicodeDecodeError, ValueError):
        raise HTTPException(status_code=400, detail="invalid form body") from None
    news_ids = list(dict.fromkeys(form.get("news_id", [])))
    articles = await repository.get_by_news_ids(news_ids)
    available = []
    for article in articles:
        resolved_path = _resolved_audio_path(article, configured_settings.audio_dir)
        if resolved_path is not None:
            available.append((article, resolved_path))
    if not available:
        raise HTTPException(status_code=404, detail="no audio available")

    temporary_archive = NamedTemporaryFile(
        prefix="nhk-easy-audio-", suffix=".zip", delete=False
    )
    archive_path = temporary_archive.name
    temporary_archive.close()
    try:
        with ZipFile(archive_path, "w", compression=ZIP_STORED) as zip_file:
            filenames = _unique_audio_filenames(
                [article for article, _ in available]
            )
            for (_, audio_path), filename in zip(
                available, filenames, strict=True
            ):
                zip_file.write(audio_path, arcname=filename)
    except Exception:
        os.unlink(archive_path)
        raise

    return FileResponse(
        archive_path,
        media_type="application/zip",
        filename="聞いたニュース.zip",
        background=BackgroundTask(os.unlink, archive_path),
    )
