from unittest.mock import patch
from datetime import datetime

from domain.models import Asset, AssetMetadata, AssetStatus, AssetType

from domain.models import Book, BookSize, Page, PageType, RenderContext, Theme
from services.layout_engine import compute_all_layouts
from services.render_pdf import render_book_to_html


@patch("services.render_pdf.build_book_itinerary")
def test_trip_route_renders_itinerary_panel(mock_build_itinerary):
    class MockDay:
        def __init__(self, idx: int):
            self.day_index = idx
            self.date_iso = f"2025-01-0{idx}"
            self.photos_count = 0
            self.segments_total_distance_km = 0.0
            self.segments_total_duration_hours = 0.0
            self.location_short = f"City {idx}"
            self.location_full = f"City {idx}, State"
            self.stops = []
            self.locations = []

    itinerary_days = [MockDay(i) for i in range(1, 7)]
    mock_build_itinerary.return_value = itinerary_days

    book = Book(id="book-trip", title="Trip", size=BookSize.SQUARE_8)
    book.pages = [
        Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": ""}),
        Page(index=1, page_type=PageType.MAP_ROUTE, payload={"segments": []}),
    ]

    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets={},
        context=context,
        media_root=".",
        mode="web",
    )

    assert "Trip Itinerary" in html
    assert "Day&nbsp;1" in html
    assert html.count('<span class="trip-route-day-pill') == len(itinerary_days)


@patch("services.render_pdf.build_book_itinerary")
def test_trip_route_itinerary_renders_in_pdf_mode(mock_build_itinerary):
    class MockDay:
        def __init__(self, idx: int):
            self.day_index = idx
            self.date_iso = f"2025-02-0{idx}"
            self.photos_count = 0
            self.segments_total_distance_km = 0.0
            self.segments_total_duration_hours = 0.0
            self.location_short = f"Place {idx}"
            self.location_full = f"Place {idx}, State"
            self.stops = []
            self.locations = []

    itinerary_days = [MockDay(i) for i in range(1, 3)]
    mock_build_itinerary.return_value = itinerary_days

    book = Book(id="book-trip-pdf", title="Trip", size=BookSize.SQUARE_8)
    book.photobook_spec_v1 = {
        "stops_for_legend": [
            {"label": "Alpha", "lat": 0.0, "lon": 0.0, "photo_count": 3, "day_index": 1},
            {"label": "Beta", "lat": 0.1, "lon": 0.1, "photo_count": 2, "day_index": 2},
            {"label": "Gamma", "lat": 0.2, "lon": 0.2, "photo_count": 1, "day_index": 3},
            {"label": "Delta", "lat": 0.3, "lon": 0.3, "photo_count": 1, "day_index": 4},
            {"label": "Epsilon", "lat": 0.4, "lon": 0.4, "photo_count": 1, "day_index": 5},
            {"label": "Zeta", "lat": 0.5, "lon": 0.5, "photo_count": 1, "day_index": 6},
            {"label": "Eta", "lat": 0.6, "lon": 0.6, "photo_count": 1, "day_index": 7},
            {"label": "Theta", "lat": 0.7, "lon": 0.7, "photo_count": 1, "day_index": 8},
        ]
    }
    book.pages = [
        Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": ""}),
        Page(index=1, page_type=PageType.MAP_ROUTE, payload={"segments": []}),
    ]

    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets={},
        context=context,
        media_root=".",
        mode="pdf",
    )

    assert "Trip Itinerary" in html
    assert "Day&nbsp;1" in html
    assert "trip-route-map-wrap" in html
    assert "map-route-canvas" in html
    assert "trip-route-overlay" in html
    assert "map-legend-badge" in html
    assert "page-map-route" in html
    assert "--card-bg" in html
    assert "--trip-route-overlay-width" in html
    assert html.count('<span class="trip-route-day-pill') == len(itinerary_days)
    assert "+2 more stops" in html
    assert 'style="--stop-color:var(--day-2' in html
    assert 'style="--stop-color:var(--day-3' in html
    assert "Pacifico" in html
    assert "var(--day-2" in html


@patch("services.render_pdf.build_book_itinerary")
def test_stop_colors_inferred_from_nearby_assets(mock_build_itinerary):
    class MockDay:
        def __init__(self, idx: int, iso: str):
            self.day_index = idx
            self.date_iso = iso
            self.photos_count = 0
            self.segments_total_distance_km = 0.0
            self.segments_total_duration_hours = 0.0
            self.location_short = f"Place {idx}"
            self.location_full = f"Place {idx}, State"
            self.stops = []
            self.locations = []

    itinerary_days = [MockDay(1, "2025-03-01"), MockDay(2, "2025-03-02")]
    mock_build_itinerary.return_value = itinerary_days

    assets = {
        "a1": Asset(
            id="a1",
            book_id="book-stop-day",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="tests/fixtures/images/landscape.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 3, 1, 12, 0, 0), gps_lat=0.0, gps_lon=0.0),
        ),
        "a2": Asset(
            id="a2",
            book_id="book-stop-day",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="tests/fixtures/images/portrait.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 3, 2, 12, 0, 0), gps_lat=0.1, gps_lon=0.1),
        ),
    }

    book = Book(id="book-stop-day", title="Trip", size=BookSize.SQUARE_8)
    book.photobook_spec_v1 = {
        "stops_for_legend": [
            {"label": "First", "lat": 0.0, "lon": 0.0, "photo_count": 3},
            {"label": "Second", "lat": 0.1, "lon": 0.1, "photo_count": 2},
        ]
    }
    book.pages = [
        Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": ""}),
        Page(index=1, page_type=PageType.MAP_ROUTE, payload={"segments": []}),
    ]

    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root=".",
        mode="pdf",
    )

    assert "map-legend-badge" in html
    assert 'style="--stop-color:var(--day-1' in html
    assert 'style="--stop-color:var(--day-2' in html
