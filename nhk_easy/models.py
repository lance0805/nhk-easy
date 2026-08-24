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


class ListeningProgress(SQLModel, table=True):
    __tablename__ = "listening_progress"

    news_id: str = Field(primary_key=True)
    completed_plays: int = Field(default=0, ge=0, le=20)


class ListeningProgressUpdate(SQLModel):
    completed_plays: int = Field(ge=0, le=20)
