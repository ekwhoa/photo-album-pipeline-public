from datetime import datetime
from typing import List
from fastapi import FastAPI
from fastapi.testclient import TestClient
from unittest.mock import patch

from api.routes import books as books_router
from domain.models import Asset, AssetMetadata, AssetStatus, AssetType, Book, BookSize
from services.itinerary import build_book_itinerary


class DummySession:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def _asset(aid: str, ts: datetime) -> Asset:
    meta = AssetMetadata(taken_at=ts, gps_lat=41.0, gps_lon=-87.0)
    return Asset(
        id=aid,
        book_id="book1",
        status=AssetStatus.APPROVED,
        type=AssetType.PHOTO,
        file_path=f"{aid}.jpg",
        metadata=meta,
    )


@patch.object(books_router, "SessionLocal", return_value=DummySession())
@patch.object(books_router, "build_book_itinerary")
@patch.object(books_router.books_repo, "get_book")
@patch.object(books_router.assets_repo, "list_assets")
@patch.object(books_router.TimelineService, "organize_assets_by_day")
def test_itinerary_endpoint_returns_days(
    mock_days,
    mock_assets,
    mock_get_book,
    mock_build,
    mock_session,
):
    # Arrange mock book and assets
    ts = datetime(2025, 8, 1, 12, 0, 0)
    asset_list: List[Asset] = [_asset("a1", ts)]
    mock_assets.return_value = asset_list
    mock_get_book.return_value = Book(id="book1", title="Test", size=BookSize.SQUARE_8)
    mock_days.return_value = []  # days built by timeline not important; build_book_itinerary is mocked

    mock_build.return_value = [
        books_router.ItineraryDayResponse(
            day_index=1,
            date_iso="2025-08-01",
            photos_count=1,
            segments_total_distance_km=0.0,
            segments_total_duration_hours=0.0,
            location_short=None,
            location_full=None,
            stops=[],
        )
    ]

    app = FastAPI()
    app.include_router(books_router.router, prefix="/books")
    client = TestClient(app)

    resp = client.get("/books/book1/itinerary")
    assert resp.status_code == 200
    data = resp.json()
    assert data["book_id"] == "book1"
    assert isinstance(data["days"], list)
    assert data["days"][0]["day_index"] == 1
    assert "locations" in data["days"][0]
    assert isinstance(data["days"][0]["locations"], list)
