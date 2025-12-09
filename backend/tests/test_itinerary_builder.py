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
from services.itinerary import build_book_itinerary
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


@patch("services.itinerary.reverse_geocode_label")
@patch("services.itinerary._build_segment_summaries")
@patch("services.itinerary._build_segments_for_day")
def test_build_book_itinerary_basic(mock_segments, mock_summaries, mock_geocode):
    # Two fake segments with polylines
    mock_segments.return_value = ([{"asset_ids": ["a1"]}, {"asset_ids": ["a2"]}], 0, 0, 0, 0)
    mock_summaries.return_value = [
        {"index": 1, "distance_km": 10.0, "duration_hours": 1.0, "polyline": [(41.0, -87.0)]},
        {"index": 2, "distance_km": 5.0, "duration_hours": 0.5, "polyline": [(42.0, -88.0)]},
    ]
    mock_geocode.return_value = PlaceLabel(city="Chicago", state="Illinois", country="United States")

    ts = datetime(2025, 8, 1, 12, 0, 0)
    assets = [_asset("a1", ts, 41.0, -87.0), _asset("a2", ts, 42.0, -88.0)]
    entry1 = ManifestEntry(asset_id="a1", timestamp=ts)
    entry2 = ManifestEntry(asset_id="a2", timestamp=ts)
    day = Day(index=0, date=ts, events=[Event(index=0, entries=[entry1, entry2])])
    book = Book(id="book1", title="Test", size=BookSize.SQUARE_8)

    days = build_book_itinerary(book, [day], assets)

    assert len(days) == 1
    d0 = days[0]
    assert d0.day_index == 1
    assert d0.photos_count == 2
    assert d0.segments_total_distance_km == 15.0
    assert d0.segments_total_duration_hours == 1.5
    assert d0.location_short == "Chicago, Illinois"
    assert len(d0.stops) == 2
    assert d0.stops[0].location_short == "Chicago, Illinois"
