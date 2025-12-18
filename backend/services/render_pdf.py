"""
PDF rendering service.

Renders the book layouts to a print-ready PDF file.
Uses HTML/CSS rendering via WeasyPrint for flexibility.
"""
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any, Iterable
from domain.models import Asset, Book, PageLayout, PageType, RenderContext, Theme
from services import map_route_renderer
from services.map_route_renderer import RouteMarker
from services.blurb_engine import (
    TripSummaryContext,
    DayIntroContext,
    build_trip_summary_blurb,
    build_day_intro_tagline,
)
from services.geocoding import compute_centroid, reverse_geocode_label
from services.itinerary import build_book_itinerary, build_place_candidates, PlaceCandidate
from services.places_enrichment import enrich_place_candidates_with_names
from services.manifest import build_manifest
from services.timeline import build_days_and_events
from services.face_crop import compute_face_focus
logger = logging.getLogger(__name__)


def get_pdf_layout_variant(page: Any, photo_count: int) -> str:
    """
    Normalize layout_variant for PDF rendering.

    Prefers top-level layout_variant, falls back to payload,
    and ultimately defaults to "default". Only honors
    grid_4_simple when there are exactly 4 photos.
    """
    variant = getattr(page, "layout_variant", None)
    payload = getattr(page, "payload", None)
    if variant is None and isinstance(payload, dict):
        variant = payload.get("layout_variant")
    if not variant:
        return "default"
    variant_str = str(variant).strip()
    if variant_str == "grid_3_hero" and photo_count >= 3:
        return "grid_3_hero"
    if variant_str == "grid_6_simple" and photo_count == 6:
        return "grid_6_simple"
    if variant_str == "grid_4_simple" and photo_count == 4:
        return "grid_4_simple"
    return "default"

def format_day_segment_summary(segment_count: Optional[int], total_hours: Optional[float], total_km: Optional[float]) -> str:
    """Return a summary line like '3 segments • 8.4 h • ~1492.6 km'."""
    count = segment_count or 0
    if count <= 0:
        return ""
    parts: List[str] = []
    parts.append(f"{count} {'segment' if count == 1 else 'segments'}")
    if total_hours and total_hours > 0:
        parts.append(f"{total_hours:.1f} h")
    if total_km and total_km > 0:
        parts.append(f"~{total_km:.1f} km")
    return " • ".join(parts)


def format_segment_line(index: int, segment: Dict[str, Any]) -> str:
    """Return a printable line for a single segment."""
    parts: List[str] = [f"Segment {index}"]
    hours = segment.get("duration_hours")
    km = segment.get("distance_km")
    if isinstance(hours, (int, float)) and hours > 0:
        parts.append(f"{hours:.1f} h")
    if isinstance(km, (int, float)) and km > 0:
        parts.append(f"{km:.1f} km")
    return " • ".join(parts)


def _points_from_segments(segments: Iterable[Dict[str, Any]]) -> List[tuple[float, float]]:
    """Flatten segment polylines into a list of (lat, lon) tuples."""
    points: List[tuple[float, float]] = []
    for seg in segments or []:
        polyline = seg.get("polyline") or []
        try:
            for lat, lon in polyline:
                points.append((float(lat), float(lon)))
        except Exception:
            continue
    return points


def _location_label_for_segments(segments: Iterable[Dict[str, Any]]) -> Optional[str]:
    """Compute a short location label for a collection of segments."""
    points = _points_from_segments(segments)
    centroid = compute_centroid(points)
    if not centroid:
        return None
    place = reverse_geocode_label(*centroid)
    return place.short_label if place else None


MAX_NOTABLE_PLACES = 5


def _format_place_label(place: PlaceCandidate) -> str:
    """Derive a compact display label for a place."""
    if getattr(place, "best_place_name", None):
        name = str(place.best_place_name).split(",")[0].strip()
        if name:
            return name if len(name) <= 50 else f"{name[:47].rstrip()}..."
    return f"{place.center_lat:.4f}, {place.center_lon:.4f}"


def _build_notable_places(place_candidates: List[PlaceCandidate]) -> List[PlaceCandidate]:
    candidates = [p for p in (place_candidates or []) if not p.hidden]
    if len(candidates) > MAX_NOTABLE_PLACES:
        candidates = candidates[:MAX_NOTABLE_PLACES]
    candidates = enrich_place_candidates_with_names(candidates, max_lookups=len(candidates))
    return candidates


def _build_trip_route_markers(itinerary: Any) -> List[RouteMarker]:
    """Collect markers for local stops across the trip."""
    markers: List[RouteMarker] = []
    days = getattr(itinerary, "days", None) if itinerary is not None else None
    if days is None:
        days = itinerary
    for day in days or []:
        stops = getattr(day, "stops", None) or []
        for stop in stops:
            if getattr(stop, "kind", None) != "local":
                continue
            poly = getattr(stop, "polyline", None)
            if not poly:
                continue
            try:
                lat, lon = poly[0]
            except Exception:
                continue
            markers.append(RouteMarker(lat=lat, lon=lon, kind=stop.kind))

    MAX_MARKERS = 12
    if len(markers) > MAX_MARKERS:
        markers = markers[:MAX_MARKERS]
    return markers


def _build_day_route_markers(day: Any) -> List[RouteMarker]:
    """Collect markers for local stops within a day."""
    markers: List[RouteMarker] = []
    if not day:
        return markers
    stops = getattr(day, "stops", None) or []
    for stop in stops:
        if getattr(stop, "kind", None) != "local":
            continue
        poly = getattr(stop, "polyline", None)
        if not poly:
            continue
        try:
            lat, lon = poly[0]
        except Exception:
            continue
        markers.append(RouteMarker(lat=lat, lon=lon, kind=stop.kind))
    return markers


MAX_TRIP_PLACE_MARKERS = 10
MAX_DAY_PLACE_MARKERS = 5


def _build_trip_place_markers(place_candidates: Iterable[PlaceCandidate]) -> List[RouteMarker]:
    """
    Return up to MAX_TRIP_PLACE_MARKERS RouteMarker objects for the trip route map.
    Uses the same scoring/ordering as the places debug UI:
    - Prefer candidates with higher score (more photos and duration).
    - Only include candidates that have at least 1 photo and are not hidden.
    """
    markers: List[RouteMarker] = []
    candidates = list(place_candidates or [])
    print(f"[PLACE_MARKERS] _build_trip_place_markers: {len(candidates)} candidates received")
    # Candidates are already sorted by score descending from build_place_candidates
    for c in candidates:
        if c.total_photos < 1 or c.hidden:
            print(f"[PLACE_MARKERS]   skipping candidate at ({c.center_lat:.4f}, {c.center_lon:.4f}) - photos={c.total_photos}, hidden={c.hidden}")
            continue
        markers.append(RouteMarker(lat=c.center_lat, lon=c.center_lon, kind="place"))
        print(f"[PLACE_MARKERS]   added marker at ({c.center_lat:.4f}, {c.center_lon:.4f}) photos={c.total_photos}")
        if len(markers) >= MAX_TRIP_PLACE_MARKERS:
            break
    print(f"[PLACE_MARKERS] _build_trip_place_markers: returning {len(markers)} markers")
    return markers


def _build_day_place_markers(day_index: int, place_candidates: Iterable[PlaceCandidate]) -> List[RouteMarker]:
    """
    Return up to MAX_DAY_PLACE_MARKERS RouteMarker objects for this specific day.
    Only include candidates whose day_indices include this day_index and are not hidden.
    """
    markers: List[RouteMarker] = []
    candidates = list(place_candidates or [])
    print(f"[PLACE_MARKERS] _build_day_place_markers: day_index={day_index}, {len(candidates)} candidates received")
    for c in candidates:
        if c.total_photos < 1 or c.hidden:
            print(f"[PLACE_MARKERS]   day {day_index}: skipping ({c.center_lat:.4f}, {c.center_lon:.4f}) - photos={c.total_photos}, hidden={c.hidden}")
            continue
        if day_index not in (c.day_indices or []):
            print(f"[PLACE_MARKERS]   day {day_index}: skipping ({c.center_lat:.4f}, {c.center_lon:.4f}) - not in day_indices {c.day_indices}")
            continue
        markers.append(RouteMarker(lat=c.center_lat, lon=c.center_lon, kind="place"))
        print(f"[PLACE_MARKERS]   day {day_index}: added marker at ({c.center_lat:.4f}, {c.center_lon:.4f})")
        if len(markers) >= MAX_DAY_PLACE_MARKERS:
            break
    print(f"[PLACE_MARKERS] _build_day_place_markers: returning {len(markers)} markers for day {day_index}")
    return markers


def _format_place_name_for_display(candidate: PlaceCandidate) -> str:
    """
    Format a single PlaceCandidate for display text.
    Prefers override_name, then display_name, then raw_name,
    then best_place_name, and finally coordinates.
    """
    # Try override_name first (user custom name takes highest priority)
    if candidate.override_name and candidate.override_name.strip():
        return candidate.override_name.strip()
    # Try display_name (clean, book-ready version)
    if candidate.display_name and candidate.display_name.strip():
        return candidate.display_name.strip()
    # Fall back to raw_name
    if candidate.raw_name and candidate.raw_name.strip():
        return candidate.raw_name.strip()
    # Fall back to best_place_name for backwards compatibility
    if candidate.best_place_name and candidate.best_place_name.strip():
        return candidate.best_place_name.strip()
    # Last resort: coordinates
    return f"({candidate.center_lat:.4f}, {candidate.center_lon:.4f})"


def _build_trip_place_names(place_candidates: Iterable[PlaceCandidate], max_count: int = MAX_TRIP_PLACE_MARKERS) -> str:
    """
    Return a formatted string of place names for the trip route page.
    E.g., "Highlighted places: Chicago, Millennium Park, Museum Campus"
    
    Only includes candidates with at least 1 photo and not hidden.
    Respects the same limits as place markers.
    Returns an empty string if no candidates qualify.
    """
    candidates = list(place_candidates or [])
    names: List[str] = []
    for c in candidates:
        if c.total_photos < 1 or c.hidden:
            continue
        names.append(_format_place_name_for_display(c))
        if len(names) >= max_count:
            break
    if not names:
        return ""
    return "Highlighted places: " + ", ".join(names)


def _build_day_place_names(day_index: int, place_candidates: Iterable[PlaceCandidate], max_count: int = MAX_DAY_PLACE_MARKERS) -> str:
    """
    Return a formatted string of place names for a specific day intro page.
    E.g., "Places today: The Bean, Chicago Riverwalk"
    
    Only includes candidates for that day with at least 1 photo and not hidden.
    Returns an empty string if no candidates qualify.
    """
    candidates = list(place_candidates or [])
    names: List[str] = []
    for c in candidates:
        if c.total_photos < 1 or c.hidden:
            continue
        if day_index not in (c.day_indices or []):
            continue
        names.append(_format_place_name_for_display(c))
        if len(names) >= max_count:
            break
    if not names:
        return ""
    return "Places today: " + ", ".join(names)


MAX_TRIP_HIGHLIGHT_PLACES = 3
MAX_THUMBNAILS_PER_PLACE = 3


def _choose_trip_highlight_places(
    place_candidates: Iterable[PlaceCandidate],
) -> List[PlaceCandidate]:
    """
    Pick up to 3 best places for the Trip Summary highlights strip.
    Filters to candidates with at least 1 photo, then sorts by:
    1. total_photos (descending)
    2. total_duration_hours (descending)
    3. visit_count (descending)
    """
    candidates = [p for p in (place_candidates or []) if p.total_photos > 0]
    candidates.sort(
        key=lambda p: (
            -(p.total_photos or 0),
            -(p.total_duration_hours or 0.0),
            -(p.visit_count or 0),
        )
    )
    return candidates[:MAX_TRIP_HIGHLIGHT_PLACES]


def _render_place_highlight_cards(
    place_candidates: Iterable[PlaceCandidate],
    *,
    day_index: Optional[int] = None,
    mode: str = "web",
    media_root: str = "",
    media_base_url: str | None = None,
) -> str:
    """
    Render a block of place highlight cards.

    - If `day_index` is provided, only include candidates for that day.
    - Respects `MAX_TRIP_HIGHLIGHT_PLACES` and `MAX_THUMBNAILS_PER_PLACE`.
    - Works for both `web` and `pdf` modes (resolves thumbnail URLs accordingly).
    """
    candidates = list(place_candidates or [])
    if day_index is not None:
        candidates = [p for p in candidates if day_index in (p.day_indices or [])]
    if not candidates:
        return ""

    # Choose top N places using the same selection logic as trip highlights
    chosen = _choose_trip_highlight_places(candidates)
    if not chosen:
        return ""

    cards_html_parts: List[str] = []
    for p in chosen:
        name = p.display_name or p.raw_name or p.best_place_name or f"({p.center_lat:.4f}, {p.center_lon:.4f})"

        thumbs_parts: List[str] = []
        for t in (p.thumbnails or [])[:MAX_THUMBNAILS_PER_PLACE]:
            if not getattr(t, "thumbnail_path", None):
                continue
            if mode == "pdf":
                candidate = Path(t.thumbnail_path)
                if not candidate.is_absolute():
                    candidate = Path(media_root) / candidate
                img_src = candidate.resolve().as_uri()
            else:
                img_src = _resolve_web_image_url(t.thumbnail_path, media_base_url)
            thumbs_parts.append(f'<img src="{img_src}" class="trip-place-highlight-thumb" />')

        cards_html_parts.append(
            f'''<div class="trip-place-highlight-card">
                        <div class="trip-place-highlight-name">{name}</div>
                        <div class="trip-place-highlight-thumbs">{''.join(thumbs_parts)}</div>
                    </div>'''
        )

    return f"<div class=\"trip-place-highlights\">{''.join(cards_html_parts)}</div>"


def render_book_to_pdf(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    output_path: str,
    media_root: str,
) -> str:
    """
    Render a book to PDF.
    
    Args:
        book: The book to render
        layouts: Computed layouts for all pages
        assets: Dict mapping asset ID to Asset
        context: Render context with theme
        output_path: Where to save the PDF
        media_root: Root path for media files
    
    Returns:
        Path to the generated PDF
    """
    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    
    # Generate HTML for the book
    html_content = render_book_to_html(
        book, layouts, assets, context, media_root, mode="pdf"
    )
    
    # Try to render with WeasyPrint
    try:
        from weasyprint import HTML, CSS
        
        # Create CSS for print
        css = _generate_print_css(context)
        
        # Render to PDF
        html_doc = HTML(string=html_content, base_url=media_root)
        css_doc = CSS(string=css)
        html_doc.write_pdf(output_path, stylesheets=[css_doc])
        
        return output_path
        
    except ImportError:
        # WeasyPrint not available, create a placeholder PDF
        return _create_placeholder_pdf(output_path, book, layouts)


def render_book_to_html(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """
    Generate HTML for the entire book.
    Does not touch disk; intended for preview rendering.

    mode:
      - "pdf": keep filesystem-relative paths (resolved via base_url) for WeasyPrint
      - "web": use /media/{file_path} so the browser can load assets
    """
    return _generate_book_html(
        book, layouts, assets, context, media_root, mode, media_base_url
    )

def _render_photo_grid_from_elements(
    layout: PageLayout,
    assets: Dict[str, Asset],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str,
    media_base_url: str | None,
) -> str:
    """Render photo grids using precomputed LayoutRect positions (variant-aware)."""
    photo_elements = [elem for elem in layout.elements if elem.asset_id or elem.image_path or elem.image_url]
    photo_count = len(photo_elements)
    variant = get_pdf_layout_variant(layout, photo_count)
    logger.debug("[render_pdf] grid page index=%s variant=%s photo_count=%s mode=%s", layout.page_index, variant, photo_count, mode)

    bg_color = layout.background_color or theme.background_color
    elements_html = []
    label_html = ""
    if (
        layout.layout_variant == "segment_local_highlight_v1"
        and getattr(layout, "segment_label", None)
    ):
        label_html = f'<div class="segment-highlight-label">{layout.segment_label}</div>'

    for elem in layout.elements:
        img_src = ""
        if elem.image_path or elem.image_url:
            if mode == "pdf":
                candidate = elem.image_path or ""
                if candidate:
                    candidate_path = Path(candidate)
                    if not candidate_path.is_absolute():
                        candidate_path = Path(media_root) / candidate_path
                    # For PDF-rendered hero/full-page images, attempt a face-safe crop
                    try:
                        frac_w = (elem.width_mm or 0) / width_mm if width_mm else 0
                        frac_h = (elem.height_mm or 0) / height_mm if height_mm else 0
                        is_hero = frac_w >= 0.7 or frac_h >= 0.7
                    except Exception:
                        is_hero = False
                    if is_hero:
                        # Use face focus to guide rendering. If no face focus is found
                        # the renderer should fall back to center-crop (do not write files).
                        try:
                            focus = compute_face_focus(str(candidate_path))
                            if focus:
                                # When a focus is available, instruct WeasyPrint to use
                                # the full image but we can rely on CSS object-position to
                                # center the face. We'll still provide the full file URI.
                                img_src = candidate_path.resolve().as_uri()
                                # embed focus information as data-attr so CSS can be adjusted
                                # Note: WeasyPrint doesn't support custom data attributes for
                                # positioning; instead we set style with object-position here.
                                ox = f"{focus['center_x_pct'] * 100:.2f}%"
                                oy = f"{focus['center_y_pct'] * 100:.2f}%"
                                # attach style to the img tag below via a placeholder
                                img_style = f"object-fit:cover;object-position:{ox} {oy};"
                            else:
                                img_src = candidate_path.resolve().as_uri()
                                img_style = "object-fit:cover;object-position:50% 50%;"
                        except Exception:
                            img_src = candidate_path.resolve().as_uri()
                            img_style = "object-fit:cover;object-position:50% 50%;"
                    
                    else:
                        img_src = candidate_path.resolve().as_uri()
            else:
                img_src = _resolve_web_image_url(elem.image_url or "", media_base_url)
        elif elem.asset_id and elem.asset_id in assets:
            asset = assets[elem.asset_id]
            normalized_path = asset.file_path.replace("\\", "/")
            if mode == "pdf":
                candidate_path = Path(normalized_path)
                if not candidate_path.is_absolute():
                    candidate_path = Path(media_root) / candidate_path
                # If this element is a hero/full-page photo, produce a face-safe cropped
                # file on disk and use that for PDF rendering. Otherwise use the original.
                try:
                    frac_w = (elem.width_mm or 0) / width_mm if width_mm else 0
                    frac_h = (elem.height_mm or 0) / height_mm if height_mm else 0
                    is_hero = frac_w >= 0.7 or frac_h >= 0.7
                except Exception:
                    is_hero = False
                if is_hero:
                    try:
                        focus = compute_face_focus(str(candidate_path))
                        if focus:
                            img_src = candidate_path.resolve().as_uri()
                            ox = f"{focus['center_x_pct'] * 100:.2f}%"
                            oy = f"{focus['center_y_pct'] * 100:.2f}%"
                            img_style = f"object-fit:cover;object-position:{ox} {oy};"
                        else:
                            img_src = candidate_path.resolve().as_uri()
                            img_style = "object-fit:cover;object-position:50% 50%;"
                    except Exception:
                        img_src = candidate_path.resolve().as_uri()
                        img_style = "object-fit:cover;object-position:50% 50%;"
                else:
                    img_src = candidate_path.resolve().as_uri()
                    img_style = "object-fit:cover;object-position:50% 50%;"
            else:
                base = media_base_url.rstrip("/") if media_base_url else "/media"
                img_src = f"{base}/{normalized_path}"

        if img_src:
            # Use computed img_style when available
            style_attr = img_style if 'img_style' in locals() else "object-fit:cover;object-position:50% 50%;"
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    overflow: hidden;
                    border-radius: 4px;
                ">
                    <img src="{img_src}" style="width:100%;height:100%;{style_attr}" />
                </div>
            """)
        elif elem.text:
            color = elem.color or theme.primary_color
            font_size = elem.font_size or 12
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    color: {color};
                    font-size: {font_size}pt;
                    font-family: {theme.title_font_family if font_size > 14 else theme.font_family};
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                ">
                    {elem.text}
                </div>
            """)
        elif elem.color:
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    background: {elem.color};
                "></div>
            """)

    return f"""
    <div class="page photo-grid-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        {label_html}
        {''.join(elements_html)}
    </div>
    """


def _render_blank_page(theme: Theme, width_mm: float, height_mm: float) -> str:
    """Render a truly blank page."""
    return f"""
    <div class="page pdf-page-blank" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: #ffffff;
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
    </div>
    """


def _generate_book_html(
    book: Book,
    layouts: List[PageLayout],
    assets: Dict[str, Asset],
    context: RenderContext,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """Generate HTML for the entire book."""
    theme = context.theme
    width_mm = context.page_width_mm
    height_mm = context.page_height_mm

    pages_html = []

    # Precompute itinerary days once (used by trip summary and optional itinerary page)
    try:
        asset_list = list(assets.values())
        manifest = build_manifest(book.id, asset_list)
        days = build_days_and_events(manifest)
        itinerary_days = build_book_itinerary(book, days, asset_list)
        place_candidates = build_place_candidates(itinerary_days, asset_list)
        from services.itinerary import merge_place_candidate_overrides
        place_candidates = merge_place_candidate_overrides(place_candidates, book.id)
    except Exception:
        itinerary_days = []
        place_candidates = []

    def _layout_has_photos(layout: PageLayout) -> bool:
        elements = getattr(layout, "elements", None) or []
        asset_elems = [e for e in elements if getattr(e, "asset_id", None)]
        payload = getattr(layout, "payload", None)
        payload_assets = []
        if isinstance(payload, dict):
            aids = payload.get("asset_ids") or []
            if isinstance(aids, list):
                payload_assets = aids
        return len(asset_elems) > 0 or len(payload_assets) > 0

    for idx, layout in enumerate(layouts):
        logger.info("[render_pdf] Rendering page %s: page_type=%s", idx, layout.page_type)
        if layout.page_type in (PageType.PHOTO_GRID, PageType.PHOTO_SPREAD) and not _layout_has_photos(layout):
            logger.warning(
                "[render_pdf] Skipping empty photo page index=%s type=%s", idx, layout.page_type
            )
            continue
        logger.debug(
            "[render_pdf] page index=%s type=%s hero=%s assets=%s layout_variant=%s",
            layout.page_index,
            layout.page_type,
            layout.payload.get('hero_asset_id') if hasattr(layout, 'payload') else None,
            layout.payload.get('asset_ids') if hasattr(layout, 'payload') else None,
            getattr(layout, "layout_variant", None),
        )
        if layout.page_type == PageType.TRIP_SUMMARY:
            setattr(layout, "itinerary_days", itinerary_days)
            setattr(layout, "place_candidates", place_candidates)
        if itinerary_days:
            if layout.page_type == PageType.MAP_ROUTE:
                setattr(layout, "itinerary_days", itinerary_days)
                setattr(layout, "place_candidates", place_candidates)
                if not getattr(layout, "book_id", None):
                    setattr(layout, "book_id", getattr(book, "id", None))
            if layout.page_type == PageType.DAY_INTRO:
                payload = getattr(layout, "payload", None) or {}
                day_idx = payload.get("day_index")
                day_match = None
                if day_idx is not None:
                    for day in itinerary_days:
                        if getattr(day, "day_index", None) == day_idx:
                            day_match = day
                            break
                setattr(layout, "itinerary_day", day_match)
                setattr(layout, "place_candidates", place_candidates)
                setattr(layout, "day_index", day_idx)
                if not getattr(layout, "book_id", None):
                    setattr(layout, "book_id", getattr(book, "id", None))
        page_html = _render_page_html(
            layout,
            assets,
            theme,
            width_mm,
            height_mm,
            media_root,
            mode,
            media_base_url,
        )
        pages_html.append(page_html)

    # Optional itinerary page appended after all pages
    if itinerary_days:
        pages_html.append(
            _render_itinerary_page(
                itinerary_days,
                theme,
                width_mm,
                height_mm,
                page_index=len(pages_html),
            )
        )

    extra_styles = ""
    if mode == "web":
        extra_styles = """
        <style>
            body {
                margin: 0;
                padding: 24px 0;
                background: #e5e7eb;
                display: flex;
                flex-direction: column;
                align-items: center;
                font-family: sans-serif;
            }
            .page {
                margin: 16px 0;
                box-shadow: 0 10px 30px rgba(0,0,0,0.12);
                border-radius: 8px;
                overflow: hidden;
                background: #ffffff;
                border: 1px solid #e5e7eb;
            }
            .page.page--full-page-photo {
                border: 1px solid #e5e7eb;
            }
        </style>
        """

    return f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>{book.title}</title>
    {extra_styles}
</head>
<body>
    {''.join(pages_html)}
</body>
</html>
    """


def _render_itinerary_page(
    itinerary_days: List[Any],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    page_index: int,
) -> str:
    """Render itinerary as a normal page with the standard wrapper."""
    if not itinerary_days:
        return ""

    def fmt_date(date_iso: str) -> str:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(date_iso)
            return dt.strftime("%B %d, %Y")
        except Exception:
            return date_iso

    def fmt_distance(km: Optional[float]) -> str:
        if km is None or km <= 0:
            return ""
        return f"~{km:.1f} km"

    def fmt_hours(hours: Optional[float]) -> str:
        if hours is None or hours <= 0:
            return ""
        return f"{hours:.1f} h"

    def label_for_stop_kind(kind: Optional[str]) -> str:
        if kind == "travel":
            return "Travel segment"
        if kind == "local":
            return "Local exploring"
        return "Segment"

    day_blocks: List[str] = []
    for day in itinerary_days:
        segments_count = len(getattr(day, "stops", []) or [])
        distance_txt = fmt_distance(getattr(day, "segments_total_distance_km", None))
        hours_txt = fmt_hours(getattr(day, "segments_total_duration_hours", None))
        stats_parts = [
            f"{getattr(day, 'photos_count', 0)} photos",
            f"{segments_count} segments",
        ]
        if distance_txt:
            stats_parts.append(distance_txt)
        if hours_txt:
            stats_parts.append(hours_txt)
        stats_line = " • ".join(stats_parts)

        locations = getattr(day, "locations", None) or []
        location_labels: List[str] = []
        if locations:
            for loc in locations:
                label = getattr(loc, "location_short", None) or getattr(
                    loc, "location_full", None
                )
                if not label:
                    continue
                location_labels.append(label)
        location_line = " • ".join(location_labels) if location_labels else ""

        stops_html = ""
        stops = getattr(day, "stops", None) or []
        if stops:
            rows: List[str] = []
            for stop in stops:
                kind_label = label_for_stop_kind(getattr(stop, "kind", None))
                stop_parts: List[str] = []
                dur = fmt_hours(getattr(stop, "duration_hours", None))
                dist = fmt_distance(getattr(stop, "distance_km", None))
                if dur:
                    stop_parts.append(dur)
                if dist:
                    stop_parts.append(dist)
                metrics = " • ".join(stop_parts)
                rows.append(
                    f'<li class="itinerary-stop"><span class="itinerary-stop-kind">{kind_label}</span>{f"<span class=\"itinerary-stop-meta\"> • {metrics}</span>" if metrics else ""}</li>'
                )
            if rows:
                stops_html = f'<ul class="itinerary-stops">{"".join(rows)}</ul>'

        day_blocks.append(
            f"""
        <div class="itinerary-day">
            <div class="itinerary-day-header">
                <div class="itinerary-day-title">Day {getattr(day, 'day_index', '')} — {fmt_date(getattr(day, 'date_iso', '') or '')}</div>
                {f'<div class="itinerary-day-location">{location_line}</div>' if location_line else ''}
                <div class="itinerary-day-stats">{stats_line}</div>
            </div>
            {stops_html}
        </div>
        """
        )

    return f"""
    <div class="page itinerary-page" data-page-index="{page_index}" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {theme.background_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        <style>
            .itinerary {{
                padding: 2.5rem 2.75rem;
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
            }}
            .itinerary-title {{
                font-size: 1.6rem;
                font-weight: 700;
                margin: 0 0 0.75rem 0;
            }}
            .itinerary-day {{
                margin-bottom: 0.75rem;
                border-top: 1px solid #eee;
                padding-top: 0.6rem;
            }}
            .itinerary-day-header {{
                margin-bottom: 0.25rem;
            }}
            .itinerary-day-title {{
                font-weight: 600;
                font-size: 0.95rem;
            }}
            .itinerary-day-location {{
                font-size: 0.9rem;
                color: #555;
            }}
            .itinerary-day-stats {{
                font-size: 0.85rem;
                color: #444;
            }}
            .itinerary-day-stats span + span {{
                margin-left: 0.25rem;
            }}
            .itinerary-day-locations {{
                font-size: 0.75rem;
                color: #555;
            }}
            .itinerary-location-line + .itinerary-location-line {{
                margin-top: 0.1rem;
            }}
            .itinerary-stops {{
                list-style: none;
                padding-left: 0;
                margin: 0.2rem 0 0 0;
            }}
            .itinerary-stop {{
                font-size: 0.85rem;
                color: #444;
            }}
            .itinerary-stop + .itinerary-stop {{
                margin-top: 0.1rem;
            }}
            .itinerary-stop-kind {{
                font-weight: 500;
            }}
            .itinerary-stop-meta {{
                margin-left: 0.2rem;
            }}
            .segment-highlight-label {{
                font-size: 0.8rem;
                font-weight: 600;
                margin: 12px 12px 4px 12px;
                color: #444;
            }}
        </style>
        <section class="itinerary">
            <h1 class="itinerary-title">Trip Itinerary</h1>
            {''.join(day_blocks)}
        </section>
    </div>
    """


def _render_map_route_card(
    layout: PageLayout,
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str,
    media_base_url: str | None,
) -> str:
    """Render the map route page as a centered card with title/subtitle."""
    bg_color = layout.background_color or theme.background_color

    image_src = ""
    title = "Trip Route"
    stats_candidates: List[str] = []

    for elem in layout.elements:
        if (elem.image_path or elem.image_url) and not image_src:
            if mode == "pdf":
                image_src = elem.image_path or ""
            else:
                image_src = _resolve_web_image_url(elem.image_url or "", media_base_url)
        elif elem.text:
            # Keep the first text element as title if it looks like one; otherwise treat as stats text.
            if title == "Trip Route" and elem.text.lower().startswith("trip route"):
                title = elem.text
            else:
                stats_candidates.append(elem.text)

    stats_from_elements = " • ".join([s for s in stats_candidates if s.strip()])

    segments = getattr(layout, "segments", []) or []
    trip_markers = _build_trip_route_markers(getattr(layout, "itinerary_days", None))
    place_markers = _build_trip_place_markers(getattr(layout, "place_candidates", None) or [])
    all_markers = trip_markers + place_markers
    route_points = _points_from_segments(segments)
    if layout.book_id and route_points:
        trip_rel_path, trip_abs_path = map_route_renderer.render_trip_route_map(
            layout.book_id,
            route_points,
            markers=all_markers,
        )
        if trip_rel_path or trip_abs_path:
            if mode == "pdf":
                image_src = trip_abs_path or image_src
            else:
                image_src = _resolve_web_image_url(
                    f"/static/{trip_rel_path}" if trip_rel_path else trip_abs_path,
                    media_base_url,
                )
    seg_count = len(segments)
    seg_total_hours = sum((s.get("duration_hours") or 0.0) for s in segments)
    seg_total_km = sum((s.get("distance_km") or 0.0) for s in segments)
    seg_summary = format_day_segment_summary(seg_count, seg_total_hours, seg_total_km)
    stats_line = stats_from_elements or seg_summary

    # Build place names text for trip route
    place_names_line = _build_trip_place_names(getattr(layout, "place_candidates", None) or [])

    figure_html = ""
    if image_src:
        figure_html = f"""
            <div class="trip-route-map-frame">
                <img class="trip-route-map-image" src="{image_src}" alt="Trip route map" />
            </div>
        """
    else:
        figure_html = """
            <div class="map-route-placeholder">Route image unavailable</div>
        """

    return f"""
    <div class="page map-route-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        <style>
            .map-route-page {{
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: flex-start;
            }}
            .trip-route-section {{
                width: 88%;
                max-width: 190mm;
                margin: 16mm auto;
            }}
            .trip-route-header {{
                margin-bottom: 12px;
            }}
            .trip-route-title {{
                font-family: {theme.title_font_family};
                font-size: 22pt;
                margin: 0;
            }}
            .trip-route-stats {{
                font-size: 11pt;
                color: #374151;
                margin-top: 4px;
            }}
            .trip-route-stats span + span {{
                margin-left: 6px;
            }}
            .trip-route-place-names {{
                font-size: 10pt;
                color: {theme.secondary_color};
                margin-top: 8px;
                line-height: 1.4;
            }}
            .trip-route-map-frame {{
                margin-top: 14px;
                border-radius: 8px;
                overflow: hidden;
                box-shadow: 0 12px 30px rgba(15, 23, 42, 0.12);
            }}
            .trip-route-map-image {{
                width: 100%;
                height: auto;
                display: block;
            }}
            .map-route-placeholder {{
                width: 100%;
                padding: 30mm 10mm;
                background: #e2e8f0;
                color: #475569;
                border-radius: 8px;
                border: 1px dashed #cbd5e1;
                font-size: 12pt;
            }}
        </style>
        <section class="trip-route-section">
            <header class="trip-route-header">
                <h1 class="trip-route-title">{title}</h1>
                {f'<div class="trip-route-stats"><span>{stats_line}</span></div>' if stats_line else ''}
                {f'<div class="trip-route-place-names">{place_names_line}</div>' if place_names_line else ''}
            </header>
            {figure_html}
        </section>
    </div>
    """


def _render_trip_summary_card(
    layout: PageLayout,
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str = "",
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """Render a clean trip summary page with header + stats."""
    bg_color = layout.background_color or theme.background_color

    title = "Trip summary"
    subtitle = ""
    stats: List[str] = []

    for elem in layout.elements:
        if elem.text:
            if title == "Trip summary":
                title = elem.text
            elif not subtitle:
                subtitle = elem.text
            else:
                stats.append(elem.text)

    stats = [s for s in stats if s.strip()]
    stats_line_parts: List[str] = []
    num_days = None
    num_photos = None
    num_events = None
    num_locations = None
    for line in stats:
        if ":" in line:
            label, value = line.split(":", 1)
            label = label.strip().lower()
            value = value.strip()
            if value and value != "0":
                if label.endswith("s"):
                    stats_line_parts.append(f"{value} {label}")
                else:
                    stats_line_parts.append(f"{value} {label}s")
                try:
                    numeric_value = int(value)
                except ValueError:
                    numeric_value = None
                if "day" in label:
                    num_days = numeric_value
                elif "photo" in label:
                    num_photos = numeric_value
                elif "event" in label:
                    num_events = numeric_value
                elif "location" in label or "spot" in label:
                    num_locations = numeric_value
    stats_line = " • ".join(stats_line_parts)
    blurb = ""
    if num_days is not None and num_photos is not None:
        ctx = TripSummaryContext(
            num_days=num_days,
            num_photos=num_photos,
            num_events=num_events,
            num_locations=num_locations,
        )
        blurb = build_trip_summary_blurb(ctx)
    location_label = _location_label_for_segments(getattr(layout, "segments", None) or [])

    itinerary_days = getattr(layout, "itinerary_days", None) or []
    place_candidates = getattr(layout, "place_candidates", None) or []
    notable_places = _build_notable_places(place_candidates)
    # Build display labels for the notable places using the unified formatter
    notable_place_labels = [_format_place_name_for_display(p) for p in notable_places]
    logger.info("[TRIP_SUMMARY_PLACES] bullets=%s", notable_place_labels)
    trip_highlight_places = _choose_trip_highlight_places(place_candidates)

    def fmt_date(date_iso: str) -> str:
        try:
            from datetime import datetime

            dt = datetime.fromisoformat(date_iso)
            return dt.strftime("%B %d, %Y")
        except Exception:
            return date_iso

    def fmt_distance(km: Optional[float]) -> str:
        if km is None or km <= 0:
            return ""
        return f"~{km:.1f} km"

    def fmt_hours(hours: Optional[float]) -> str:
        if hours is None or hours <= 0:
            return ""
        return f"{hours:.1f} h"

    day_rows = ""
    if itinerary_days:
        rows: List[str] = []
        for day in itinerary_days:
            date_txt = fmt_date(getattr(day, "date_iso", "") or "")
            locations = getattr(day, "locations", None) or []
            location_labels: List[str] = []
            if locations:
                for loc in locations:
                    label = getattr(loc, "location_short", None) or getattr(
                        loc, "location_full", None
                    )
                    if label:
                        location_labels.append(label)
            location_line = " • ".join(location_labels)
            segments_count = len(getattr(day, "stops", []) or [])
            distance_txt = fmt_distance(getattr(day, "segments_total_distance_km", None))
            hours_txt = fmt_hours(getattr(day, "segments_total_duration_hours", None))
            stats_parts = [
                f"{getattr(day, 'photos_count', 0)} photos",
                f"{segments_count} segments",
            ]
            if distance_txt:
                stats_parts.append(distance_txt)
            if hours_txt:
                stats_parts.append(hours_txt)
            stats_line = " • ".join(stats_parts)
            rows.append(
                f"""
                <div class="trip-summary-day-row">
                    <div class="trip-summary-day-title">Day {getattr(day, 'day_index', '')} — {date_txt}</div>
                    {f'<div class="trip-summary-day-location">{location_line}</div>' if location_line else ''}
                    <div class="trip-summary-day-meta">{stats_line}</div>
                </div>
                """
            )
        day_rows = f'<div class="trip-summary-days">{"".join(rows)}</div>'

    return f"""
    <div class="page trip-summary-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        <style>
            .trip-summary {{
                width: 88%;
                max-width: 190mm;
                margin: 16mm auto;
            }}
            .trip-summary-header {{
                margin-bottom: 12px;
            }}
            .trip-summary-kicker {{
                font-size: 0.8rem;
                letter-spacing: 0.1em;
                text-transform: uppercase;
                margin-bottom: 4px;
            }}
            .trip-summary-title {{
                font-family: {theme.title_font_family};
                font-size: 24pt;
                margin: 0;
            }}
            .trip-summary-dates {{
                margin-top: 4px;
                font-size: 11pt;
                color: #374151;
            }}
            .trip-summary-location {{
                margin-top: 2px;
                font-size: 10pt;
                color: #4b5563;
            }}
            .trip-summary-blurb {{
                font-size: 11pt;
                margin-top: 6px;
                color: #111827;
            }}
            .trip-summary-stats {{
                margin-top: 6px;
                font-size: 10pt;
                color: #374151;
            }}
            .trip-summary-stats span + span {{
                margin-left: 6px;
            }}
            .trip-notable-places {{
                margin-top: 10px;
                font-size: 10pt;
                color: #374151;
            }}
            .trip-notable-places-title {{
                font-weight: 600;
                margin-bottom: 4px;
            }}
            .trip-notable-places-list {{
                list-style: disc;
                padding-left: 18px;
                margin: 0;
            }}
            .trip-notable-places-list li + li {{
                margin-top: 2px;
            }}
            .trip-place-highlights {{
                margin-top: 14px;
                display: flex;
                gap: 8px;
                flex-wrap: wrap;
            }}
            .trip-place-highlight-card {{
                flex: 0 1 calc(33.333% - 6px);
                min-width: 40mm;
                border: 1px solid #d1d5db;
                border-radius: 4px;
                padding: 6px;
                background: #fafafa;
                display: flex;
                flex-direction: column;
                gap: 4px;
            }}
            .trip-place-highlight-name {{
                font-size: 9pt;
                font-weight: 600;
                color: #111827;
                line-height: 1.3;
                word-break: break-word;
            }}
            .trip-place-highlight-thumbs {{
                display: flex;
                gap: 3px;
                flex-wrap: wrap;
            }}
            .trip-place-highlight-thumb {{
                height: 40px;
                width: 40px;
                object-fit: cover;
                border-radius: 2px;
                border: 1px solid #e5e7eb;
            }}
            .trip-summary-days {{
                margin-top: 12px;
            }}
            .trip-summary-day-row + .trip-summary-day-row {{
                margin-top: 10px;
            }}
            .trip-summary-day-title {{
                font-weight: 600;
                font-size: 11pt;
                margin: 0;
            }}
            .trip-summary-day-location {{
                font-size: 10pt;
                color: #4b5563;
            }}
            .trip-summary-day-meta {{
                font-size: 9pt;
                color: #374151;
            }}
        </style>
        <section class="trip-summary">
            <header class="trip-summary-header">
                <div class="trip-summary-kicker">TRIP SUMMARY</div>
                <h1 class="trip-summary-title">{title}</h1>
                {f'<div class="trip-summary-dates">{subtitle}</div>' if subtitle else ''}
                {f'<div class="trip-summary-location">{location_label}</div>' if location_label else ''}
                {f'<div class="trip-summary-blurb">{blurb}</div>' if blurb else ''}
                {f'<div class="trip-summary-stats">' + ' '.join([f'<span>{part}</span>' for part in stats_line_parts]) + '</div>' if stats_line_parts else ''}
            </header>
            {f'''
            <div class="trip-notable-places">
                <div class="trip-notable-places-title">Notable places</div>
                <ul class="trip-notable-places-list">
                    {''.join(f'<li>{label}</li>' for label in notable_place_labels)}
                </ul>
            </div>
            ''' if notable_places else ''}
            {(_render_place_highlight_cards(place_candidates, mode=mode, media_root=media_root, media_base_url=media_base_url) if place_candidates else '')}
            {day_rows}
        </section>
    </div>
    """


def _render_title_page(
    layout: PageLayout,
    theme: Theme,
    width_mm: float,
    height_mm: float,
) -> str:
    """Render a minimal, text-centric title page."""
    bg_color = layout.background_color or theme.background_color

    payload = getattr(layout, "payload", None)
    if isinstance(payload, dict):
        data = payload
    else:
        data = {
            "title": getattr(layout, "title", ""),
            "date_range": getattr(layout, "date_range", ""),
            "stats_line": getattr(layout, "stats_line", ""),
        }

    title = data.get("title", "") or getattr(layout, "title", "") or ""
    date_range = data.get("date_range", "") or ""
    stats_line = data.get("stats_line", "") or ""

    return f"""
    <div class="page front-cover-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        <style>
            .front-cover {{
                min-height: 100%;
                display: flex;
                align-items: center;
                justify-content: center;
                text-align: center;
                padding: 20mm;
            }}
            .front-cover-content {{
                max-width: 170mm;
                margin: 0 auto;
            }}
            .front-cover-title {{
                font-family: {theme.title_font_family};
                font-size: 26pt;
                margin: 0;
            }}
            .front-cover-dates {{
                margin-top: 6px;
                font-size: 12pt;
                color: #374151;
            }}
            .front-cover-subtitle {{
                margin-top: 10px;
                font-size: 11pt;
                color: #4b5563;
            }}
            .front-cover-stats {{
                margin-top: 10px;
                font-size: 10pt;
                color: #555;
            }}
        </style>
        <section class="front-cover">
            <div class="front-cover-content">
                {f'<h1 class="front-cover-title">{title}</h1>' if title else ''}
                {f'<div class="front-cover-dates">{date_range}</div>' if date_range else ''}
                {f'<div class="front-cover-stats">{stats_line}</div>' if stats_line else ''}
            </div>
        </section>
    </div>
    """


def _render_day_intro(
    layout: PageLayout,
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str,
    media_base_url: str | None,
) -> str:
    """Render a chapter-opener style day intro page."""
    bg_color = layout.background_color or theme.background_color
    # Extract text fragments from layout rects
    header = ""
    title = ""
    photos_text = ""
    for elem in layout.elements:
        if elem.font_size and elem.font_size >= 20 and elem.text:
            title = elem.text
        elif elem.font_size and elem.font_size <= 12 and not header and elem.text:
            header = elem.text
        elif elem.font_size and elem.font_size <= 12 and elem.text:
            photos_text = elem.text
    segment_count = getattr(layout, "segment_count", None)
    total_hours = getattr(layout, "segments_total_duration_hours", None)
    total_km = getattr(layout, "segments_total_distance_km", None)
    summary_line = format_day_segment_summary(
        segment_count,
        total_hours,
        total_km,
    )
    segments = getattr(layout, "segments", []) or []
    travel_count = 0
    local_count = 0
    for seg in segments:
        try:
            kind = seg.get("kind")
            if kind == "travel":
                travel_count += 1
            elif kind == "local":
                local_count += 1
        except Exception:
            continue

    tagline_ctx = DayIntroContext(
        photos_count=getattr(layout, "photos_count", 0) or 0,
        segments_total_distance_km=total_km,
        segment_count=segment_count,
        travel_segments_count=travel_count,
        local_segments_count=local_count,
    )
    tagline = build_day_intro_tagline(tagline_ctx)
    segment_items: List[str] = []
    for idx, seg in enumerate(getattr(layout, "segments", []) or []):
        try:
            parts: List[str] = []
            dur_val = seg.get("duration_hours") if isinstance(seg, dict) else None
            dist_val = seg.get("distance_km") if isinstance(seg, dict) else None
            if isinstance(dur_val, (int, float)) and dur_val > 0:
                parts.append(f"{dur_val:.1f} h")
            if isinstance(dist_val, (int, float)) and dist_val > 0:
                parts.append(f"~{dist_val:.1f} km")
            meta = " • ".join(parts)
            segment_items.append(
                f'<li class="day-intro-segment"><span class="day-intro-segment-label">Segment {idx + 1}</span>{f"<span class=\"day-intro-segment-meta\"> • {meta}</span>" if meta else ""}</li>'
            )
        except Exception:
            continue
    location_label = _location_label_for_segments(getattr(layout, "segments", None) or [])

    # Optional mini route image for this day if segments have polylines
    mini_route_src = ""
    segments = getattr(layout, "segments", None) or []
    day_markers = _build_day_route_markers(getattr(layout, "itinerary_day", None))
    day_idx = getattr(layout, "day_index", None)
    place_markers = []
    if day_idx is not None:
        place_markers = _build_day_place_markers(day_idx, getattr(layout, "place_candidates", None) or [])
    all_markers = day_markers + place_markers
    if layout.book_id and segments:
        rel_path, abs_path = map_route_renderer.render_day_route_image(
            layout.book_id,
            segments,
            markers=all_markers,
            width=800,
            height=360,
            filename_prefix=f"day_{layout.page_index}_route",
        )
        if rel_path or abs_path:
            if mode == "pdf":
                mini_route_src = abs_path or ""
            else:
                mini_route_src = _resolve_web_image_url(f"/static/{rel_path}" if rel_path else abs_path, media_base_url)

    # Build a compact stats line
    stats_parts: List[str] = []
    if photos_text:
        stats_parts.append(photos_text)
    elif getattr(layout, "photos_count", None):
        stats_parts.append(f"{layout.photos_count} photos")
    if segment_count is not None:
        stats_parts.append(f"{segment_count} segments")
    if total_km is not None:
        stats_parts.append(f"~{total_km:.1f} km")
    if total_hours is not None:
        stats_parts.append(f"{total_hours:.1f} h")
    stats_line = " • ".join([p for p in stats_parts if p])

    # Build place names text for this day
    place_names_line = ""
    if day_idx is not None:
        place_names_line = _build_day_place_names(day_idx, getattr(layout, "place_candidates", None) or [])

    # Build place cards HTML for this day (if any) and append to the names block
    place_cards_html = ""
    if day_idx is not None:
        place_cards_html = _render_place_highlight_cards(
            getattr(layout, "place_candidates", None) or [],
            day_index=day_idx,
            mode=mode,
            media_root=media_root,
            media_base_url=media_base_url,
        )
    if place_cards_html:
        if place_names_line:
            place_names_line = f"{place_names_line} {place_cards_html}"
        else:
            place_names_line = place_cards_html

    segment_list_html = (
        f'<ul class="day-intro-segments">' + "".join(segment_items) + "</ul>"
        if segment_items
        else ""
    )

    return f"""
    <div class="page day-intro-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        page-break-after: always;
    ">
        <style>
            .day-intro {{
                width: 88%;
                max-width: 190mm;
                margin: 16mm auto;
                display: flex;
                flex-direction: column;
                gap: 10px;
            }}
            .day-intro-header {{
                margin-bottom: 0.75rem;
            }}
            .day-intro-title {{
                font-size: 24pt;
                font-family: {theme.title_font_family};
                margin: 0;
                letter-spacing: 0.2pt;
            }}
            .day-intro-subtitle {{
                font-size: 12pt;
                color: {theme.secondary_color};
                margin: 4px 0 8px 0;
            }}
            .day-intro-tagline {{
                margin: 2px 0 6px 0;
                font-size: 12pt;
                color: {theme.primary_color};
            }}
            .day-intro-stats {{
                font-size: 11pt;
                color: {theme.primary_color};
                margin: 2px 0 10px 0;
            }}
            .day-intro-place-names {{
                font-size: 10pt;
                color: {theme.secondary_color};
                margin: 4px 0 10px 0;
                line-height: 1.4;
            }}
            .day-intro-map {{
                margin: 10px 0 12px 0;
            }}
            .day-intro-map img {{
                width: 100%;
                height: auto;
                border-radius: 8px;
                box-shadow: 0 4px 16px rgba(0, 0, 0, 0.18);
                display: block;
            }}
            .day-intro-segments {{
                list-style: none;
                padding-left: 0;
                margin: 6px 0 0 0;
                font-size: 10pt;
                color: {theme.secondary_color};
            }}
            .day-intro-segment + .day-intro-segment {{
                margin-top: 2px;
            }}
            .day-intro-segment-label {{
                font-weight: 600;
            }}
            .day-intro-segment-meta {{
                margin-left: 4px;
            }}
                    /* Reuse trip-place card styles so day-intro can render the same cards */
                    .trip-place-highlights {{
                        margin-top: 14px;
                        display: flex;
                        gap: 8px;
                        flex-wrap: wrap;
                    }}
                    .trip-place-highlight-card {{
                        flex: 0 1 calc(33.333% - 6px);
                        min-width: 40mm;
                        border: 1px solid #d1d5db;
                        border-radius: 4px;
                        padding: 6px;
                        background: #fafafa;
                        display: flex;
                        flex-direction: column;
                        gap: 4px;
                    }}
                    .trip-place-highlight-name {{
                        font-size: 9pt;
                        font-weight: 600;
                        color: #111827;
                        line-height: 1.3;
                        word-break: break-word;
                    }}
                    .trip-place-highlight-thumbs {{
                        display: flex;
                        gap: 3px;
                        flex-wrap: wrap;
                    }}
                    .trip-place-highlight-thumb {{
                        height: 40px;
                        width: 40px;
                        object-fit: cover;
                        border-radius: 2px;
                        border: 1px solid #e5e7eb;
                    }}
        </style>
        <div class="day-intro">
            <div class="day-intro-header">
                <div style="font-size: 10pt; color: {theme.secondary_color}; text-transform: uppercase; letter-spacing: 0.08em;">{header}</div>
                <h1 class="day-intro-title">{title}</h1>
                {f'<div class=\"day-intro-tagline\">{tagline}</div>' if tagline else ''}
                {f'<div class=\"day-intro-subtitle\">{location_label}</div>' if location_label else ''}
            </div>
            <div class="day-intro-body">
                {f'<div class=\"day-intro-stats\">{stats_line}</div>' if stats_line else ''}
                {f'<div class=\"day-intro-place-names\">{place_names_line}</div>' if place_names_line else ''}
                {f'<div class=\"day-intro-map\"><img src=\"{mini_route_src}\" /></div>' if mini_route_src else ''}
                {segment_list_html}
            </div>
        </div>
    </div>
    """

def _render_photo_spread(
    layout: PageLayout,
    assets: Dict[str, Asset],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str,
    media_base_url: str | None,
) -> str:
    """Render a full-bleed photo spread page."""
    bg_color = layout.background_color or theme.background_color
    spread_slot = getattr(layout, "spread_slot", None)
    asset_id = None
    for elem in layout.elements:
        if elem.asset_id:
            asset_id = elem.asset_id
            break
    if not asset_id and layout.elements and layout.elements[0].image_path:
        # fallback if image_path set directly
        img_path = layout.elements[0].image_path
    else:
        img_path = None

    if asset_id:
        asset = assets.get(asset_id)
        if asset:
            normalized_path = asset.file_path.replace("\\", "/")
            if mode == "pdf":
                candidate_path = Path(normalized_path)
                if not candidate_path.is_absolute():
                    candidate_path = Path(media_root) / candidate_path
                img_path = candidate_path.resolve().as_uri()
            else:
                base = media_base_url.rstrip("/") if media_base_url else "/media"
                img_path = f"{base}/{normalized_path}"

    if not img_path:
        return f"""
    <div class="page" style="width:{width_mm}mm;height:{height_mm}mm;background:{bg_color};display:flex;align-items:center;justify-content:center;page-break-after: always;">
        <div class="text-sm text-muted-foreground">Missing spread image</div>
    </div>
    """

    # Use background positioning to clearly split the image across the spread.
    # Fall back to page parity if spread_slot not provided so web/preview matches PDF
    slot = spread_slot
    if not slot and layout.page_index is not None:
        slot = "left" if layout.page_index % 2 == 0 else "right"
    position = "left center" if slot == "left" else "right center"

    return f"""
    <div class="page" style="position:relative;width:{width_mm}mm;height:{height_mm}mm;background:{bg_color};page-break-after: always;overflow:hidden;">
        <div style="
            width:100%;
            height:100%;
            background-image:url('{img_path}');
            background-size:200% auto;
            background-position:{position};
            background-repeat:no-repeat;
        "></div>
    </div>
    """


def _render_photo_full(
    layout: PageLayout,
    assets: Dict[str, Asset],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str,
    media_base_url: str | None,
) -> str:
    """Render a single hero photo page (full-page, not a spread)."""
    bg_color = layout.background_color or theme.background_color
    asset_id = None
    for elem in layout.elements:
        if elem.asset_id:
            asset_id = elem.asset_id
            break
    if not asset_id and hasattr(layout, "payload"):
        asset_id = layout.payload.get("hero_asset_id") or (
            (layout.payload.get("asset_ids") or [None])[0]
            if isinstance(layout.payload, dict)
            else None
        )
    img_src = ""
    if asset_id and asset_id in assets:
        asset = assets[asset_id]
        normalized_path = asset.file_path.replace("\\", "/")
        if mode == "pdf":
            candidate_path = Path(normalized_path)
            if not candidate_path.is_absolute():
                candidate_path = Path(media_root) / candidate_path
            img_src = candidate_path.resolve().as_uri()
        else:
            base = media_base_url.rstrip("/") if media_base_url else "/media"
            img_src = f"{base}/{normalized_path}"

    body_html = (
        f'<img src="{img_src}" style="display:block;width:100%;height:100%;object-fit:cover;" />'
        if img_src
        else '<div class="text-muted-foreground text-sm">Missing image</div>'
    )

    return f"""
    <div class="page page--full-page-photo" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        page-break-after: always;
        overflow: hidden;
    ">
        <div class="page-inner" style="width:100%;height:100%;">
            {body_html}
        </div>
    </div>
    """
def _render_page_html(
    layout: PageLayout,
    assets: Dict[str, Asset],
    theme: Theme,
    width_mm: float,
    height_mm: float,
    media_root: str,
    mode: str = "web",
    media_base_url: str | None = None,
) -> str:
    """Render a single page to HTML."""
    if layout.page_type == PageType.TITLE_PAGE:
        return _render_title_page(layout, theme, width_mm, height_mm)
    if layout.page_type == PageType.BLANK:
        return _render_blank_page(theme, width_mm, height_mm)
    if layout.page_type == PageType.MAP_ROUTE:
        return _render_map_route_card(layout, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type == PageType.TRIP_SUMMARY:
        return _render_trip_summary_card(layout, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type == PageType.PHOTO_GRID:
        return _render_photo_grid_from_elements(layout, assets, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type == PageType.DAY_INTRO:
        return _render_day_intro(layout, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type == PageType.PHOTO_SPREAD:
        return _render_photo_spread(layout, assets, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type in (PageType.PHOTO_FULL, PageType.FULL_PAGE_PHOTO) or getattr(layout, "page_type", None) == "full_page_photo":
        return _render_photo_full(layout, assets, theme, width_mm, height_mm, media_root, mode, media_base_url)

    bg_color = layout.background_color or theme.background_color
    
    elements_html = []
    for elem in layout.elements:
        if elem.image_path or elem.image_url:
            if mode == "pdf":
                img_path = elem.image_path or ""
            else:
                img_path = _resolve_web_image_url(elem.image_url or "", media_base_url)
            if img_path:
                elements_html.append(f"""
                    <div style="
                        position: absolute;
                        left: {elem.x_mm}mm;
                        top: {elem.y_mm}mm;
                        width: {elem.width_mm}mm;
                        height: {elem.height_mm}mm;
                        overflow: hidden;
                    ">
                        <img src="{img_path}" style="
                            width: 100%;
                            height: 100%;
                            object-fit: cover;
                        " />
                    </div>
                """)
        elif elem.asset_id and elem.asset_id in assets:
            asset = assets[elem.asset_id]
            # Path handling based on render mode
            normalized_path = asset.file_path.replace("\\", "/")
            if mode == "pdf":
                # Use filesystem-relative path (WeasyPrint resolves via base_url)
                img_path = normalized_path
            else:
                base = media_base_url.rstrip("/") if media_base_url else "/media"
                img_path = f"{base}/{normalized_path}"
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    overflow: hidden;
                ">
                    <img src="{img_path}" style="
                        width: 100%;
                        height: 100%;
                        object-fit: cover;
                    " />
                </div>
            """)
        elif elem.text:
            # Text element
            color = elem.color or theme.primary_color
            font_size = elem.font_size or 12
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    color: {color};
                    font-size: {font_size}pt;
                    font-family: {theme.title_font_family if font_size > 14 else theme.font_family};
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    text-align: center;
                ">
                    {elem.text}
                </div>
            """)
        elif elem.color:
            # Colored rectangle (overlay)
            elements_html.append(f"""
                <div style="
                    position: absolute;
                    left: {elem.x_mm}mm;
                    top: {elem.y_mm}mm;
                    width: {elem.width_mm}mm;
                    height: {elem.height_mm}mm;
                    background: {elem.color};
                "></div>
            """)
    
    return f"""
        <div class="page" style="
            width: {width_mm}mm;
            height: {height_mm}mm;
            background: {bg_color};
            position: relative;
            page-break-after: always;
            overflow: hidden;
        ">
            {''.join(elements_html)}
        </div>
    """


def _resolve_web_image_url(raw_path: str, media_base_url: str | None) -> str:
    """
    Ensure image URLs inside srcDoc HTML point to the backend origin.

    Args:
        raw_path: Path stored in the layout (may be /static/... or relative)
        media_base_url: Absolute base URL to /media (e.g., http://localhost:8000/media)
    """
    if not raw_path:
        return ""
    # Already an absolute URL or data URI — return as-is
    if raw_path.startswith(("http://", "https://", "data:")):
        return raw_path

    # Determine the origin (e.g., http://localhost:8000) from media_base_url when available
    origin = ""
    if media_base_url:
        if "/media" in media_base_url:
            origin = media_base_url.split("/media")[0].rstrip("/")
        else:
            origin = media_base_url.rstrip("/")

    # If the raw path refers to a static asset (served from /static), preserve the /static path
    rp = raw_path.lstrip("/")
    if rp.startswith("static/"):
        return f"{origin}/{rp}" if origin else f"/{rp}"

    # If the raw path already contains a leading media/ segment, trim it and construct a /media URL
    if rp.startswith("media/"):
        rp = rp[len("media/"):]

    # Default: return URL under /media
    base = f"{origin}/media" if origin else "/media"
    return f"{base}/{rp}"


def _generate_print_css(context: RenderContext) -> str:
    """Generate CSS for print output."""
    return f"""
        @page {{
            size: {context.page_width_mm}mm {context.page_height_mm}mm;
            margin: 0;
        }}
        
        * {{
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }}
        
        body {{
            margin: 0;
            padding: 0;
        }}
        
        .page {{
            overflow: hidden;
        }}
        
        .page:last-child {{
            page-break-after: avoid;
        }}
    """


def _create_placeholder_pdf(output_path: str, book: Book, layouts: List[PageLayout]) -> str:
    """
    Create a simple placeholder PDF when WeasyPrint is not available.
    Uses reportlab as a fallback, or creates an empty file.
    """
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.pdfgen import canvas
        
        c = canvas.Canvas(output_path, pagesize=letter)
        
        for i, layout in enumerate(layouts):
            if i > 0:
                c.showPage()
            
            c.setFont("Helvetica", 16)
            c.drawString(72, 720, f"{book.title}")
            c.setFont("Helvetica", 12)
            c.drawString(72, 700, f"Page {i + 1} of {len(layouts)}")
            c.drawString(72, 680, f"Type: {layout.page_type.value}")
            
            if layout.elements:
                c.drawString(72, 660, f"Elements: {len(layout.elements)}")
        
        c.save()
        return output_path
        
    except ImportError:
        # No PDF library available, create empty file with info
        with open(output_path, 'w') as f:
            f.write(f"PDF generation requires WeasyPrint or reportlab.\n")
            f.write(f"Book: {book.title}\n")
            f.write(f"Pages: {len(layouts)}\n")
        return output_path
