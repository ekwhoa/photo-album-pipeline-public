from datetime import datetime
from unittest.mock import patch

from domain.models import (
    Asset,
    AssetMetadata,
    AssetStatus,
    AssetType,
    Book,
    BookSize,
    Day,
    Event,
    ManifestEntry,
)
from services.itinerary import build_book_itinerary, _classify_stop_kind
from services.geocoding import PlaceLabel


def _asset(aid: str, ts: datetime, lat: float, lon: float) -> Asset:
    meta = AssetMetadata(
        taken_at=ts,
        gps_lat=lat,
        gps_lon=lon,
    )
    return Asset(
        id=aid,
        book_id="book1",
        status=AssetStatus.APPROVED,
        type=AssetType.PHOTO,
        file_path=f"{aid}.jpg",
        metadata=meta,
    )


def test_classify_stop_kind_basic():
    assert _classify_stop_kind(1000, 0.5) == "travel"
    assert _classify_stop_kind(10, 5.0) == "travel"
    assert _classify_stop_kind(10, 1.0) == "local"


@patch("services.itinerary.reverse_geocode_label")
@patch("services.itinerary._build_segment_summaries")
@patch("services.itinerary._build_segments_for_day")
def test_build_book_itinerary_sets_stop_kinds(mock_segments, mock_summaries, mock_geocode):
    mock_segments.return_value = ([{"asset_ids": ["a1"]}, {"asset_ids": ["a2"]}], 0, 0, 0, 0)
    mock_summaries.return_value = [
        {"index": 1, "distance_km": 1000.0, "duration_hours": 5.0, "polyline": [(41.0, -87.0)]},
        {"index": 2, "distance_km": 10.0, "duration_hours": 1.0, "polyline": [(41.1, -87.1)]},
    ]
    mock_geocode.return_value = PlaceLabel(city="Chicago", state="Illinois", country="United States")

    ts = datetime(2025, 8, 1, 12, 0, 0)
    assets = [_asset("a1", ts, 41.0, -87.0), _asset("a2", ts, 41.1, -87.1)]
    entry1 = ManifestEntry(asset_id="a1", timestamp=ts)
    entry2 = ManifestEntry(asset_id="a2", timestamp=ts)
    day = Day(index=0, date=ts, events=[Event(index=0, entries=[entry1, entry2])])
    book = Book(id="book1", title="Test", size=BookSize.SQUARE_8)

    days = build_book_itinerary(book, [day], assets)

    assert len(days) == 1
    kinds = {s.kind for s in days[0].stops}
    assert "travel" in kinds
    assert "local" in kinds
