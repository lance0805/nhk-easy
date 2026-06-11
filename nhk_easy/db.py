from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlmodel import SQLModel, select
from sqlmodel.ext.asyncio.session import AsyncSession

from nhk_easy.models import Article
from nhk_easy.settings import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    return create_async_engine(settings.postgres_dsn, pool_pre_ping=True)


async def init_db(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)


async def existing_news_ids(engine: AsyncEngine) -> set[str]:
    async with AsyncSession(engine) as session:
        result = await session.exec(select(Article.news_id))
        return set(result.all())


async def articles_with_image_urls(engine: AsyncEngine) -> list[tuple[str, str]]:
    """(news_id, image_url) for all articles that reference a remote image."""
    async with AsyncSession(engine) as session:
        result = await session.exec(
            select(Article.news_id, Article.image_url).where(
                Article.image_url.is_not(None), Article.image_url != ""
            )
        )
        return list(result.all())


async def upsert_article(engine: AsyncEngine, article: Article) -> None:
    values = article.model_dump()
    stmt = insert(Article).values(**values)
    update_cols = {k: v for k, v in values.items() if k != "news_id"}
    stmt = stmt.on_conflict_do_update(index_elements=["news_id"], set_=update_cols)
    async with AsyncSession(engine) as session:
        await session.exec(stmt)
        await session.commit()
