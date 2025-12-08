"""
Book planner service.

Takes organized days/events and creates a Book structure with
front cover, trip summary, interior pages, and back cover.
"""
from typing import Any, Dict, List, Optional, Tuple
from datetime import date, datetime
from dataclasses import dataclass
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

_grid_variant_counter = 0  # tracks per-day usage of special 4-photo variant

# Near-duplicate tuning: be very conservative
HIGH_SIMILARITY_THRESHOLD = 0.92  # only treat as true duplicates when this high
MIN_CLUSTER_SIZE_FOR_AUTO_HIDE = 3  # never auto-hide if only 2 photos

# Day layout profile heuristics (controls full-page bias per day)
@dataclass
class DayLayoutProfile:
    max_full_page_photos: int
    prefer_full_page_for_leftovers: bool


def compute_day_layout_profile(photo_count: int, segment_count: int) -> DayLayoutProfile:
    """
    Compute a simple per-day layout profile based on photos/segments.
    Small days allow more full-page freedom; busy days bias to grids.
    """
    if photo_count <= 12 and segment_count <= 1:
        return DayLayoutProfile(max_full_page_photos=2, prefer_full_page_for_leftovers=True)
    if photo_count <= 40 and segment_count <= 2:
        return DayLayoutProfile(max_full_page_photos=1, prefer_full_page_for_leftovers=False)
    return DayLayoutProfile(max_full_page_photos=1, prefer_full_page_for_leftovers=False)


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

    # Organize deduped ids by day for day intro + grids
    day_asset_sets: List[Tuple[int, Optional[date], List[str]]] = []
    assigned: set[str] = set()
    for idx, day in enumerate(days):
        day_ids = [entry.asset_id for entry in day.all_entries]
        day_set = set(day_ids)
        filtered = [aid for aid in deduped_ids if aid in day_set]
        assigned.update(filtered)
        if filtered:
            day_asset_sets.append((idx + 1, day.date.date() if day.date else None, filtered))
    # Any remaining assets without a day mapping
    remaining = [aid for aid in deduped_ids if aid not in assigned]
    if remaining:
        day_asset_sets.append((len(day_asset_sets) + 1, None, remaining))

    photos_per_page = PHOTOS_PER_PAGE.get(size.value, 4)
    interior_pages: List[Page] = []
    current_index = interior_start_index
    day_intro_pages_count = 0
    spread_used = False
    full_hero_count = 0
    map_route_segments: List[Dict[str, Any]] = []
    for day_index, day_date, day_ids in day_asset_sets:
        day_photo_count = len(day_ids)
        full_page_photos_for_day = 0
        ordered_assets_for_segments = [asset_lookup[aid] for aid in day_ids if aid in asset_lookup]
        ordered_assets_for_segments.sort(
            key=lambda a: (
                a.metadata.taken_at is None if a.metadata else True,
                a.metadata.taken_at if a.metadata and a.metadata.taken_at else datetime.min,
            )
        )
        day_segments, _, _, _, _ = _build_segments_for_day(ordered_assets_for_segments)
        segment_count = len(day_segments)
        day_segment_summaries = _build_segment_summaries(day_segments, asset_lookup, index_offset=0)
        global_segment_summaries = _build_segment_summaries(
            day_segments, asset_lookup, index_offset=len(map_route_segments)
        )
        map_route_segments.extend(global_segment_summaries)
        segments_total_distance_km = sum(s.get("distance_km") or 0.0 for s in day_segment_summaries)
        segments_total_duration_hours = sum(
            (s.get("duration_hours") or 0.0)
            for s in day_segment_summaries
            if s.get("duration_hours") is not None
        )
        profile = compute_day_layout_profile(day_photo_count, segment_count)
        asset_to_segment: Dict[str, int] = {}
        for seg in day_segments:
            idx_seg = seg.get("segment_index")
            for aid in seg.get("asset_ids", []):
                asset_to_segment[aid] = idx_seg
        display_date = day_date.strftime("%B %d, %Y") if day_date else None
        day_intro_pages_count += 1
        interior_pages.append(
            Page(
                index=current_index,
                page_type=PageType.DAY_INTRO,
                payload={
                    "day_index": day_index,
                    "day_date": day_date.isoformat() if day_date else None,
                    "display_date": display_date,
                    "day_photo_count": day_photo_count,
                    "segment_count": segment_count,
                    "segments_total_distance_km": segments_total_distance_km,
                    "segments_total_duration_hours": segments_total_duration_hours,
                    "segments": day_segment_summaries,
                },
            )
        )
        current_index += 1
        _reset_grid_variant_counter()
        # Optional full-page hero for the day
        day_remaining = list(day_ids)
        if (
            len(day_remaining) >= 5
            and full_hero_count < 2
            and full_page_photos_for_day < profile.max_full_page_photos
        ):
            hero_full = _select_full_page_hero(day_remaining, asset_lookup)
            if hero_full:
                day_remaining = [aid for aid in day_remaining if aid != hero_full]
                interior_pages.append(
                    Page(
                        index=current_index,
                        page_type=PageType.PHOTO_FULL,
                        payload={
                            "asset_ids": [hero_full],
                            "hero_asset_id": hero_full,
                        },
                    )
                )
                current_index += 1
                full_hero_count += 1
                full_page_photos_for_day += 1
        day_pages, current_index, spread_used = _build_photo_pages_with_optional_spread(
            day_remaining, photos_per_page, asset_lookup, current_index, spread_used
        )
        full_page_photos_for_day = _normalize_day_photo_pages(
            day_pages, profile, full_page_photos_for_day
        )
        chosen_grid_pages = _apply_segment_grid_variants(day_pages, asset_to_segment)
        interior_pages.extend(day_pages)

        print(
            f"[planner/day-layout] day_index={day_index} date={day_date} "
            f"photos={day_photo_count} segments={segment_count} "
            f"max_full_page={profile.max_full_page_photos} full_page_used={full_page_photos_for_day}"
        )
        if chosen_grid_pages:
            print(
                f"[planner/grid-variant] day_index={day_index} segments={segment_count} "
                f"grid_4_simple_pages={chosen_grid_pages}"
            )

    # Combine trip summary + optional map route + photo grids
    all_interior_pages = [trip_summary]
    if map_route_page:
        # Inject segment summaries into map route payload
        payload = map_route_page.payload or {}
        payload["segments"] = map_route_segments
        map_route_page.payload = payload
        all_interior_pages.append(map_route_page)
    all_interior_pages.extend(interior_pages)
    all_interior_pages = _ensure_layout_variants(all_interior_pages)

    # Debug accounting
    db_approved_ids = set(all_asset_ids)
    considered_ids = set(all_asset_ids)
    used_ids = set(deduped_ids)
    hidden_ids = {
        hid
        for cluster in dedup_summary.get("clusters", [])
        for hid in cluster.get("hidden_asset_ids", [])
    }
    for cluster in dedup_summary.get("clusters", []):
        hero = cluster.get("kept_asset_id")
        if hero:
            used_ids.add(hero)
    # Include cover hero if it comes from approved assets
    if hero_asset_id:
        used_ids.add(hero_asset_id)

    approved_count = len(db_approved_ids)
    considered_count = len(considered_ids)
    used_count = len(used_ids)
    auto_hidden_clusters_count = len(dedup_summary.get("clusters", []))
    auto_hidden_hidden_assets_count = len(hidden_ids)
    missing_used = considered_ids - used_ids - hidden_ids

    if approved_count != used_count + auto_hidden_hidden_assets_count:
        print(
            f"[planner][warn] count mismatch: approved={approved_count} used={used_count} hidden_assets={auto_hidden_hidden_assets_count}"
        )
    if missing_used:
        print(f"[planner][warn] missing in pages (considered but unused): {missing_used}")

    print(
        f"[planner] Assets: approved={approved_count} considered={considered_count} "
        f"used={used_count} auto_hidden_clusters={auto_hidden_clusters_count} "
        f"auto_hidden_assets={auto_hidden_hidden_assets_count} "
        f"day_intro_pages={day_intro_pages_count}"
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
    
    # Debug: print first/last few pages with asset ids for inspection
    def _page_summary(page: Page) -> str:
        asset_ids = page.payload.get("asset_ids") or []
        hero = page.payload.get("hero_asset_id")
        if hero and hero not in asset_ids:
            asset_ids = [hero] + list(asset_ids)
        return f"{page.index}:{page.page_type.value}:{asset_ids}"

    full_pages: List[Page] = []
    if front_cover:
        full_pages.append(front_cover)
    full_pages.extend(all_interior_pages)
    if back_cover:
        full_pages.append(back_cover)

    first_pages = full_pages[:5]
    last_pages = full_pages[-5:] if len(full_pages) > 5 else []
    print("[planner] First pages:", [_page_summary(p) for p in first_pages])
    if last_pages:
        print("[planner] Last pages:", [_page_summary(p) for p in last_pages])

    return Book(
        id=book_id,
        title=title,
        size=size,
        front_cover=front_cover,
        pages=all_interior_pages,
        back_cover=back_cover,
        auto_hidden_duplicate_clusters=dedup_summary.get("clusters", []),
        auto_hidden_clusters_count=auto_hidden_clusters_count,
        auto_hidden_hidden_assets_count=auto_hidden_hidden_assets_count,
        considered_count=considered_count,
        used_count=used_count,
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
            if not same_orientation:
                return False
            area_a = a.metadata.width * a.metadata.height
            area_b = b.metadata.width * b.metadata.height
            area_ratio = min(area_a, area_b) / max(area_a, area_b) if max(area_a, area_b) > 0 else 0
            width_ratio = min(a.metadata.width, b.metadata.width) / max(a.metadata.width, b.metadata.width)
            height_ratio = min(a.metadata.height, b.metadata.height) / max(a.metadata.height, b.metadata.height)
            similarity = min(area_ratio, width_ratio, height_ratio)
            return similarity >= HIGH_SIMILARITY_THRESHOLD

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
            if len(cluster) < MIN_CLUSTER_SIZE_FOR_AUTO_HIDE:
                clustered_keep.extend(cluster)
                continue
            hero = _select_cluster_hero(cluster, asset_lookup)
            hidden = [aid for aid in cluster if aid != hero]

            # Require high similarity of hero to every hidden item
            def similarity_ok(a_id: str, b_id: str) -> bool:
                a = asset_lookup.get(a_id)
                b = asset_lookup.get(b_id)
                if not a or not b or not a.metadata or not b.metadata:
                    return False
                area_a = (a.metadata.width or 0) * (a.metadata.height or 0)
                area_b = (b.metadata.width or 0) * (b.metadata.height or 0)
                if area_a == 0 or area_b == 0:
                    return False
                area_ratio = min(area_a, area_b) / max(area_a, area_b)
                width_ratio = min(a.metadata.width or 0, b.metadata.width or 0) / max(a.metadata.width or 0, b.metadata.width or 0)
                height_ratio = min(a.metadata.height or 0, b.metadata.height or 0) / max(a.metadata.height or 0, b.metadata.height or 0)
                same_orientation = (a.metadata.width or 0 >= a.metadata.height or 0) == (b.metadata.width or 0 >= b.metadata.height or 0)
                similarity = min(area_ratio, width_ratio, height_ratio) if same_orientation else 0
                return similarity >= HIGH_SIMILARITY_THRESHOLD

            if hidden and all(similarity_ok(hero, hid) for hid in hidden):
                cluster_counter += 1
                clustered_keep.append(hero)
                dropped += len(hidden)
                clusters.append(
                    {
                        "cluster_id": f"day_{current_day_date}_{cluster_counter}",
                        "kept_asset_id": hero,
                        "hidden_asset_ids": hidden,
                    }
                )
            else:
                clustered_keep.extend(cluster)

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


def _build_photo_pages_with_optional_spread(
    asset_ids: List[str],
    photos_per_page: int,
    asset_lookup: Dict[str, Asset],
    start_index: int,
    spread_used: bool,
) -> Tuple[List[Page], int, bool]:
    pages: List[Page] = []
    if not asset_ids:
        return pages, start_index, spread_used

    spread_hero_id = asset_ids[0] if asset_ids else None
    i = 0
    current_index = start_index

    while i < len(asset_ids):
        current_side = "left" if current_index % 2 == 0 else "right"
        aid = asset_ids[i]

        # If hero is on right, finish sheet with a grid to flip
        if (
            not spread_used
            and spread_hero_id
            and aid == spread_hero_id
            and current_side == "right"
        ):
            batch: List[str] = []
            j = i
            while j < len(asset_ids) and len(batch) < photos_per_page:
                if asset_ids[j] == spread_hero_id:
                    j += 1
                    continue
                batch.append(asset_ids[j])
                j += 1
            if batch:
                pages.append(
                    Page(
                        index=current_index,
                        page_type=PageType.PHOTO_GRID,
                        payload={
                            "asset_ids": batch,
                            "layout": _select_grid_layout(len(batch), photos_per_page),
                        },
                    )
                )
                current_index += 1
                # Keep hero at current i so the next iteration (now left side) can place the spread
                continue
            # No other photos to fill the right page; fall back to a single grid page
            pages.append(
                Page(
                    index=current_index,
                    page_type=PageType.PHOTO_GRID,
                    payload={
                        "asset_ids": [spread_hero_id],
                        "layout": _select_grid_layout(1, photos_per_page),
                    },
                )
            )
            current_index += 1
            i = j  # consume hero
            spread_used = True  # avoid reprocessing as spread
            continue

        # Insert spread on left when available
        if (
            not spread_used
            and spread_hero_id
            and aid == spread_hero_id
            and current_side == "left"
        ):
            pages.append(
                Page(
                    index=current_index,
                    page_type=PageType.PHOTO_SPREAD,
                    payload={
                        "asset_ids": [spread_hero_id],
                        "hero_asset_id": spread_hero_id,
                    },
                    spread_slot="left",
                )
            )
            pages.append(
                Page(
                    index=current_index + 1,
                    page_type=PageType.PHOTO_SPREAD,
                    payload={
                        "asset_ids": [spread_hero_id],
                        "hero_asset_id": spread_hero_id,
                    },
                    spread_slot="right",
                )
            )
            spread_used = True
            current_index += 2
            i += 1
            continue

        # Skip hero in grids
        if spread_hero_id and aid == spread_hero_id and not spread_used:
            i += 1
            continue

        # Normal grid page
        batch: List[str] = []
        while i < len(asset_ids) and len(batch) < photos_per_page:
            if spread_hero_id and not spread_used and asset_ids[i] == spread_hero_id:
                i += 1
                continue
            batch.append(asset_ids[i])
            i += 1

        if batch:
            if len(batch) == 1:
                # Single-photo chunk becomes a full-page hero
                pages.append(
                    Page(
                        index=current_index,
                        page_type=PageType.FULL_PAGE_PHOTO,
                        payload={
                            "asset_ids": batch,
                            "hero_asset_id": batch[0],
                        },
                    )
                )
            else:
                pages.append(
                    Page(
                        index=current_index,
                        page_type=PageType.PHOTO_GRID,
                        payload={
                            "asset_ids": batch,
                            "layout": _select_grid_layout(len(batch), photos_per_page),
                            "layout_variant": choose_grid_layout_variant(len(batch)),
                        },
                    )
                )
            current_index += 1

    return pages, current_index, spread_used


def _normalize_day_photo_pages(day_pages: List[Page], profile: DayLayoutProfile, full_used: int) -> int:
    """
    Convert any 1-photo grid within a single day to a full-page photo when allowed
    by the day's profile and cap.
    Returns updated full-page count.
    """
    for page in day_pages:
        if page.page_type != PageType.PHOTO_GRID:
            continue
        assets = page.payload.get("asset_ids") or []
        if (
            len(assets) == 1
            and profile.prefer_full_page_for_leftovers
            and full_used < profile.max_full_page_photos
        ):
            aid = assets[0]
            page.page_type = PageType.FULL_PAGE_PHOTO
            page.payload["hero_asset_id"] = aid
            print(f"[planner][info] converted single-photo grid to full page: {aid}")
    # Recompute full-page count from final day pages plus any already used
    full_pages_in_day = sum(
        1 for p in day_pages if p.page_type in (PageType.FULL_PAGE_PHOTO, PageType.PHOTO_FULL)
    )
    return full_used + full_pages_in_day


def _apply_segment_grid_variants(
    day_pages: List[Page],
    asset_to_segment: Dict[str, int],
) -> List[int]:
    """
    For each day, choose at most one 4-photo grid per segment to use the
    grid_4_simple layout variant (hero + three). All other grids default.
    """
    chosen_segments: set[int] = set()
    chosen_pages: List[int] = []

    for page in day_pages:
        if page.page_type != PageType.PHOTO_GRID:
            continue
        payload = page.payload or {}
        asset_ids = payload.get("asset_ids") or []
        # default baseline
        payload["layout_variant"] = "default"
        if len(asset_ids) != 4:
            page.payload = payload
            continue
        segments = {asset_to_segment.get(aid) for aid in asset_ids}
        segments.discard(None)
        if len(segments) != 1:
            page.payload = payload
            continue
        seg_idx = next(iter(segments))
        if seg_idx in chosen_segments:
            page.payload = payload
            continue
        payload["layout_variant"] = "grid_4_simple"
        chosen_segments.add(seg_idx)
        chosen_pages.append(page.index)
        page.payload = payload

    return chosen_pages


# ---------------------------
# Segment debug helpers
# ---------------------------

MAX_SEGMENT_TIME_GAP_MINUTES = 90   # Split if gap between photos exceeds 1.5h
LARGE_MOVE_DISTANCE_KM = 5.0        # Split if distance jump exceeds 5km
MIN_PHOTOS_PER_SEGMENT = 3          # Avoid micro segments; merge if below this


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute haversine distance in km."""
    from math import radians, sin, cos, sqrt, atan2

    R = 6371.0
    dlat = radians(lat2 - lat1)
    dlon = radians(lon2 - lon1)
    a = sin(dlat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(dlon / 2) ** 2
    c = 2 * atan2(sqrt(a), sqrt(1 - a))
    return R * c


def _build_segments_for_day(day_assets: List[Asset]) -> Tuple[List[Dict[str, Any]], int, int, int, int]:
    """
    Split a day's assets into segments based on time gaps and distance jumps.
    Steps:
    1) Initial split on large time gaps or large moves.
    2) Merge micro segments (< MIN_PHOTOS_PER_SEGMENT) unless they are clearly isolated.
    """
    if not day_assets:
        return []

    # Initial segmentation pass
    segments: List[List[Asset]] = []
    current_segment: List[Asset] = [day_assets[0]]
    break_reasons: List[Dict[str, bool]] = []  # reasons for break after segment i
    large_gap_count = 0
    large_move_count = 0
    candidate_breaks = 0

    for prev, curr in zip(day_assets, day_assets[1:]):
        split = False
        reason = {"time_gap": False, "move_gap": False}

        # Time gap
        if prev.metadata and prev.metadata.taken_at and curr.metadata and curr.metadata.taken_at:
            delta_min = abs((curr.metadata.taken_at - prev.metadata.taken_at).total_seconds()) / 60.0
            if delta_min > MAX_SEGMENT_TIME_GAP_MINUTES:
                split = True
                reason["time_gap"] = True
                large_gap_count += 1
        # Distance jump
        if (
            prev.metadata and curr.metadata
            and prev.metadata.gps_lat is not None and prev.metadata.gps_lon is not None
            and curr.metadata.gps_lat is not None and curr.metadata.gps_lon is not None
        ):
            jump = _haversine_km(
                prev.metadata.gps_lat, prev.metadata.gps_lon,
                curr.metadata.gps_lat, curr.metadata.gps_lon,
            )
            if jump >= LARGE_MOVE_DISTANCE_KM:
                split = True
                reason["move_gap"] = True
                large_move_count += 1
        if split:
            candidate_breaks += 1
            segments.append(current_segment)
            break_reasons.append(reason)
            current_segment = [curr]
        else:
            current_segment.append(curr)
    if current_segment:
        segments.append(current_segment)

    # Merge micro segments that are not clearly isolated
    idx = 0
    while idx < len(segments):
        seg = segments[idx]
        if len(seg) < MIN_PHOTOS_PER_SEGMENT:
            # Determine isolation: if both neighbors are separated by strong reasons, keep; else merge
            before_is_strong = False
            after_is_strong = False
            if idx > 0:
                br = break_reasons[idx - 1]
                before_is_strong = br.get("time_gap") or br.get("move_gap")
            if idx < len(break_reasons):
                br = break_reasons[idx]
                after_is_strong = br.get("time_gap") or br.get("move_gap")

            if not (before_is_strong and after_is_strong):
                # Prefer merging backward if possible, else forward
                if idx > 0:
                    segments[idx - 1].extend(seg)
                    del break_reasons[idx - 1]
                    del segments[idx]
                    continue
                elif idx + 1 < len(segments):
                    segments[idx + 1] = seg + segments[idx + 1]
                    del break_reasons[idx]
                    del segments[idx]
                    continue
        idx += 1  # advance if not merged

    out: List[Dict[str, Any]] = []
    for idx_seg, seg in enumerate(segments):
        seg_asset_ids = [a.id for a in seg]
        times = [a.metadata.taken_at for a in seg if a.metadata and a.metadata.taken_at]
        start_time = min(times) if times else None
        end_time = max(times) if times else None
        duration = None
        if start_time and end_time:
            duration = (end_time - start_time).total_seconds() / 60.0

        # Approx distance within segment
        dist_km = 0.0
        for s_prev, s_curr in zip(seg, seg[1:]):
            if (
                s_prev.metadata and s_curr.metadata
                and s_prev.metadata.gps_lat is not None and s_prev.metadata.gps_lon is not None
                and s_curr.metadata.gps_lat is not None and s_curr.metadata.gps_lon is not None
            ):
                dist_km += _haversine_km(
                    s_prev.metadata.gps_lat, s_prev.metadata.gps_lon,
                    s_curr.metadata.gps_lat, s_curr.metadata.gps_lon,
                )

        out.append(
            {
                "segment_index": idx_seg,
                "asset_ids": seg_asset_ids,
                "start_taken_at": start_time,
                "end_taken_at": end_time,
                "duration_minutes": duration,
                "approx_distance_km": dist_km if dist_km > 0 else None,
            }
        )
    kept_breaks = len(segments) - 1
    return out, large_gap_count, large_move_count, candidate_breaks, kept_breaks


def _build_segment_summaries(
    segments: List[Dict[str, Any]],
    asset_lookup: Dict[str, Asset],
    index_offset: int = 0,
) -> List[Dict[str, Any]]:
    """Create lightweight segment summaries for day intro / map pages."""
    summaries: List[Dict[str, Any]] = []
    for idx, seg in enumerate(segments):
        assets_in_seg = [asset_lookup.get(aid) for aid in seg.get("asset_ids", []) if aid in asset_lookup]
        polyline: List[Tuple[float, float]] = []
        for a in assets_in_seg:
            if (
                a
                and a.metadata
                and a.metadata.gps_lat is not None
                and a.metadata.gps_lon is not None
            ):
                polyline.append((a.metadata.gps_lat, a.metadata.gps_lon))

        duration_minutes = seg.get("duration_minutes")
        duration_hours = duration_minutes / 60.0 if duration_minutes is not None else None
        distance_km = seg.get("approx_distance_km", 0.0) or 0.0

        summaries.append(
            {
                "index": index_offset + idx + 1,  # 1-based
                "distance_km": distance_km,
                "duration_hours": duration_hours,
                "start_label": None,  # placeholder; no reverse geocoding
                "end_label": None,
                "polyline": polyline if polyline else None,
            }
        )
    return summaries


def get_book_segment_debug(book_id: str, days: List[Day], assets: List[Asset]) -> Dict[str, Any]:
    """
    Build segment debug info without altering planner output.
    Groups assets by day (existing order) and splits each day into segments.
    """
    asset_lookup = {a.id: a for a in assets}

    day_entries: List[Dict[str, Any]] = []
    total_segments = 0
    total_assets = 0

    for day in days:
        day_ids = [entry.asset_id for entry in day.all_entries]
        ordered_assets: List[Asset] = []
        for aid in day_ids:
            if aid in asset_lookup:
                ordered_assets.append(asset_lookup[aid])
        # Sort by taken_at when available to be safe
        ordered_assets.sort(
            key=lambda a: (
                a.metadata.taken_at is None if a.metadata else True,
                a.metadata.taken_at if a.metadata and a.metadata.taken_at else datetime.min,
            )
        )
        total_assets += len(ordered_assets)
        segments, gap_count, move_count, candidate_breaks, kept_breaks = _build_segments_for_day(ordered_assets)
        total_segments += len(segments)
        day_entries.append(
            {
                "day_index": day.index if day.index is not None else len(day_entries),
                "date": day.date.date() if day.date else None,
                "asset_ids": [a.id for a in ordered_assets],
                "segments": segments,
            }
        )
        print(
            f"[segmenter] book={book_id} day={day.date.date() if day.date else 'n/a'} "
            f"assets={len(ordered_assets)} segments={len(segments)} "
            f"gaps>{MAX_SEGMENT_TIME_GAP_MINUTES}m={gap_count} moves>{LARGE_MOVE_DISTANCE_KM}km={move_count} "
            f"breakpoints={candidate_breaks} kept={kept_breaks}"
        )

    print(f"[segments] book={book_id} days={len(day_entries)} segments={total_segments}")
    return {
        "book_id": book_id,
        "total_days": len(day_entries),
        "total_assets": total_assets,
        "days": day_entries,
    }


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


def _select_full_page_hero(asset_ids: List[str], asset_lookup: Dict[str, Asset]) -> Optional[str]:
    """
    Choose a full-page hero for a day.
    Prefer portrait or near-square assets if metadata is available; otherwise pick first.
    """
    if not asset_ids:
        return None
    portrait_ids: List[str] = []
    square_ids: List[str] = []
    others: List[str] = []
    for aid in asset_ids:
        asset = asset_lookup.get(aid)
        if not asset or not asset.metadata or not asset.metadata.width or not asset.metadata.height:
            others.append(aid)
            continue
        w, h = asset.metadata.width, asset.metadata.height
        if h >= w:
            portrait_ids.append(aid)
        elif abs(w - h) / max(w, h) < 0.1:
            square_ids.append(aid)
        else:
            others.append(aid)
    for group in (portrait_ids, square_ids, others):
        if group:
            return group[0]
    return asset_ids[0]


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
                "layout_variant": choose_grid_layout_variant(len(batch)),
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


def _reset_grid_variant_counter() -> None:
    """Reset per-day grid variant counter."""
    global _grid_variant_counter
    _grid_variant_counter = 0


def choose_grid_layout_variant(photo_count: int) -> str:
    """
    Return a layout_variant string for a photo_grid page.

    - 4 photos: use the hero + 3 below layout ("grid_4_simple")
    - everything else: stick with "default"
    """
    if photo_count == 4:
        return "grid_4_simple"
    return "default"


def _ensure_layout_variants(pages: List[Page]) -> List[Page]:
    """
    Ensure every photo_grid page has a non-null layout_variant.
    Currently defaults to "default" to match existing layouts.
    """
    for page in pages:
        if page.page_type == PageType.PHOTO_GRID:
            payload = page.payload or {}
            if payload.get("layout_variant") is None:
                payload["layout_variant"] = "default"
                page.payload = payload
    return pages


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
