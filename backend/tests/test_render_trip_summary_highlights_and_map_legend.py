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


def test_trip_summary_highlights_and_map_legend_render_html(tmp_path):
    assets = {
        "a1": Asset(
            id="a1",
            book_id="b-render",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="tests/fixtures/images/landscape.jpg",
            thumbnail_path="tests/fixtures/images/landscape_thumb.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 1)),
        ),
        "a2": Asset(
            id="a2",
            book_id="b-render",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="tests/fixtures/images/portrait.jpg",
            thumbnail_path="tests/fixtures/images/portrait_thumb.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 2)),
        ),
        "a3": Asset(
            id="a3",
            book_id="b-render",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="tests/fixtures/images/face_1.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 3)),
        ),
    }

    book = Book(id="b-render", title="Render Test", size=BookSize.SQUARE_8)
    book.pages = [
        Page(index=0, page_type=PageType.TRIP_SUMMARY, payload={"title": "Trip summary", "subtitle": "Test"}),
        Page(index=1, page_type=PageType.MAP_ROUTE, payload={"segments": []}),
    ]
    book.photobook_spec_v1 = {
        "trip_highlights": [
            {"asset_id": "a1", "label": None},
            {"asset_id": "a2", "label": None},
        ],
        "stops_for_legend": [
            {"label": "Stop 1", "lat": 0.0, "lon": 0.0, "photo_count": 10},
            {"label": "Stop 2", "lat": 1.0, "lon": 1.0, "photo_count": 5},
        ],
    }

    context = RenderContext(book_size=book.size, theme=Theme())
    layouts = compute_all_layouts(book.get_all_pages(), context, book_id=book.id)

    html = render_book_to_html(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root=str(tmp_path),
        mode="web",
        media_base_url="/media",
    )
    assert "trip-highlights" in html
    assert "Stop 1" in html and "Stop 2" in html
    assert html.count('class="map-legend-badge"') >= 2
    assert ">1</span>" in html and ">2</span>" in html
    # should render highlight images
    assert html.count("trip-highlight-thumb") >= 2
    assert "landscape_thumb.jpg" in html and "portrait_thumb.jpg" in html
