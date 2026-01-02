from unittest.mock import patch

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
    assert "Day 1" in html
    assert "+1 more days" in html
