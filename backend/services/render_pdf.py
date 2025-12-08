"""
PDF rendering service.

Renders the book layouts to a print-ready PDF file.
Uses HTML/CSS rendering via WeasyPrint for flexibility.
"""
import os
import logging
from pathlib import Path
from typing import Dict, List, Optional, Any
from domain.models import Asset, Book, PageLayout, PageType, RenderContext, Theme
from services import map_route_renderer
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


def build_day_intro_tagline(
    segment_count: Optional[int],
    total_hours: Optional[float],
    total_km: Optional[float],
) -> str:
    """
    Mirror the frontend's day intro narrative line.
    Example: "Big travel day  8.4 h out and about • ~1492.6 km traveled"
    """
    hours = total_hours or 0.0
    km = total_km or 0.0
    count = segment_count or 0
    far = km >= 100
    medium = 10 <= km < 100
    long_day = hours >= 8
    short_day = hours < 3

    label = "Easygoing day"
    if far:
        label = "Big travel day"
    elif long_day and medium:
        label = "Full-day exploring"
    elif short_day and km < 5:
        label = "Chill day nearby"
    elif long_day:
        label = "Long day out"
    elif medium:
        label = "Out and about"

    # If there's really no movement/segments, skip
    if count <= 0 and hours <= 0 and km <= 0:
        return ""

    duration_label = f"{hours:.1f} h out and about"
    distance_label = f"~{km:.1f} km traveled" if km > 0 else ""
    parts = [label, duration_label]
    if distance_label:
        parts.append(distance_label)

    if len(parts) == 2:
        return "  ".join(parts)
    if len(parts) == 3:
        return "  ".join(parts[:2]) + f" • {parts[2]}"
    return ""


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

    for elem in layout.elements:
        img_src = ""
        if elem.image_path or elem.image_url:
            if mode == "pdf":
                candidate = elem.image_path or ""
                if candidate:
                    candidate_path = Path(candidate)
                    if not candidate_path.is_absolute():
                        candidate_path = Path(media_root) / candidate_path
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
                img_src = candidate_path.resolve().as_uri()
            else:
                base = media_base_url.rstrip("/") if media_base_url else "/media"
                img_src = f"{base}/{normalized_path}"

        if img_src:
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
                    <img src="{img_src}" style="width:100%;height:100%;object-fit:cover;" />
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
    for layout in layouts:
        logger.debug(
            "[render_pdf] page index=%s type=%s hero=%s assets=%s layout_variant=%s",
            layout.page_index,
            layout.page_type,
            layout.payload.get('hero_asset_id') if hasattr(layout, 'payload') else None,
            layout.payload.get('asset_ids') if hasattr(layout, 'payload') else None,
            getattr(layout, "layout_variant", None),
        )
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
    title = "Trip route"
    stats_lines: List[str] = []

    for elem in layout.elements:
        if (elem.image_path or elem.image_url) and not image_src:
            if mode == "pdf":
                image_src = elem.image_path or ""
            else:
                image_src = _resolve_web_image_url(elem.image_url or "", media_base_url)
        elif elem.text:
            # First text element is the title; others become subtitle lines
            if title == "Trip route" and elem.text.lower().startswith("trip route"):
                title = elem.text
            else:
                stats_lines.append(elem.text)

    subtitle = " • ".join(stats_lines)

    segments = getattr(layout, "segments", []) or []
    seg_count = len(segments)
    seg_total_hours = sum((s.get("duration_hours") or 0.0) for s in segments)
    seg_total_km = sum((s.get("distance_km") or 0.0) for s in segments)
    seg_summary = format_day_segment_summary(seg_count, seg_total_hours, seg_total_km)

    figure_html = ""
    if image_src:
        figure_html = f"""
            <figure class="map-route-figure">
                <img src="{image_src}" alt="Trip route map" />
            </figure>
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
            .map-route-card {{
                max-width: 190mm;
                width: 88%;
                margin: 18mm auto 18mm;
                padding: 14mm 12mm;
                background: #f8fafc;
                border: 1px solid #d9e2ec;
                border-radius: 10px;
                box-shadow: 0 14px 40px rgba(15, 23, 42, 0.14);
                display: flex;
                flex-direction: column;
                gap: 6mm;
                align-items: center;
                text-align: center;
            }}
            .map-route-title {{
                font-family: {theme.title_font_family};
                font-size: 24pt;
                letter-spacing: 0.2pt;
                margin: 0;
                color: {theme.primary_color};
            }}
            .map-route-subtitle {{
                font-size: 12pt;
                color: {theme.secondary_color};
                margin: 0;
            }}
            .map-route-figure {{
                margin: 0;
                width: 100%;
                background: #0b111c;
                border-radius: 8px;
                border: 1px solid #cbd5e1;
                box-shadow: 0 12px 30px rgba(15, 23, 42, 0.18);
                padding: 6mm;
                max-height: 130mm;
                overflow: hidden;
            }}
            .map-route-figure img {{
                width: 100%;
                height: auto;
                max-height: 118mm;
                display: block;
                border-radius: 6px;
                object-fit: contain;
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
            .map-route-segment-summary {{
                margin: 6px 0 4px 0;
                font-size: 12pt;
                color: {theme.primary_color};
                text-align: center;
            }}
        </style>
        <div class="map-route-card">
            <h1 class="map-route-title">{title}</h1>
            <p class="map-route-subtitle">{subtitle}</p>
            {figure_html}
            {f'<div class=\"map-route-segment-summary\">{seg_summary}</div>' if seg_summary else ''}
        </div>
    </div>
    """


def _render_trip_summary_card(
    layout: PageLayout,
    theme: Theme,
    width_mm: float,
    height_mm: float,
) -> str:
    """Render trip summary with card styling consistent with map route."""
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
    stats_line = " • ".join(stats_line_parts)

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
            .trip-summary-page {{
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: flex-start;
            }}
            .trip-summary-card {{
                max-width: 190mm;
                width: 88%;
                margin: 18mm auto 18mm;
                padding: 14mm 12mm;
                background: #f8fafc;
                border: 1px solid #d9e2ec;
                border-radius: 10px;
                box-shadow: 0 14px 40px rgba(15, 23, 42, 0.14);
                display: flex;
                flex-direction: column;
                gap: 6mm;
                align-items: center;
                text-align: center;
            }}
            .trip-summary-title {{
                font-family: {theme.title_font_family};
                font-size: 24pt;
                letter-spacing: 0.2pt;
                margin: 0;
                color: {theme.primary_color};
            }}
            .trip-summary-subtitle {{
                font-size: 12pt;
                color: {theme.secondary_color};
                margin: 0;
            }}
            .trip-summary-meta {{
                font-size: 12pt;
                color: {theme.secondary_color};
                margin: 4mm 0 0 0;
            }}
        </style>
        <div class="trip-summary-card">
            <h1 class="trip-summary-title">{title}</h1>
            <p class="trip-summary-subtitle">{subtitle}</p>
            {f'<p class=\"trip-summary-meta\">{stats_line}</p>' if stats_line else ''}
        </div>
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
    """Render a simple day intro page."""
    bg_color = layout.background_color or theme.background_color
    day_index = layout.elements and layout.elements[0]  # unused, payload holds info
    payload = {}
    # payload not available directly on layout; rely on .page_content in elements is not accessible here.
    # Use layout.page_type specific data: stored in layout? Not available; use layout.elements? Instead,
    # fallback to reading from layout via attributes set in book planner payload when creating PageLayout.
    day_idx = layout.elements and layout.elements[0].text if layout.elements else ""
    # Since LayoutRects already hold text, build HTML from PageLayout elements directly.
    header = ""
    title = ""
    photos = ""
    for elem in layout.elements:
        if elem.font_size and elem.font_size >= 20:
            title = elem.text
        elif elem.font_size and elem.font_size <= 12 and not header:
            header = elem.text
        elif elem.font_size and elem.font_size <= 12:
            photos = elem.text
    segment_count = getattr(layout, "segment_count", None)
    total_hours = getattr(layout, "segments_total_duration_hours", None)
    total_km = getattr(layout, "segments_total_distance_km", None)
    summary_line = format_day_segment_summary(
        segment_count,
        total_hours,
        total_km,
    )
    tagline = build_day_intro_tagline(
        segment_count,
        total_hours,
        total_km,
    )
    segment_lines: List[str] = []
    for idx, seg in enumerate(getattr(layout, "segments", []) or []):
        try:
            segment_lines.append(format_segment_line(idx + 1, seg))
        except Exception:
            continue

    # Optional mini route image for this day if segments have polylines
    mini_route_src = ""
    segments = getattr(layout, "segments", None) or []
    if layout.book_id and segments:
        rel_path, abs_path = map_route_renderer.render_day_route_image(
            layout.book_id,
            segments,
            width=800,
            height=360,
            filename_prefix=f"day_{layout.page_index}_route",
        )
        if rel_path or abs_path:
            if mode == "pdf":
                mini_route_src = abs_path or ""
            else:
                mini_route_src = _resolve_web_image_url(f"/static/{rel_path}" if rel_path else abs_path, media_base_url)

    return f"""
    <div class="page day-intro-page" style="
        position: relative;
        width: {width_mm}mm;
        height: {height_mm}mm;
        background: {bg_color};
        font-family: {theme.font_family};
        color: {theme.primary_color};
        display: flex;
        align-items: center;
        justify-content: center;
        page-break-after: always;
    ">
        <style>
            .day-intro-center {{
                text-align: center;
                display: flex;
                flex-direction: column;
                gap: 6px;
            }}
            .day-intro-photos {{
                margin-top: 6px;
                margin-bottom: 10px;
            }}
            .day-intro-tagline {{
                margin-top: 6px;
                margin-bottom: 6px;
            }}
            .day-intro-summary {{
                margin-top: 4px;
                margin-bottom: 6px;
            }}
            .day-intro-segments {{
                list-style: disc;
                list-style-position: outside;
                margin: 8px auto 0;
                padding: 0 18px;
                text-align: left;
                max-width: 80%;
                font-size: 10pt;
                color: {theme.secondary_color};
            }}
            .day-intro-segments li {{
                margin: 2px 0;
            }}
            .day-intro-mini-map-wrapper {{
                margin-top: 10mm;
                margin-bottom: 8mm;
                text-align: center;
            }}
            .day-intro-mini-map {{
                max-width: 100%;
                max-height: 60mm;
                border-radius: 4px;
                display: inline-block;
            }}
        </style>
        <div class="day-intro-center">
            <div style="font-size: 12pt; color: {theme.secondary_color}; text-transform: uppercase; letter-spacing: 0.08em;">{header}</div>
            <div style="font-size: 24pt; font-family: {theme.title_font_family}; color: {theme.primary_color};">{title}</div>
            {f'<div class=\"day-intro-photos\" style=\"font-size: 12pt; color: {theme.secondary_color};\">{photos}</div>' if photos else ''}
            {f'<div class=\"day-intro-tagline\" style=\"font-size: 11pt; color: {theme.primary_color};\">{tagline}</div>' if tagline else ''}
            {f'<div class=\"day-intro-summary\" style=\"font-size: 11pt; color: {theme.primary_color};\">{summary_line}</div>' if summary_line else ''}
            {f'<div class=\"day-intro-mini-map-wrapper\"><img class=\"day-intro-mini-map\" src=\"{mini_route_src}\" /></div>' if mini_route_src else ''}
            {f'<ul class=\"day-intro-segments\">' + ''.join([f'<li>{line}</li>' for line in segment_lines]) + '</ul>' if segment_lines else ''}
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
    if layout.page_type == PageType.BLANK:
        return _render_blank_page(theme, width_mm, height_mm)
    if layout.page_type == PageType.MAP_ROUTE:
        return _render_map_route_card(layout, theme, width_mm, height_mm, media_root, mode, media_base_url)
    if layout.page_type == PageType.TRIP_SUMMARY:
        return _render_trip_summary_card(layout, theme, width_mm, height_mm)
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
    if raw_path.startswith(("http://", "https://", "data:")):
        return raw_path

    origin = ""
    if media_base_url:
        if "/media" in media_base_url:
            origin = media_base_url.split("/media")[0].rstrip("/")
        else:
            origin = media_base_url.rstrip("/")

    if raw_path.startswith("/"):
        return f"{origin}{raw_path}" if origin else raw_path

    return f"{origin}/{raw_path}" if origin else raw_path


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
