"""
Book planner service.

Takes organized days/events and creates a Book structure with
front cover, trip summary, interior pages, and back cover.
"""
from typing import Any, Dict, List, Optional, Tuple
from datetime import date
from domain.models import (
    Asset, Book, BookSize, Day, Page, PageType
)
from services.map_route_renderer import render_route_map


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
    
    # Compute EXIF-based date range for subtitles
    _, _, exif_subtitle = compute_exif_date_range(assets)
    fallback_subtitle = _generate_subtitle(days) or f"{len(days)} days • {len(assets)} photos"
    cover_subtitle = exif_subtitle or fallback_subtitle

    # Create front cover
    front_cover = Page(
        index=0,
        page_type=PageType.FRONT_COVER,
        payload={
            "title": title,
            "subtitle": cover_subtitle,
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

    # Map route page (optional, index 2)
    gps_photo_count, distinct_locations = compute_gps_stats(assets)
    asset_lookup = {a.id: a for a in assets}
    route_points = []
    for asset_id in all_asset_ids:
        asset = asset_lookup.get(asset_id)
        if asset and asset.metadata and asset.metadata.gps_lat is not None and asset.metadata.gps_lon is not None:
            route_points.append((asset.metadata.gps_lat, asset.metadata.gps_lon))
    map_route_page: Optional[Page] = None
    interior_start_index = 2
    route_image_rel = ""
    route_image_abs = ""
    if gps_photo_count > 0 and route_points:
        route_image_rel, route_image_abs = render_route_map(book_id, route_points)

    if gps_photo_count > 0:
        map_route_page = Page(
            index=2,
            page_type=PageType.MAP_ROUTE,
            payload={
                "gps_photo_count": gps_photo_count,
                "distinct_locations": distinct_locations,
                "route_image_path": route_image_rel,
                "route_image_abs_path": route_image_abs,
            },
        )
        interior_start_index = 3
    
    # Deduplicate near-identical shots per day (order preserved)
    deduped_ids, dedup_summary = _dedupe_assets_by_day(all_asset_ids, asset_lookup)

    # Create interior photo grid pages
    photos_per_page = PHOTOS_PER_PAGE.get(size.value, 4)
    interior_pages = _create_photo_grid_pages(deduped_ids, photos_per_page, asset_lookup, start_index=interior_start_index)
    
    # Combine trip summary + optional map route + photo grids
    all_interior_pages = [trip_summary]
    if map_route_page:
        all_interior_pages.append(map_route_page)
    all_interior_pages.extend(interior_pages)

    # Debug accounting
    approved_ids = set(all_asset_ids)
    used_ids = set(deduped_ids)
    hidden_ids = set()
    for cluster in dedup_summary.get("clusters", []):
        hidden_ids.update(cluster.get("hidden_asset_ids", []))
        hero = cluster.get("kept_asset_id")
        if hero:
            used_ids.add(hero)
    # Include cover hero if it comes from approved assets
    if hero_asset_id:
        used_ids.add(hero_asset_id)
    unused_ids = sorted(list(approved_ids - used_ids - hidden_ids))

    print(
        f"[planner] Assets: approved={len(assets)} used={len(deduped_ids)} "
        f"auto_hidden_duplicates={dedup_summary.get('dropped', 0)} "
        f"unused={len(unused_ids)}"
    )
    
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
        auto_hidden_duplicate_clusters=dedup_summary.get("clusters", []),
        unused_approved_asset_ids=unused_ids,
    )


def _generate_subtitle(days: List[Day]) -> str:
    """Generate a subtitle from Day dates (fallback only)."""
    if not days:
        return ""
    
    dates = [d.date for d in days if d.date]
    if not dates:
        return ""
    
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


def compute_exif_date_range(assets: List[Asset]) -> Tuple[Optional[date], Optional[date], Optional[str]]:
    """
    Compute date range from EXIF taken_at only.
    
    Returns:
        (start_date, end_date, subtitle_text) where subtitle_text is human-readable.
        Returns (None, None, None) if no EXIF timestamps are present.
    """
    exif_dates = [
        a.metadata.taken_at.date()
        for a in assets
        if a.metadata and a.metadata.taken_at is not None
    ]
    if not exif_dates:
        return None, None, None
    
    start = min(exif_dates)
    end = max(exif_dates)
    
    if start == end:
        subtitle = start.strftime("%B %d, %Y")
    elif start.year == end.year:
        if start.month == end.month:
            subtitle = f"{start.strftime('%B %d')} - {end.strftime('%d, %Y')}"
        else:
            subtitle = f"{start.strftime('%B %d')} - {end.strftime('%B %d, %Y')}"
    else:
        subtitle = f"{start.strftime('%B %Y')} - {end.strftime('%B %Y')}"
    
    return start, end, subtitle


def compute_gps_stats(assets: List[Asset]) -> Tuple[int, int]:
    """
    Compute GPS-related stats from assets.
    
    Returns:
        (gps_photo_count, distinct_locations)
        distinct_locations is based on rounded lat/lon pairs to approximate unique spots.
    """
    gps_assets = [
        (a.metadata.gps_lat, a.metadata.gps_lon)
        for a in assets
        if a.metadata and a.metadata.gps_lat is not None and a.metadata.gps_lon is not None
    ]
    gps_photo_count = len(gps_assets)
    distinct_set = set()
    for lat, lon in gps_assets:
        # Round to 3 decimal places (~100m) for uniqueness approximation
        rounded = (round(lat, 3), round(lon, 3))
        distinct_set.add(rounded)
    return gps_photo_count, len(distinct_set)


def _dedupe_assets_by_day(asset_ids: List[str], asset_lookup: Dict[str, Asset]) -> Tuple[List[str], Dict[str, Any]]:
    """Remove near-duplicates per day while preserving chronological order."""
    kept: List[str] = []
    dropped = 0
    clusters: List[Dict[str, Any]] = []

    # Group asset IDs by day index based on appearance order in the original list
    # Day boundaries are assumed to be reflected in order of asset_ids passed in.
    # We simply walk in order and apply per-day clustering until taken_at day changes.
    current_day_assets: List[str] = []
    current_day_date: Optional[date] = None

    def flush_day(ids: List[str]):
        nonlocal dropped, clusters
        # Within a day, sort by taken_at (fallback to as-is) and cluster
        sorted_ids = sorted(
            ids,
            key=lambda aid: asset_lookup.get(aid).metadata.taken_at if asset_lookup.get(aid) and asset_lookup.get(aid).metadata else None,
        )
        clustered_keep: List[str] = []
        local_clusters: List[List[str]] = []

        def is_near_duplicate(a_id: str, b_id: str) -> bool:
            a = asset_lookup.get(a_id)
            b = asset_lookup.get(b_id)
            if not a or not b or not a.metadata or not b.metadata:
                return False
            if not (a.metadata.taken_at and b.metadata.taken_at):
                return False
            delta = abs((a.metadata.taken_at - b.metadata.taken_at).total_seconds())
            if delta > 10:
                return False
            if not (a.metadata.width and a.metadata.height and b.metadata.width and b.metadata.height):
                return False
            same_orientation = (a.metadata.width >= a.metadata.height) == (b.metadata.width >= b.metadata.height)
            max_dim = max(a.metadata.width, a.metadata.height, b.metadata.width, b.metadata.height)
            dim_diff = max(abs(a.metadata.width - b.metadata.width), abs(a.metadata.height - b.metadata.height))
            if same_orientation and dim_diff <= max(64, 0.05 * max_dim):
                return True
            return False

        current_cluster: List[str] = []
        for aid in sorted_ids:
            if not current_cluster:
                current_cluster = [aid]
                continue
            if is_near_duplicate(aid, current_cluster[-1]):
                current_cluster.append(aid)
            else:
                local_clusters.append(current_cluster)
                current_cluster = [aid]
        if current_cluster:
            local_clusters.append(current_cluster)

        cluster_counter = 0
        for cluster in local_clusters:
            if len(cluster) == 1:
                clustered_keep.append(cluster[0])
                continue
            cluster_counter += 1
            hero = _select_cluster_hero(cluster, asset_lookup)
            clustered_keep.append(hero)
            hidden = [aid for aid in cluster if aid != hero]
            dropped += len(hidden)
            clusters.append(
                {
                    "cluster_id": f"day_{current_day_date}_{cluster_counter}",
                    "kept_asset_id": hero,
                    "hidden_asset_ids": hidden,
                }
            )

        kept.extend(clustered_keep)

    for aid in asset_ids:
        asset = asset_lookup.get(aid)
        if not asset or not asset.metadata or not asset.metadata.taken_at:
            # If no timestamp, just treat as current day continuation
            current_day_assets.append(aid)
            continue
        aid_date = asset.metadata.taken_at.date()
        if current_day_date is None:
            current_day_date = aid_date
        if aid_date != current_day_date:
            flush_day(current_day_assets)
            current_day_assets = [aid]
            current_day_date = aid_date
        else:
            current_day_assets.append(aid)

    if current_day_assets:
        flush_day(current_day_assets)

    return kept, {"dropped": dropped, "clusters": clusters}


def _select_cluster_hero(cluster: List[str], asset_lookup: Dict[str, Asset]) -> str:
    """Pick a representative asset from a near-duplicate cluster."""
    def score(aid: str) -> Tuple[int, float]:
        asset = asset_lookup.get(aid)
        if not asset or not asset.metadata:
            return 0, 0.0
        w = asset.metadata.width or 0
        h = asset.metadata.height or 0
        area = w * h
        ts = asset.metadata.taken_at.timestamp() if asset.metadata.taken_at else 0.0
        return area, ts

    return max(cluster, key=score)


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
    
    # Use EXIF-based range first; fallback to simple stats
    start_date_exif, end_date_exif, subtitle_exif = compute_exif_date_range(assets)
    subtitle = subtitle_exif or f"{day_count} days • {photo_count} photos"
    start_date = start_date_exif.isoformat() if start_date_exif else None
    end_date = end_date_exif.isoformat() if end_date_exif else None
    
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


def _create_photo_grid_pages(asset_ids: List[str], photos_per_page: int, asset_lookup: Dict[str, Asset], start_index: int = 1) -> List[Page]:
    """Create photo grid pages from asset IDs in order (no reordering)."""
    pages: List[Page] = []

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
        print(f"[planner] Photo grid page {start_index + len(pages) - 1} assets={batch}")

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
