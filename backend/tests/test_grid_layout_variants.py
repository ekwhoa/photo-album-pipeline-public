from domain.models import LayoutRect, Page, PageType, RenderContext, BookSize
from services.book_planner import choose_grid_layout_variant
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
