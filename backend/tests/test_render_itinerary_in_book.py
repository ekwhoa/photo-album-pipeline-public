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
    Page,
    PageType,
    RenderContext,
    Theme,
)
from services.render_pdf import render_book_to_html
from services.layout_engine import compute_all_layouts


def _asset(aid: str, ts: datetime, lat: float, lon: float) -> Asset:
    meta = AssetMetadata(taken_at=ts, gps_lat=lat, gps_lon=lon)
    return Asset(
        id=aid,
        book_id="book1",
        status=AssetStatus.APPROVED,
        type=AssetType.PHOTO,
        file_path=f"{aid}.jpg",
        metadata=meta,
    )


@patch("services.render_pdf.build_book_itinerary")
def test_itinerary_section_appended(mock_itinerary):
    # Mock itinerary days
    class MockLoc:
        def __init__(self, val):
            self.location_short = val
            self.location_full = val

    class MockDay:
        def __init__(self):
            self.day_index = 1
            self.date_iso = "2025-08-01"
            self.photos_count = 2
            self.segments_total_distance_km = 12.3
            self.segments_total_duration_hours = 3.4
            self.locations = [MockLoc("Chicago, Illinois")]
            self.stops = [
                type(
                    "Stop",
                    (),
                    {
                        "segment_index": 1,
                        "distance_km": 5.6,
                        "duration_hours": 1.2,
                        "location_short": "Chicago, Illinois",
                        "location_full": "Chicago, Illinois",
                        "kind": "travel",
                    },
                )()
            ]

    mock_itinerary.return_value = [MockDay()]

    ts = datetime(2025, 8, 1, 12, 0, 0)
    assets = [_asset("a1", ts, 41.0, -87.0)]
    page = Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Test", "subtitle": ""})
    book = Book(id="book1", title="Test", size=BookSize.SQUARE_8, pages=[page])
    context = RenderContext(book_size=BookSize.SQUARE_8, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)

    html = render_book_to_html(book, layouts, {a.id: a for a in assets}, context, media_root=".")
    assert "itinerary (beta)" in html.lower()
    assert "Day 1" in html
    assert "Chicago, Illinois" in html
    assert "Travel segment" in html
