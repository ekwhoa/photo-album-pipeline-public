from domain.models import LayoutRect, Page, PageType, RenderContext, BookSize
from services.book_planner import choose_grid_layout_variant, _build_photo_pages_with_optional_spread
from services.layout_engine import layout_photo_grid


def test_choose_grid_layout_variant_for_six_photos():
    assert choose_grid_layout_variant(6) == "grid_6_simple"


def test_layout_photo_grid_six_simple_positions():
    page = Page(
        index=0,
        page_type=PageType.PHOTO_GRID,
        payload={
            "asset_ids": [str(i) for i in range(6)],
            "layout": "grid_2x3",
            "layout_variant": "grid_6_simple",
        },
    )
    ctx = RenderContext(book_size=BookSize.SQUARE_8)
    layout = layout_photo_grid(page, ctx)
    assert len(layout.elements) == 6
    xs = sorted({round(elem.x_mm, 2) for elem in layout.elements})
    ys = sorted({round(elem.y_mm, 2) for elem in layout.elements})
    # Expect 3 distinct x positions and 2 distinct y positions (3x2 grid)
    assert len(xs) == 3
    assert len(ys) == 2


def test_plan_day_uses_six_up_when_clean():
    asset_ids = [str(i) for i in range(6)]
    pages, _, _ = _build_photo_pages_with_optional_spread(
        asset_ids,
        photos_per_page=4,
        asset_lookup={},
        start_index=0,
        spread_used=True,  # skip spread handling
    )
    assert len(pages) == 1
    page = pages[0]
    assert page.page_type == PageType.PHOTO_GRID
    assert page.payload.get("layout_variant") == "grid_6_simple"
    assert len(page.payload.get("asset_ids") or []) == 6


def test_plan_day_prefers_six_plus_four_for_ten_photos():
    asset_ids = [str(i) for i in range(10)]
    pages, _, _ = _build_photo_pages_with_optional_spread(
        asset_ids,
        photos_per_page=4,
        asset_lookup={},
        start_index=0,
        spread_used=True,
    )
    sizes = [len(p.payload.get("asset_ids") or []) for p in pages if p.page_type == PageType.PHOTO_GRID]
    assert sizes == [6, 4]
    variants = [p.payload.get("layout_variant") for p in pages if p.page_type == PageType.PHOTO_GRID]
    assert variants[0] == "grid_6_simple"
