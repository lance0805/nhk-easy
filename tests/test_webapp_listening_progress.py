from fastapi.testclient import TestClient

from nhk_easy.models import ListeningProgress
from nhk_easy.webapp.app import app, get_listening_progress_repository


class InMemoryListeningProgressRepository:
    def __init__(self, progress: list[ListeningProgress] | None = None):
        self._counts = {
            item.news_id: item.completed_plays for item in (progress or [])
        }

    async def get_all(self) -> list[ListeningProgress]:
        return [
            ListeningProgress(news_id=news_id, completed_plays=count)
            for news_id, count in self._counts.items()
        ]

    async def increment(self, news_id: str) -> ListeningProgress:
        self._counts[news_id] = min(self._counts.get(news_id, 0) + 1, 20)
        return ListeningProgress(
            news_id=news_id, completed_plays=self._counts[news_id]
        )

    async def set_completed_plays(
        self, news_id: str, completed_plays: int
    ) -> ListeningProgress:
        self._counts[news_id] = completed_plays
        return ListeningProgress(news_id=news_id, completed_plays=completed_plays)


def test_progress_survives_page_and_app_client_reload():
    repository = InMemoryListeningProgressRepository(
        [ListeningProgress(news_id="ne2026062413017", completed_plays=20)]
    )
    app.dependency_overrides[get_listening_progress_repository] = lambda: repository

    try:
        first_load = TestClient(app).get("/api/listening-progress")
        restarted_client_load = TestClient(app).get("/api/listening-progress")
    finally:
        app.dependency_overrides.clear()

    expected = {"counts": {"ne2026062413017": 20}}
    assert first_load.status_code == 200
    assert first_load.json() == expected
    assert restarted_client_load.status_code == 200
    assert restarted_client_load.json() == expected


def test_completed_play_is_accumulated_on_the_server_and_capped_at_twenty():
    repository = InMemoryListeningProgressRepository(
        [ListeningProgress(news_id="ne2026072313058", completed_plays=19)]
    )
    app.dependency_overrides[get_listening_progress_repository] = lambda: repository

    try:
        completed = TestClient(app).post(
            "/api/listening-progress/ne2026072313058/plays"
        )
        extra_completion = TestClient(app).post(
            "/api/listening-progress/ne2026072313058/plays"
        )
        reloaded = TestClient(app).get("/api/listening-progress")
    finally:
        app.dependency_overrides.clear()

    expected_item = {
        "news_id": "ne2026072313058",
        "completed_plays": 20,
    }
    assert completed.status_code == 200
    assert completed.json() == expected_item
    assert extra_completion.status_code == 200
    assert extra_completion.json() == expected_item
    assert reloaded.json() == {"counts": {"ne2026072313058": 20}}


def test_progress_can_be_set_to_twenty_through_the_public_api():
    repository = InMemoryListeningProgressRepository()
    app.dependency_overrides[get_listening_progress_repository] = lambda: repository

    try:
        responses = [
            TestClient(app).put(
                f"/api/listening-progress/{news_id}",
                json={"completed_plays": 20},
            )
            for news_id in (
                "ne2026062413017",
                "ne2026072313058",
                "ne2026080412537",
            )
        ]
        reloaded = TestClient(app).get("/api/listening-progress")
    finally:
        app.dependency_overrides.clear()

    assert [response.status_code for response in responses] == [200, 200, 200]
    assert reloaded.json() == {
        "counts": {
            "ne2026062413017": 20,
            "ne2026072313058": 20,
            "ne2026080412537": 20,
        }
    }
