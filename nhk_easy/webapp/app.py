"""Local web reader for saved NHK Easy articles.

Run: uv run uvicorn nhk_easy.webapp.app:app
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from nhk_easy.db import create_engine, init_db
from nhk_easy.models import Article
from nhk_easy.settings import Settings

settings = Settings()
engine = create_engine(settings)


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
async def article_list(request: Request):
    async with AsyncSession(engine) as session:
        result = await session.exec(
            select(Article).order_by(Article.published_at.desc())
        )
        articles = result.all()
    # Cards always request /image/{news_id}; the endpoint 404s when no image was
    # downloaded and the client falls back to the placeholder. This avoids a
    # per-article filesystem glob on every list render.
    return templates.TemplateResponse(
        request, "list.html", {"articles": articles}
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
