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
    grid_pages = [p for p in pages if p.page_type == PageType.PHOTO_GRID]
    sizes = [len(p.payload.get("asset_ids") or []) for p in grid_pages]
    assert sorted(sizes) == [4, 6]
    six_pages = [p for p in grid_pages if len(p.payload.get("asset_ids") or []) == 6]
    assert len(six_pages) == 1
    assert six_pages[0].payload.get("layout_variant") == "grid_6_simple"


def test_plan_day_with_multiple_of_four_photos_uses_only_four_up():
    asset_ids = [str(i) for i in range(24)]
    pages, _, _ = _build_photo_pages_with_optional_spread(
        asset_ids,
        photos_per_page=4,
        asset_lookup={},
        start_index=0,
        spread_used=False,
    )
    grid_pages = [p for p in pages if p.page_type == PageType.PHOTO_GRID]
    sizes = [len(p.payload.get("asset_ids") or []) for p in grid_pages]
    assert all(size == 4 for size in sizes)
    assert all(
        (p.payload.get("layout_variant") or "").startswith("grid_4") or p.payload.get("layout_variant") in (None, "default")
        for p in grid_pages
    )


def test_plan_day_with_fourteen_photos_uses_one_six_up_to_fix_tail():
    asset_ids = [str(i) for i in range(14)]
    pages, _, _ = _build_photo_pages_with_optional_spread(
        asset_ids,
        photos_per_page=4,
        asset_lookup={},
        start_index=0,
        spread_used=False,
    )
    grid_pages = [p for p in pages if p.page_type == PageType.PHOTO_GRID]
    sizes = [len(p.payload.get("asset_ids") or []) for p in grid_pages]
    assert sizes.count(6) == 1
    assert all(size in (4, 6) for size in sizes)
    six_pages = [p for p in grid_pages if len(p.payload.get("asset_ids") or []) == 6]
    assert len(six_pages) == 1
    assert six_pages[0].payload.get("layout_variant") == "grid_6_simple"
