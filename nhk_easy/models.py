from datetime import datetime

from sqlmodel import Field, SQLModel


class Article(SQLModel, table=True):
    __tablename__ = "articles"

    news_id: str = Field(primary_key=True)
    title: str
    title_with_ruby: str | None = None
    published_at: datetime | None = None
    url: str
    genre: str | None = None
    body_html: str | None = None
    body_text: str | None = None
    image_url: str | None = None
    video_m3u8: str | None = None
    audio_voice_id: str | None = None
    audio_path: str | None = None
    fetched_at: datetime = Field(default_factory=datetime.now)
