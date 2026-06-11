"""Local web reader for saved NHK Easy articles.

Run: uv run uvicorn nhk_easy.webapp.app:app
"""

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
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
templates = Jinja2Templates(
    directory=os.path.join(os.path.dirname(__file__), "templates")
)


@app.get("/", response_class=HTMLResponse)
async def article_list(request: Request):
    async with AsyncSession(engine) as session:
        result = await session.exec(
            select(Article).order_by(Article.published_at.desc())
        )
        articles = result.all()
    return templates.TemplateResponse(
        request, "list.html", {"articles": articles}
    )


@app.get("/article/{news_id}", response_class=HTMLResponse)
async def article_detail(request: Request, news_id: str):
    async with AsyncSession(engine) as session:
        article = await session.get(Article, news_id)
    if article is None:
        raise HTTPException(status_code=404, detail="article not found")
    return templates.TemplateResponse(
        request, "detail.html", {"article": article}
    )


@app.get("/audio/{news_id}")
async def article_audio(news_id: str):
    async with AsyncSession(engine) as session:
        article = await session.get(Article, news_id)
    if article is None or not article.audio_path or not os.path.exists(
        article.audio_path
    ):
        raise HTTPException(status_code=404, detail="audio not found")
    return FileResponse(article.audio_path, media_type="audio/mp4")
