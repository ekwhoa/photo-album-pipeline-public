"""
Layout engine service.

Computes the visual layout of each page based on its type.
Uses a registry pattern to allow easy addition of new page types.
"""
from typing import Callable, Dict, List, Optional
from domain.models import (
    LayoutRect, Page, PageLayout, PageType, RenderContext
)


# Type alias for layout functions
LayoutFunction = Callable[[Page, RenderContext], PageLayout]


# Registry of layout functions by page type
_layout_registry: Dict[PageType, LayoutFunction] = {}


def register_layout(page_type: PageType):
    """Decorator to register a layout function for a page type."""
    def decorator(func: LayoutFunction) -> LayoutFunction:
        _layout_registry[page_type] = func
        return func
    return decorator


def compute_layout(page: Page, context: RenderContext) -> PageLayout:
    """
    Compute the layout for a page.
    
    Args:
        page: The page to layout
        context: Render context with size and theme info
    
    Returns:
        PageLayout with positioned elements
    
    Raises:
        ValueError: If no layout is registered for the page type
    """
    layout_func = _layout_registry.get(page.page_type)
    if not layout_func:
        raise ValueError(f"No layout registered for page type: {page.page_type}")
    return layout_func(page, context)


def compute_all_layouts(pages: List[Page], context: RenderContext) -> List[PageLayout]:
    """Compute layouts for all pages in a book."""
    return [compute_layout(page, context) for page in pages]


# ============================================
# Layout implementations
# ============================================

@register_layout(PageType.FRONT_COVER)
def layout_front_cover(page: Page, context: RenderContext) -> PageLayout:
    """
    Layout for front cover.
    
    Structure:
    - Full-bleed hero image (or solid background)
    - Title text centered
    - Subtitle below title
    """
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm
    
    elements = []
    
    # Hero image (full bleed)
    hero_id = page.payload.get("hero_asset_id")
    if hero_id:
        elements.append(LayoutRect(
            x_mm=0,
            y_mm=0,
            width_mm=width,
            height_mm=height,
            asset_id=hero_id,
        ))
    
    # Semi-transparent overlay for text readability
    elements.append(LayoutRect(
        x_mm=0,
        y_mm=height * 0.5,
        width_mm=width,
        height_mm=height * 0.5,
        color="rgba(0, 0, 0, 0.4)",
    ))
    
    # Title
    title = page.payload.get("title", "")
    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=margin + 30,
        width_mm=width - 2 * margin,
        height_mm=22,
        text=title,
        font_size=28,
        color=theme.cover_text_color,
    ))
    
    # Subtitle
    subtitle = page.payload.get("subtitle", "")
    if subtitle:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=margin + 55,
            width_mm=width - 2 * margin,
            height_mm=14,
            text=subtitle,
            font_size=14,
            color=theme.cover_text_color,
        ))
    
    # Accent rule
    elements.append(LayoutRect(
        x_mm=margin + 20,
        y_mm=margin + 70,
        width_mm=width - 2 * margin - 40,
        height_mm=1,
        color="rgba(255, 255, 255, 0.6)",
    ))
    
    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.cover_background_color,
        elements=elements,
    )


@register_layout(PageType.PHOTO_GRID)
def layout_photo_grid(page: Page, context: RenderContext) -> PageLayout:
    """
    Layout for photo grid pages.
    
    Arranges photos in a grid based on the layout type in payload.
    """
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm
    gap = theme.photo_gap_mm
    
    asset_ids = page.payload.get("asset_ids", [])
    layout_type = page.payload.get("layout", "grid_2x2")
    
    elements = []
    
    # Calculate content area
    content_width = width - 2 * margin
    content_height = height - 2 * margin
    
    if layout_type == "single":
        # Single photo, centered
        if asset_ids:
            elements.append(LayoutRect(
                x_mm=margin,
                y_mm=margin,
                width_mm=content_width,
                height_mm=content_height,
                asset_id=asset_ids[0],
            ))
    
    elif layout_type == "two_column":
        # Two photos side by side
        photo_width = (content_width - gap) / 2
        for i, asset_id in enumerate(asset_ids[:2]):
            elements.append(LayoutRect(
                x_mm=margin + i * (photo_width + gap),
                y_mm=margin,
                width_mm=photo_width,
                height_mm=content_height,
                asset_id=asset_id,
            ))
    
    elif layout_type == "grid_2x2":
        # 2x2 grid
        photo_width = (content_width - gap) / 2
        photo_height = (content_height - gap) / 2
        for i, asset_id in enumerate(asset_ids[:4]):
            row = i // 2
            col = i % 2
            elements.append(LayoutRect(
                x_mm=margin + col * (photo_width + gap),
                y_mm=margin + row * (photo_height + gap),
                width_mm=photo_width,
                height_mm=photo_height,
                asset_id=asset_id,
            ))
    
    elif layout_type == "grid_2x3":
        # 2 columns, 3 rows
        photo_width = (content_width - gap) / 2
        photo_height = (content_height - 2 * gap) / 3
        for i, asset_id in enumerate(asset_ids[:6]):
            row = i // 2
            col = i % 2
            elements.append(LayoutRect(
                x_mm=margin + col * (photo_width + gap),
                y_mm=margin + row * (photo_height + gap),
                width_mm=photo_width,
                height_mm=photo_height,
                asset_id=asset_id,
            ))
    
    elif layout_type == "grid_3x3":
        # 3x3 grid
        photo_width = (content_width - 2 * gap) / 3
        photo_height = (content_height - 2 * gap) / 3
        for i, asset_id in enumerate(asset_ids[:9]):
            row = i // 3
            col = i % 3
            elements.append(LayoutRect(
                x_mm=margin + col * (photo_width + gap),
                y_mm=margin + row * (photo_height + gap),
                width_mm=photo_width,
                height_mm=photo_height,
                asset_id=asset_id,
            ))
    
    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.background_color,
        elements=elements,
    )


@register_layout(PageType.BACK_COVER)
def layout_back_cover(page: Page, context: RenderContext) -> PageLayout:
    """
    Layout for back cover.
    
    Simple layout with centered text.
    """
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm
    
    elements = []
    
    # Copyright text
    text = page.payload.get("text", "")
    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=height - margin - 10,
        width_mm=width - 2 * margin,
        height_mm=10,
        text=text,
        font_size=10,
        color=theme.secondary_color,
    ))
    
    # Photo count
    photo_count = page.payload.get("photo_count", 0)
    if photo_count:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=height - margin - 25,
            width_mm=width - 2 * margin,
            height_mm=10,
            text=f"{photo_count} photos",
            font_size=10,
            color=theme.secondary_color,
        ))
    
    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.background_color,
        elements=elements,
    )


# ============================================
# Future page type placeholders
# ============================================

# These are defined but raise NotImplementedError until implemented

@register_layout(PageType.DAY_INTRO)
def layout_day_intro(page: Page, context: RenderContext) -> PageLayout:
    """Simple centered day intro page."""
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm

    elements: List[LayoutRect] = []
    day_index = page.payload.get("day_index")
    day_date = page.payload.get("display_date") or page.payload.get("day_date") or "Day"
    photo_count = page.payload.get("day_photo_count")

    header_text = f"Day {day_index}" if day_index else "Day"
    footer_text = f"{photo_count} photos" if photo_count is not None else ""

    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=height * 0.35,
        width_mm=width - 2 * margin,
        height_mm=12,
        text=header_text,
        font_size=12,
        color=theme.secondary_color,
    ))
    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=height * 0.42,
        width_mm=width - 2 * margin,
        height_mm=18,
        text=day_date,
        font_size=24,
        color=theme.primary_color,
    ))
    if footer_text:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=height * 0.52,
            width_mm=width - 2 * margin,
            height_mm=10,
            text=footer_text,
            font_size=12,
            color=theme.secondary_color,
        ))

    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.background_color,
        elements=elements,
    )


@register_layout(PageType.MAP_ROUTE)
def layout_map_route(page: Page, context: RenderContext) -> PageLayout:
    """Text-only layout for map route stats."""
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm

    gps_photo_count = page.payload.get("gps_photo_count") or 0
    distinct_locations = page.payload.get("distinct_locations") or 0
    route_image_path = page.payload.get("route_image_abs_path") or ""
    route_image_url = page.payload.get("route_image_path") or ""

    elements = []

    # Title
    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=margin + 15,
        width_mm=width - 2 * margin,
        height_mm=20,
        text="Trip Route",
        font_size=26,
        color=theme.primary_color,
    ))

    # Image area if available
    if route_image_path or route_image_url:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=margin + 40,
            width_mm=width - 2 * margin,
            height_mm=height * 0.55,
            image_path=route_image_path,
            image_url=f"/static/{route_image_url}" if route_image_url else None,
        ))

    # Summary lines
    summary_lines = [
        f"Photos with location: {gps_photo_count}",
        f"Approximate unique spots: {distinct_locations}",
    ]

    start_y = (margin + 40 + height * 0.55 + 10) if (route_image_path or route_image_url) else (margin + 55)
    line_height = 14
    for i, line in enumerate(summary_lines):
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=start_y + i * (line_height + 4),
            width_mm=width - 2 * margin,
            height_mm=line_height,
            text=line,
            font_size=14,
            color=theme.secondary_color,
        ))

    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.background_color,
        elements=elements,
    )


@register_layout(PageType.SPOTLIGHT)
def layout_spotlight(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for spotlight page layout."""
    raise NotImplementedError("Spotlight layout not yet implemented")


@register_layout(PageType.POSTCARD_COVER)
def layout_postcard_cover(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for postcard cover layout."""
    raise NotImplementedError("Postcard cover layout not yet implemented")


@register_layout(PageType.PHOTOBOOTH_STRIP)
def layout_photobooth_strip(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for photobooth strip layout."""
    raise NotImplementedError("Photobooth strip layout not yet implemented")


@register_layout(PageType.TRIP_SUMMARY)
def layout_trip_summary(page: Page, context: RenderContext) -> PageLayout:
    """
    Layout for trip summary page.
    
    Displays book title, date range, and trip statistics.
    """
    theme = context.theme
    width = context.page_width_mm
    height = context.page_height_mm
    margin = theme.page_margin_mm
    
    elements = []
    
    # Title (centered, near top)
    title = page.payload.get("title", "Trip Summary")
    elements.append(LayoutRect(
        x_mm=margin,
        y_mm=margin + 20,
        width_mm=width - 2 * margin,
        height_mm=20,
        text=title,
        font_size=28,
        color=theme.primary_color,
    ))
    
    # Subtitle / date range
    subtitle = page.payload.get("subtitle", "")
    if subtitle:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=margin + 50,
            width_mm=width - 2 * margin,
            height_mm=14,
            text=subtitle,
            font_size=14,
            color=theme.secondary_color,
        ))
    
    # Stats section (centered vertically)
    stats_y = height * 0.4
    line_height = 16
    
    day_count = page.payload.get("day_count", 0)
    photo_count = page.payload.get("photo_count", 0)
    event_count = page.payload.get("event_count", 0)
    locations_count = page.payload.get("locations_count")
    
    stats_lines = [
        f"Days: {day_count}",
        f"Photos: {photo_count}",
        f"Events: {event_count}",
    ]
    
    if locations_count:
        stats_lines.append(f"Locations: {locations_count}")
    
    for i, line in enumerate(stats_lines):
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=stats_y + i * line_height,
            width_mm=width - 2 * margin,
            height_mm=12,
            text=line,
            font_size=16,
            color=theme.primary_color,
        ))
    
    return PageLayout(
        page_index=page.index,
        page_type=page.page_type,
        background_color=theme.background_color,
        elements=elements,
    )


@register_layout(PageType.ITINERARY)
def layout_itinerary(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for itinerary layout."""
    raise NotImplementedError("Itinerary layout not yet implemented")
