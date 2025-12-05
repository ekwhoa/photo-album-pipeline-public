"""
Book planner service.

Takes organized days/events and creates a Book structure with
front cover, trip summary, interior pages, and back cover.
"""
from typing import List, Optional
from domain.models import (
    Asset, Book, BookSize, Day, Page, PageType
)


# Configuration for photo grid layouts
PHOTOS_PER_PAGE = {
    "8x8": 4,
    "10x10": 6,
    "8x10": 4,
    "10x8": 6,
    "11x14": 9,
}


def plan_book(
    book_id: str,
    title: str,
    size: BookSize,
    days: List[Day],
    assets: List[Asset],
) -> Book:
    """
    Plan a book from organized days/events.
    
    Creates:
    1. Front cover with title and hero image
    2. Trip summary page with stats
    3. Interior photo grid pages
    4. Back cover
    
    Args:
        book_id: ID for the book
        title: Book title
        size: Book size
        days: Organized days from timeline service
        assets: All approved assets (for hero selection)
    
    Returns:
        Book with planned pages
    """
    # Collect all asset IDs in order
    all_asset_ids = []
    for day in days:
        for entry in day.all_entries:
            all_asset_ids.append(entry.asset_id)
    
    # Select hero asset for cover (first asset or None)
    hero_asset_id = all_asset_ids[0] if all_asset_ids else None
    
    # Create front cover
    front_cover = Page(
        index=0,
        page_type=PageType.FRONT_COVER,
        payload={
            "title": title,
            "subtitle": _generate_subtitle(days),
            "hero_asset_id": hero_asset_id,
        },
    )
    
    # Create trip summary page (index 1)
    trip_summary = _create_trip_summary_page(
        title=title,
        days=days,
        assets=assets,
        index=1,
    )
    
    # Create interior photo grid pages (starting at index 2)
    photos_per_page = PHOTOS_PER_PAGE.get(size.value, 4)
    interior_pages = _create_photo_grid_pages(all_asset_ids, photos_per_page, start_index=2)
    
    # Combine trip summary + photo grids
    all_interior_pages = [trip_summary] + interior_pages
    
    # Create back cover (last page)
    back_cover = Page(
        index=len(all_interior_pages) + 1,
        page_type=PageType.BACK_COVER,
        payload={
            "text": f"© {title}",
            "photo_count": len(all_asset_ids),
        },
    )
    
    return Book(
        id=book_id,
        title=title,
        size=size,
        front_cover=front_cover,
        pages=all_interior_pages,
        back_cover=back_cover,
    )


def _generate_subtitle(days: List[Day]) -> str:
    """Generate a subtitle from the date range."""
    if not days:
        return ""
    
    dates = [d.date for d in days if d.date]
    if not dates:
        return f"{len(days)} days"
    
    start = min(dates)
    end = max(dates)
    
    if start == end:
        return start.strftime("%B %d, %Y")
    elif start.year == end.year:
        if start.month == end.month:
            return f"{start.strftime('%B %d')} - {end.strftime('%d, %Y')}"
        else:
            return f"{start.strftime('%B %d')} - {end.strftime('%B %d, %Y')}"
    else:
        return f"{start.strftime('%B %Y')} - {end.strftime('%B %Y')}"


def _create_trip_summary_page(
    title: str,
    days: List[Day],
    assets: List[Asset],
    index: int,
) -> Page:
    """Create a trip summary page with stats."""
    # Calculate stats
    day_count = len(days)
    photo_count = len(assets)
    event_count = sum(len(day.events) for day in days)
    
    # Count locations with GPS
    locations_count = sum(
        1 for a in assets 
        if a.metadata and a.metadata.gps_lat is not None and a.metadata.gps_lon is not None
    )
    
    # Get date range
    dates = [d.date for d in days if d.date]
    start_date = min(dates).isoformat() if dates else None
    end_date = max(dates).isoformat() if dates else None
    
    # Generate subtitle
    subtitle = _generate_subtitle(days)
    
    return Page(
        index=index,
        page_type=PageType.TRIP_SUMMARY,
        payload={
            "title": title,
            "subtitle": subtitle,
            "day_count": day_count,
            "photo_count": photo_count,
            "event_count": event_count,
            "locations_count": locations_count if locations_count > 0 else None,
            "start_date": start_date,
            "end_date": end_date,
        },
    )


def _create_photo_grid_pages(asset_ids: List[str], photos_per_page: int, start_index: int = 1) -> List[Page]:
    """Create photo grid pages from asset IDs."""
    pages = []
    
    for i in range(0, len(asset_ids), photos_per_page):
        batch = asset_ids[i:i + photos_per_page]
        page = Page(
            index=start_index + len(pages),
            page_type=PageType.PHOTO_GRID,
            payload={
                "asset_ids": batch,
                "layout": _select_grid_layout(len(batch), photos_per_page),
            },
        )
        pages.append(page)
    
    return pages


def _select_grid_layout(photo_count: int, max_photos: int) -> str:
    """
    Select a grid layout based on photo count.
    
    Returns a layout identifier that the layout engine will use.
    """
    if photo_count == 1:
        return "single"
    elif photo_count == 2:
        return "two_column"
    elif photo_count <= 4:
        return "grid_2x2"
    elif photo_count <= 6:
        return "grid_2x3"
    else:
        return "grid_3x3"


# ============================================
# Future: Advanced planning
# ============================================

def plan_with_special_pages(
    book_id: str,
    title: str,
    size: BookSize,
    days: List[Day],
    assets: List[Asset],
    include_map: bool = False,
    include_spotlights: bool = False,
) -> Book:
    """
    Placeholder for planning with special page types.
    
    Future implementation would:
    - Add map pages showing route
    - Add spotlight pages for best photos
    - Add trip summary page
    """
    # For now, delegate to basic planner
    return plan_book(book_id, title, size, days, assets)
