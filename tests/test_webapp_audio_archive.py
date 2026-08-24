from io import BytesIO
import re
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from fastapi.testclient import TestClient

from nhk_easy.models import Article
from nhk_easy.settings import Settings
from nhk_easy.webapp.app import app, get_article_repository, get_settings


class StubArticleRepository:
    def __init__(self, articles: list[Article]):
        self._articles = {article.news_id: article for article in articles}

    async def get_by_news_ids(self, news_ids: list[str]) -> list[Article]:
        return [self._articles[news_id] for news_id in news_ids if news_id in self._articles]

    async def get_all(self) -> list[Article]:
        return list(self._articles.values())


@pytest.fixture(autouse=True)
def configured_audio_dir(tmp_path):
    app.dependency_overrides[get_settings] = lambda: SimpleNamespace(
        audio_dir=str(tmp_path)
    )
    yield
    app.dependency_overrides.clear()


def test_user_can_download_selected_audio_as_a_title_named_zip(tmp_path):
    first_audio = tmp_path / "first.m4a"
    first_audio.write_bytes(b"first audio")
    second_audio = tmp_path / "second.m4a"
    second_audio.write_bytes(b"second audio")
    repository = StubArticleRepository(
        [
            Article(
                news_id="ne1",
                title="東京のニュース",
                url="https://example.com/ne1",
                audio_path=str(first_audio),
            ),
            Article(
                news_id="ne2",
                title="大阪のニュース",
                url="https://example.com/ne2",
                audio_path=str(second_audio),
            ),
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={"news_id": ["ne1", "ne2"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    assert "attachment" in response.headers["content-disposition"]
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["東京のニュース.m4a", "大阪のニュース.m4a"]
        assert archive.read("東京のニュース.m4a") == b"first audio"
        assert archive.read("大阪のニュース.m4a") == b"second audio"


def test_archive_entry_names_are_macos_safe_and_utf8_length_limited(tmp_path):
    unsafe_audio = tmp_path / "unsafe.m4a"
    unsafe_audio.write_bytes(b"unsafe title audio")
    long_audio = tmp_path / "long.m4a"
    long_audio.write_bytes(b"long title audio")
    repository = StubArticleRepository(
        [
            Article(
                news_id="unsafe",
                title="京都/大阪:ガイド\n",
                url="https://example.com/unsafe",
                audio_path=str(unsafe_audio),
            ),
            Article(
                news_id="long",
                title="長" * 100,
                url="https://example.com/long",
                audio_path=str(long_audio),
            ),
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={"news_id": ["unsafe", "long"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "京都／大阪：ガイド_.m4a",
            f"{'長' * 83}.m4a",
        ]
        assert all(len(name.encode("utf-8")) <= 255 for name in archive.namelist())


def test_archive_entry_names_are_unique_on_case_insensitive_macos(tmp_path):
    articles = []
    titles = ["News", "news", "長" * 100, "長" * 100]
    for index, title in enumerate(titles, start=1):
        audio = tmp_path / f"audio-{index}.m4a"
        audio.write_bytes(f"audio {index}".encode())
        articles.append(
            Article(
                news_id=f"ne{index}",
                title=title,
                url=f"https://example.com/ne{index}",
                audio_path=str(audio),
            )
        )
    app.dependency_overrides[get_article_repository] = lambda: StubArticleRepository(
        articles
    )

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={"news_id": ["ne1", "ne2", "ne3", "ne4"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == [
            "News.m4a",
            "news (2).m4a",
            f"{'長' * 83}.m4a",
            f"{'長' * 82} (2).m4a",
        ]
        assert [archive.read(name) for name in archive.namelist()] == [
            b"audio 1",
            b"audio 2",
            b"audio 3",
            b"audio 4",
        ]
        assert all(len(name.encode("utf-8")) <= 255 for name in archive.namelist())


def test_archive_excludes_unknown_and_unavailable_audio(tmp_path):
    available_audio = tmp_path / "available.m4a"
    available_audio.write_bytes(b"available audio")
    repository = StubArticleRepository(
        [
            Article(
                news_id="available",
                title="利用できるニュース",
                url="https://example.com/available",
                audio_path=str(available_audio),
            ),
            Article(
                news_id="without-path",
                title="音声がないニュース",
                url="https://example.com/without-path",
                audio_path=None,
            ),
            Article(
                news_id="missing-file",
                title="ファイルがないニュース",
                url="https://example.com/missing-file",
                audio_path=str(tmp_path / "does-not-exist.m4a"),
            ),
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={
                "news_id": [
                    "unknown",
                    "without-path",
                    "available",
                    "missing-file",
                ]
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["利用できるニュース.m4a"]
        assert archive.read("利用できるニュース.m4a") == b"available audio"


def test_archive_returns_not_found_when_no_selected_audio_is_available(tmp_path):
    unrequested_audio = tmp_path / "unrequested.m4a"
    unrequested_audio.write_bytes(b"must not be exported")
    repository = StubArticleRepository(
        [
            Article(
                news_id="missing-file",
                title="ファイルがないニュース",
                url="https://example.com/missing-file",
                audio_path=str(tmp_path / "does-not-exist.m4a"),
            )
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={
                "news_id": ["unknown", "missing-file"],
                "audio_path": str(unrequested_audio),
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 404
    assert response.json() == {"detail": "no audio available"}


def test_archive_exports_a_repeated_news_id_only_once(tmp_path):
    audio = tmp_path / "repeated.m4a"
    audio.write_bytes(b"one copy")
    repository = StubArticleRepository(
        [
            Article(
                news_id="repeated",
                title="同じニュース",
                url="https://example.com/repeated",
                audio_path=str(audio),
            )
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={"news_id": ["repeated", "repeated", "repeated"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["同じニュース.m4a"]
        assert archive.read("同じニュース.m4a") == b"one copy"


def test_archive_only_exports_real_files_inside_configured_audio_dir(tmp_path):
    data_dir = tmp_path / "data"
    audio_dir = data_dir / "audio"
    audio_dir.mkdir(parents=True)
    allowed_audio = audio_dir / "allowed.m4a"
    allowed_audio.write_bytes(b"allowed")
    outside_audio = tmp_path / "outside.m4a"
    outside_audio.write_bytes(b"outside")
    escaping_symlink = audio_dir / "escaping.m4a"
    escaping_symlink.symlink_to(outside_audio)
    repository = StubArticleRepository(
        [
            Article(
                news_id="allowed",
                title="安全なニュース",
                url="https://example.com/allowed",
                audio_path=str(allowed_audio),
            ),
            Article(
                news_id="outside",
                title="外部ファイル",
                url="https://example.com/outside",
                audio_path=str(outside_audio),
            ),
            Article(
                news_id="symlink",
                title="外へのリンク",
                url="https://example.com/symlink",
                audio_path=str(escaping_symlink),
            ),
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository
    app.dependency_overrides[get_settings] = lambda: Settings(DATA_DIR=str(data_dir))

    try:
        response = TestClient(app).post(
            "/audio/archive",
            data={"news_id": ["allowed", "outside", "symlink"]},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    with ZipFile(BytesIO(response.content)) as archive:
        assert archive.namelist() == ["安全なニュース.m4a"]
        assert archive.read("安全なニュース.m4a") == b"allowed"


def test_archive_rejects_malformed_utf8_form_body():
    response = TestClient(app, raise_server_exceptions=False).post(
        "/audio/archive",
        content=b"news_id=valid&news_id=\xff",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "invalid form body"}


def test_article_list_only_marks_existing_audio_as_available(tmp_path):
    existing_audio = tmp_path / "existing.m4a"
    existing_audio.write_bytes(b"existing")
    repository = StubArticleRepository(
        [
            Article(
                news_id="existing",
                title="音声があるニュース",
                url="https://example.com/existing",
                audio_path=str(existing_audio),
            ),
            Article(
                news_id="stale",
                title="音声がないニュース",
                url="https://example.com/stale",
                audio_path=str(tmp_path / "missing.m4a"),
            ),
        ]
    )
    app.dependency_overrides[get_article_repository] = lambda: repository

    response = TestClient(app, raise_server_exceptions=False).get("/")

    assert response.status_code == 200
    existing_card = re.search(
        r'<article class="card"[^>]*data-id="existing"[^>]*>', response.text
    )
    stale_card = re.search(
        r'<article class="card"[^>]*data-id="stale"[^>]*>', response.text
    )
    assert existing_card is not None
    assert 'data-has-audio="true"' in existing_card.group()
    assert stale_card is not None
    assert 'data-has-audio="false"' in stale_card.group()
