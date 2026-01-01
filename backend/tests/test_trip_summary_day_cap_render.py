from datetime import datetime

from domain.models import (
    Asset,
    AssetMetadata,
    AssetStatus,
    AssetType,
    Book,
    BookSize,
    Page,
    PageType,
)
from services.layout_engine import compute_all_layouts
from domain.models import RenderContext, Theme
from services.render_pdf import render_book_to_html


def test_trip_summary_day_list_cap(monkeypatch):
    assets = {}
    book = Book(id="b-daycap", title="Cap Test", size=BookSize.SQUARE_8)
    # Build itinerary_days payload via placeholders on layout
    # We attach 6 dummy days to trigger cap.
    itinerary_days = []
    for i in range(6):
        class DayObj:
            day_index = i + 1
            date_iso = datetime(2025, 1, i + 1).date().isoformat()
            locations = []
            stops = [1]
            photos_count = 3
            segments_total_distance_km = 0.0
            segments_total_duration_hours = 0.0
        itinerary_days.append(DayObj())

    book.pages = [Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": "Test"})]
    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)
    monkeypatch.setattr("services.render_pdf.build_book_itinerary", lambda *args, **kwargs: itinerary_days)
    monkeypatch.setattr("services.render_pdf.build_place_candidates", lambda *args, **kwargs: [])

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root="",
        mode="pdf",
        media_base_url="/media",
    )

    # PDF mode cap should render only 1 day title and show remaining
    assert html.count('class="trip-summary-day-title"') == 1
    assert "+ 5 more days" in html


def test_trip_summary_day_list_no_cap_when_small(monkeypatch):
    assets = {}
    book = Book(id="b-daycap2", title="Cap Test", size=BookSize.SQUARE_8)
    itinerary_days = []
    for i in range(1):
        class DayObj:
            day_index = i + 1
            date_iso = datetime(2025, 1, i + 1).date().isoformat()
            locations = []
            stops = [1]
            photos_count = 3
            segments_total_distance_km = 0.0
            segments_total_duration_hours = 0.0
        itinerary_days.append(DayObj())

    book.pages = [Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": "Test"})]
    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)
    monkeypatch.setattr("services.render_pdf.build_book_itinerary", lambda *args, **kwargs: itinerary_days)
    monkeypatch.setattr("services.render_pdf.build_place_candidates", lambda *args, **kwargs: [])

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root="",
        mode="pdf",
        media_base_url="/media",
    )

    assert html.count('class="trip-summary-day-title"') == 1
    assert "more days" not in html
