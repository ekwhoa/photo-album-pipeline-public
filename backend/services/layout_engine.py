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
        y_mm=height * 0.65,
        width_mm=width - 2 * margin,
        height_mm=20,
        text=title,
        font_size=24,
        color=theme.cover_text_color,
    ))
    
    # Subtitle
    subtitle = page.payload.get("subtitle", "")
    if subtitle:
        elements.append(LayoutRect(
            x_mm=margin,
            y_mm=height * 0.65 + 25,
            width_mm=width - 2 * margin,
            height_mm=12,
            text=subtitle,
            font_size=12,
            color=theme.cover_text_color,
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

@register_layout(PageType.MAP_ROUTE)
def layout_map_route(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for map route page layout."""
    raise NotImplementedError("Map route layout not yet implemented")


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
    """Placeholder for trip summary layout."""
    raise NotImplementedError("Trip summary layout not yet implemented")


@register_layout(PageType.ITINERARY)
def layout_itinerary(page: Page, context: RenderContext) -> PageLayout:
    """Placeholder for itinerary layout."""
    raise NotImplementedError("Itinerary layout not yet implemented")
