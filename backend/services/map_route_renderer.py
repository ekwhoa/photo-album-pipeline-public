"""
Route map renderer using Pillow (schematic).

Generates a static PNG for map route pages.
Focuses on the dominant trip cluster and exaggerates skinny routes.
"""
import os
import math
import sqlite3
import threading
import time
from dataclasses import dataclass
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from statistics import median
from typing import List, Tuple, Sequence, Optional, Any

import requests
from PIL import Image, ImageDraw, ImageFont, ImageFilter


BASE_DIR = Path(__file__).resolve().parents[1]
UPSCALE_FACTOR = 4

# Tile configuration
MAP_TILES_ENABLED = os.getenv("MAP_TILES_ENABLED", "0") in ("1", "true", "TRUE")
MAP_TILE_URL_TEMPLATE = os.getenv("MAP_TILE_URL_TEMPLATE", "")
MAP_TILE_USER_AGENT = os.getenv(
    "MAP_TILE_USER_AGENT",
    os.getenv("NOMINATIM_USER_AGENT", "photo-album-pipeline/1.0 (tile-fetch)"),
)
MAP_TILE_REFERER = os.getenv("MAP_TILE_REFERER")
MAP_TILE_TIMEOUT = float(os.getenv("MAP_TILE_TIMEOUT", "3"))
MAP_RENDER_TIMEOUT = float(os.getenv("MAP_RENDER_TIMEOUT", "25"))
MAP_TILE_MIN_INTERVAL_SEC = float(os.getenv("MAP_TILE_MIN_INTERVAL_SEC", "1.0"))
MAP_TILE_HEADERS = {"User-Agent": MAP_TILE_USER_AGENT}
if MAP_TILE_REFERER:
    MAP_TILE_HEADERS["Referer"] = MAP_TILE_REFERER
_TILE_SESSION = requests.Session()
_TILE_LOCK = threading.Lock()
_LAST_TILE_TS = 0.0
MAP_TILE_CACHE_PATH = Path(
    os.getenv("MAP_TILE_CACHE_PATH", str(BASE_DIR / "tile_cache.sqlite"))
)
MAP_TILE_CACHE_TTL_SECONDS = int(os.getenv("MAP_TILE_CACHE_TTL_SECONDS", str(30 * 24 * 3600)))
_CACHE_DB_LOCK = threading.Lock()
_CACHE_DB: Optional[sqlite3.Connection] = None

# Directories
DATA_DIR = BASE_DIR / "data"
MAP_OUTPUT_DIR = DATA_DIR / "maps"
DEBUG_MAP_RENDERING = True

# Ensure directories exist
MAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Route / map styling
ROUTE_OUTLINE_COLOR = (0, 0, 0, 180)
ROUTE_OUTLINE_EXTRA_WIDTH = 2
ROUTE_SHADOW_COLOR = (0, 0, 0, 180)
ROUTE_GLOW_COLOR = (255, 255, 255, 235)
ROUTE_MARKER_FILL = (255, 255, 255, 255)
ROUTE_MARKER_OUTLINE = (0, 0, 0, 220)
ROUTE_MARKER_RADIUS = 10
ROUTE_POI_LOCAL_RADIUS = 6
ROUTE_POI_TRAVEL_RADIUS = 4
ROUTE_POI_LOCAL_OUTLINE = (0, 0, 0, 230)
ROUTE_POI_TRAVEL_OUTLINE = (70, 70, 70, 220)
ROUTE_CANVAS_PADDING_PX = 24
LEGEND_MARGIN_PX = 16
TILE_DARKEN_OVERLAY = (0, 0, 0, 170)
MARKER_RADIUS_LOCAL = 6
MARKER_RADIUS_TRAVEL = 4
MARKER_OUTLINE_WIDTH_LOCAL = 3
MARKER_OUTLINE_WIDTH_TRAVEL = 2


@dataclass
class RouteMarker:
    lat: float
    lon: float
    kind: str  # e.g. "local" or "travel"

# TODO(map-v2): explore further smoothing/anti-aliasing for extreme zoom levels,
# or switching to an SVG/vector-based route renderer if we ever need ultra-high DPI.
def render_route_map(
    book_id: str,
    points: List[Tuple[float, float]],
    markers: Optional[List[RouteMarker]] = None,
) -> Tuple[str, str]:
    """
    Render a static PNG map for the given route points.

    Args:
        book_id: Book identifier (used for filename)
        points: Ordered list of (lat, lon) tuples

    Returns:
        (relative_path, absolute_path). Empty strings if rendering fails or insufficient points.
        relative_path is relative to the static mount root (data/).
    """
    return _render_route_image(
        book_id,
        points,
        markers=markers,
        width=1600,
        height=1000,
        filename_prefix="route",
    )


def render_trip_route_map(
    book_id: str,
    points: List[Tuple[float, float]],
    markers: Optional[List[RouteMarker]] = None,
) -> Tuple[str, str]:
    """
    Render a static PNG map for the given route points (trip-wide helper).
    """
    return render_route_map(book_id, points, markers=markers)


def render_day_route_image(
    book_id: str,
    segments: Sequence[dict],
    width: int = 900,
    height: int = 300,
    filename_prefix: Optional[str] = None,
    markers: Optional[List[RouteMarker]] = None,
) -> Tuple[str, str]:
    """
    Render a smaller route image for a single day using only that day's segment polylines.
    """
    points: List[Tuple[float, float]] = []
    for seg in segments or []:
        poly = seg.get("polyline") or []
        if len(poly) >= 2:
            points.extend([(lat, lon) for lat, lon in poly])
    if filename_prefix is None:
        filename_prefix = "day_route"
    return _render_route_image(
        book_id,
        points,
        markers=markers,
        width=width,
        height=height,
        filename_prefix=filename_prefix,
    )


def render_day_route_map(
    book_id: str,
    segments: Sequence[dict],
    markers: Optional[List[RouteMarker]] = None,
) -> Tuple[str, str]:
    """
    Public helper to mirror render_route_map but for a day's segments.
    Returns (relative_path, absolute_path).
    """
    return render_day_route_image(
        book_id,
        segments,
        markers=markers,
        width=900,
        height=300,
        filename_prefix="day_route",
    )


def _get_tile_db() -> sqlite3.Connection:
    """Lazily open the tile cache DB and ensure schema exists."""
    global _CACHE_DB
    with _CACHE_DB_LOCK:
        if _CACHE_DB is None:
            MAP_TILE_CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_DB = sqlite3.connect(str(MAP_TILE_CACHE_PATH))
            _CACHE_DB.execute(
                """
                CREATE TABLE IF NOT EXISTS tiles (
                    z INTEGER,
                    x INTEGER,
                    y INTEGER,
                    fetched_at INTEGER,
                    data BLOB,
                    PRIMARY KEY (z, x, y)
                )
                """
            )
            _CACHE_DB.commit()
        return _CACHE_DB


def _get_tile_from_cache(z: int, x: int, y: int) -> Optional[bytes]:
    """Fetch tile bytes from SQLite cache if present and not expired."""
    try:
        db = _get_tile_db()
        cur = db.execute(
            "SELECT fetched_at, data FROM tiles WHERE z=? AND x=? AND y=?",
            (z, x, y),
        )
        row = cur.fetchone()
        if not row:
            return None
        fetched_at, data = row
        if MAP_TILE_CACHE_TTL_SECONDS > 0:
            age = time.time() - (fetched_at or 0)
            if age > MAP_TILE_CACHE_TTL_SECONDS:
                return None
        print(f"[MAP] tile sqlite cache hit {z}/{x}/{y}")
        return data
    except Exception as exc:
        print(f"[MAP] Tile cache read failed for {z}/{x}/{y}: {exc}")
        return None


def _store_tile_in_cache(z: int, x: int, y: int, data: bytes) -> None:
    """Store tile bytes in SQLite cache."""
    try:
        db = _get_tile_db()
        db.execute(
            "INSERT OR REPLACE INTO tiles (z, x, y, fetched_at, data) VALUES (?, ?, ?, ?, ?)",
            (z, x, y, int(time.time()), data),
        )
        db.commit()
        print(f"[MAP] tile sqlite cache store {z}/{x}/{y}")
    except Exception as exc:
        print(f"[MAP] Tile cache write failed for {z}/{x}/{y}: {exc}")


def _fetch_tile_http(z: int, x: int, y: int) -> Optional[Image.Image]:
    """
    Fetch a single tile via HTTP with rate limiting.
    Returns a PIL Image or None on error.
    """
    global _LAST_TILE_TS

    if not MAP_TILES_ENABLED or not MAP_TILE_URL_TEMPLATE:
        return None

    url = MAP_TILE_URL_TEMPLATE.format(z=z, x=x, y=y)

    with _TILE_LOCK:
        now = time.time()
        elapsed = now - _LAST_TILE_TS
        if elapsed < MAP_TILE_MIN_INTERVAL_SEC:
            time.sleep(MAP_TILE_MIN_INTERVAL_SEC - elapsed)
        _LAST_TILE_TS = time.time()
        try:
            resp = _TILE_SESSION.get(
                url, headers=MAP_TILE_HEADERS, timeout=MAP_TILE_TIMEOUT
            )
            resp.raise_for_status()
        except requests.RequestException as exc:
            print(f"[MAP] Tile fetch failed for {url}: {exc}")
            return None

    try:
        from io import BytesIO

        return Image.open(BytesIO(resp.content)).convert("RGB")
    except Exception as exc:
        print(f"[MAP] Tile decode failed for {url}: {exc}")
        return None


@lru_cache(maxsize=512)
def _fetch_tile_cached(z: int, x: int, y: int) -> Optional[Image.Image]:
    """Cached tile fetch; wraps the throttled HTTP helper."""
    cached_bytes = _get_tile_from_cache(z, x, y)
    if cached_bytes:
        try:
            print(f"[MAP] tile cache hit {z}/{x}/{y}")
            return Image.open(BytesIO(cached_bytes)).convert("RGB")
        except Exception as exc:
            print(f"[MAP] Tile cache decode failed for {z}/{x}/{y}: {exc}")
    else:
        print(f"[MAP] tile cache miss {z}/{x}/{y}")

    img = _fetch_tile_http(z, x, y)
    if img is not None:
        try:
            buf = BytesIO()
            img.save(buf, format="PNG")
            _store_tile_in_cache(z, x, y, buf.getvalue())
        except Exception as exc:
            print(f"[MAP] Tile cache store failed for {z}/{x}/{y}: {exc}")
    return img


def _latlon_to_tile_xy(lat: float, lon: float, zoom: int) -> Tuple[float, float]:
    """Convert lat/lon to fractional Web Mercator tile coords."""
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n
    y = (1.0 - math.log(math.tan(lat_rad) + 1.0 / math.cos(lat_rad)) / math.pi) / 2.0 * n
    return x, y


def _draw_tile_background(
    img: Image.Image,
    bbox: dict[str, float],
) -> bool:
    """
    Attempt to draw a tile background behind the route.
    Returns True if tiles were drawn, False to fall back.
    """
    if not MAP_TILES_ENABLED or not MAP_TILE_URL_TEMPLATE:
        return False

    lat_min = bbox.get("min_lat")
    lat_max = bbox.get("max_lat")
    lon_min = bbox.get("min_lon")
    lon_max = bbox.get("max_lon")
    if None in (lat_min, lat_max, lon_min, lon_max):
        return False

    lat_span = max(1e-6, abs(lat_max - lat_min))
    lon_span = max(1e-6, abs(lon_max - lon_min))
    approx_span = max(lat_span, lon_span)

    if approx_span > 10:
        zoom = 7
    elif approx_span > 2:
        zoom = 9
    elif approx_span > 0.5:
        zoom = 11
    else:
        zoom = 13

    x1f, y1f = _latlon_to_tile_xy(lat_max, lon_min, zoom)
    x2f, y2f = _latlon_to_tile_xy(lat_min, lon_max, zoom)
    x_min, x_max = int(math.floor(min(x1f, x2f))), int(math.floor(max(x1f, x2f)))
    y_min, y_max = int(math.floor(min(y1f, y2f))), int(math.floor(max(y1f, y2f)))

    tile_size = 256
    span_px_x = (x_max - x_min + 1) * tile_size
    span_px_y = (y_max - y_min + 1) * tile_size
    scale = min(img.width / span_px_x, img.height / span_px_y)
    if scale <= 0:
        return False
    scaled_tile_size = max(1, int(tile_size * scale))
    offset_x = int((img.width - span_px_x * scale) / 2)
    offset_y = int((img.height - span_px_y * scale) / 2)

    any_tile = False
    for ty in range(y_min, y_max + 1):
        for tx in range(x_min, x_max + 1):
            tile = _fetch_tile_cached(zoom, tx, ty)
            if tile is None:
                continue
            any_tile = True
            tile_resized = tile.resize((scaled_tile_size, scaled_tile_size), Image.BICUBIC)
            px = offset_x + int((tx - x_min) * scaled_tile_size)
            py = offset_y + int((ty - y_min) * scaled_tile_size)
            img.paste(tile_resized, (px, py))

    return any_tile


def _apply_tile_overlay(bg: Image.Image) -> None:
    """Slightly darken the tile background so the route stands out."""
    base = bg
    if base.mode != "RGBA":
        base = base.convert("RGBA")
    overlay = Image.new("RGBA", base.size, TILE_DARKEN_OVERLAY)
    darkened = Image.alpha_composite(base, overlay)
    bg.paste(darkened)


def _compute_route_width(size: Tuple[int, int]) -> int:
    """Derive a base stroke width relative to canvas size."""
    w, h = size
    # Slightly larger base width for better print visibility
    base = min(w, h) // 35
    return max(8, min(base, 20))


def _draw_route_markers(
    draw: ImageDraw.ImageDraw,
    points: Sequence[Tuple[float, float]],
    base_width: int,
    start_outline: Tuple[int, int, int, int],
    end_outline: Tuple[int, int, int, int],
) -> None:
    """Draw neutral start/end markers so they work on tiles or grid."""
    if not points:
        return
    start = points[0]
    end = points[-1]
    r = max(ROUTE_MARKER_RADIUS, int(base_width * 1.4))
    for (x, y), outline in ((start, start_outline), (end, end_outline)):
        bbox = (x - r, y - r, x + r, y + r)
        draw.ellipse(bbox, fill=ROUTE_MARKER_FILL, outline=outline, width=1)


def _render_route_image(
    book_id: str,
    points: Sequence[Tuple[float, float]],
    width: int,
    height: int,
    filename_prefix: str = "route",
    markers: Optional[List[RouteMarker]] = None,
) -> Tuple[str, str]:
    """
    Shared rendering logic for trip and day maps.
    """
    if len(points) < 2:
        return "", ""

    print(f"[MAP] Starting render for book {book_id}: {len(points)} raw points")

    # Preserve original ordering
    indexed_points = [(idx, lat, lon) for idx, (lat, lon) in enumerate(points)]

    try:
        clusters = _cluster_points(indexed_points, radius_km=40.0)
        main_cluster = _select_dominant_cluster(clusters, len(indexed_points))
        cluster_points = _filter_points_in_cluster(indexed_points, main_cluster)
        ignored_by_cluster = len(points) - len(cluster_points)

        if len(cluster_points) < 2:
            core_points = [(lat, lon) for _, lat, lon in indexed_points]
        else:
            center_lat = sum(lat for lat, _ in cluster_points) / len(cluster_points)
            center_lon = sum(lon for _, lon in cluster_points) / len(cluster_points)

            distances = [
                _haversine_km(lat, lon, center_lat, center_lon) for lat, lon in cluster_points
            ]
            median_distance_km = median(distances)
            max_core_distance_km = max(5.0, 3 * median_distance_km)

            trimmed_points = [
                (lat, lon)
                for (lat, lon), dist in zip(cluster_points, distances)
                if dist <= max_core_distance_km
            ]

            if len(trimmed_points) < 2:
                core_points = cluster_points
            else:
                core_points = trimmed_points

        if ignored_by_cluster > 0:
            print(f"[MAP] Using dominant cluster with {len(cluster_points)} points; ignored {ignored_by_cluster} far-off points for rendering")
        else:
            print(f"[MAP] Using dominant cluster with {len(cluster_points)} points; no points ignored")

        simplified_points = simplify_route(core_points, max_points=25, min_distance_km=0.1)
        print(
            f"[MAP] Simplified route (raw {len(points)} -> cluster {len(core_points)} -> "
            f"{len(simplified_points)} points) targeting ~20-30 pts"
        )

        bbox = _compute_bbox(simplified_points)
        target_aspect = max((width - 2 * max(70, ROUTE_CANVAS_PADDING_PX)) / max(height - 2 * max(70, ROUTE_CANVAS_PADDING_PX), 1), 1e-3)
        min_lat_n, max_lat_n, min_lon_n, max_lon_n = _normalize_bbox_aspect(
            bbox["min_lat"], bbox["max_lat"], bbox["min_lon"], bbox["max_lon"], target_aspect
        )
        bbox.update(
            {
                "min_lat": min_lat_n,
                "max_lat": max_lat_n,
                "min_lon": min_lon_n,
                "max_lon": max_lon_n,
            }
        )
        print(
            f"[MAP] BBox lat({bbox['min_lat']:.4f},{bbox['max_lat']:.4f}) "
            f"lon({bbox['min_lon']:.4f},{bbox['max_lon']:.4f}) "
            f"span_lat={bbox['span_lat']:.4f} span_lon={bbox['span_lon']:.4f}"
        )

        img = Image.new("RGB", (width, height), color="#f6f8fa")
        draw = ImageDraw.Draw(img)
        route_width = 6
        route_color = "#2e8bc0"
        margin_px = 90
        coords = _map_points_to_canvas(simplified_points, width, height, margin_px=margin_px, shrink_factor=0.9)

        print(
            f"[MAP] Drawing {len(simplified_points)} core points "
            f"(ignored {len(cluster_points) - len(core_points)} edge points)"
        )

        bg_color = "#050910"
        grid_color = (40, 48, 58, 35)
        grid_spacing = 100
        frame_color = "#1a2433"
        frame_width = 3
        halo_color = (46, 139, 192, 70)
        halo_width = 16
        route_width = 7
        start_color = (64, 224, 208, 255)  # turquoise
        end_color = (244, 114, 182, 255)  # coral/pink
        marker_outline = (255, 255, 255, 60)
        margin_px = max(70, ROUTE_CANVAS_PADDING_PX)
        coords = _map_points_to_canvas(
            simplified_points, width, height, margin_px=margin_px, shrink_factor=0.9, bbox=bbox
        )
        marker_coords_scaled: List[Tuple[float, float]] = []
        if markers:
            marker_points = [(marker.lat, marker.lon) for marker in markers]
            marker_coords = _map_points_to_canvas(
                marker_points,
                width,
                height,
                margin_px=margin_px,
                shrink_factor=0.9,
                bbox=bbox,
            )
            marker_coords_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in marker_coords]
        smoothed_coords = _smooth_polyline(
            coords,
            min_total_points=250,
            max_segment_spacing_px=5.0,
        )

        draw_width, draw_height = width * UPSCALE_FACTOR, height * UPSCALE_FACTOR
        coords_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in coords]
        smoothed_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in smoothed_coords]

        # First try tiles on a transparent base; fall back to the legacy grid if tiles fail.
        background_img = Image.new("RGBA", (draw_width, draw_height), (0, 0, 0, 0))
        bg_draw = ImageDraw.Draw(background_img, "RGBA")

        tiles_ok = False
        try:
            tiles_ok = _draw_tile_background(background_img, bbox)
        except Exception as exc:
            print(f"[MAP] Tile background failed, falling back to grid: {exc}")
            tiles_ok = False

        if tiles_ok:
            _apply_tile_overlay(background_img)
        if not tiles_ok:
            background_img = Image.new("RGBA", (draw_width, draw_height), color=bg_color)
            bg_draw = ImageDraw.Draw(background_img, "RGBA")
            # Subtle grid texture
            grid_step = int(grid_spacing * UPSCALE_FACTOR)
            grid_line_width = max(1, int(1 * UPSCALE_FACTOR / 2))
            for x in range(0, draw_width + 1, grid_step):
                bg_draw.line([(x, 0), (x, draw_height)], fill=grid_color, width=grid_line_width)
            for y in range(0, draw_height + 1, grid_step):
                bg_draw.line([(0, y), (draw_width, y)], fill=grid_color, width=grid_line_width)

        if coords and DEBUG_MAP_RENDERING:
            xs, ys = zip(*coords)
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            safe_left, safe_top = margin_px, margin_px
            safe_right, safe_bottom = width - margin_px, height - margin_px
            print(
                f"[MAP] Debug bbox canvas=({width}x{height}) margin={margin_px}px "
                f"route_px=({min_x:.1f},{min_y:.1f})-({max_x:.1f},{max_y:.1f}) "
                f"safe_box=({safe_left},{safe_top})-({safe_right},{safe_bottom}) "
                f"points={len(coords)}"
            )

        if len(coords) >= 2:
            if DEBUG_MAP_RENDERING and not tiles_ok:
                safe_box = (
                    margin_px * UPSCALE_FACTOR,
                    margin_px * UPSCALE_FACTOR,
                    draw_width - margin_px * UPSCALE_FACTOR,
                    draw_height - margin_px * UPSCALE_FACTOR,
                )
                bg_draw.rectangle(safe_box, outline="#d0d7de", width=max(1, int(2 * UPSCALE_FACTOR)))

            route_layer = Image.new("RGBA", (draw_width, draw_height), (0, 0, 0, 0))
            route_draw = ImageDraw.Draw(route_layer, "RGBA")
            base_width = _compute_route_width((draw_width, draw_height))

            # Shadow -> glow -> gradient for strong contrast
            route_draw.line(
                smoothed_scaled,
                fill=ROUTE_SHADOW_COLOR,
                width=int(base_width + 10),
                joint="curve",
            )
            route_draw.line(
                smoothed_scaled,
                fill=ROUTE_GLOW_COLOR,
                width=int(base_width + 7),
                joint="curve",
            )
            _draw_gradient_polyline(route_draw, smoothed_scaled, start_color, end_color, width=int(base_width + 3))

            blurred_route = route_layer.filter(ImageFilter.GaussianBlur(radius=1.0 * UPSCALE_FACTOR))
            blended_route = Image.alpha_composite(blurred_route, route_layer)

            composed = Image.alpha_composite(background_img, blended_route)

            overlay_draw = ImageDraw.Draw(composed, "RGBA")
            if marker_coords_scaled:
                for marker, (mx, my) in zip(markers or [], marker_coords_scaled):
                    if marker.kind == "local":
                        radius = MARKER_RADIUS_LOCAL
                        fill = (255, 255, 255, 255)
                        outline = (60, 60, 60, 255)
                        stroke_width = MARKER_OUTLINE_WIDTH_LOCAL
                    else:
                        radius = MARKER_RADIUS_TRAVEL
                        fill = (230, 230, 230, 255)
                        outline = (80, 80, 80, 255)
                        stroke_width = MARKER_OUTLINE_WIDTH_TRAVEL
                    r_scaled = int(radius * UPSCALE_FACTOR)
                    stroke_scaled = max(1, int(stroke_width * UPSCALE_FACTOR))
                    marker_bbox = (mx - r_scaled, my - r_scaled, mx + r_scaled, my + r_scaled)
                    overlay_draw.ellipse(marker_bbox, fill=fill, outline=outline, width=stroke_scaled)
            _draw_route_markers(overlay_draw, coords_scaled, base_width, start_color, end_color)

            _draw_legend(overlay_draw, draw_width, draw_height, start_color, end_color, marker_outline, scale=UPSCALE_FACTOR)

            frame_margin = int(6 * UPSCALE_FACTOR)
            frame_bbox = (
                frame_margin,
                frame_margin,
                draw_width - frame_margin,
                draw_height - frame_margin,
            )
            overlay_draw.rounded_rectangle(frame_bbox, radius=int(12 * UPSCALE_FACTOR), outline=frame_color, width=int(frame_width * UPSCALE_FACTOR))
        else:
            composed = background_img

        filename = f"book_{book_id}_{filename_prefix}.png"
        output_path = MAP_OUTPUT_DIR / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        final_img = composed.resize((width, height), resample=Image.LANCZOS)
        final_img.save(output_path, format="PNG")

        rel_path = str(output_path.relative_to(DATA_DIR))
        abs_path = str(output_path.resolve())
        print(f"[MAP] Rendered map for book {book_id} to {rel_path}")
        return rel_path, abs_path
    except Exception as e:
        print(f"[map_route_renderer] Failed to render route map for book {book_id}: {e}")
        return "", ""


# ============================================================
# Helpers for clustering and layout
# ============================================================

def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance in kilometers between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _cluster_points(indexed_points: List[Tuple[int, float, float]], radius_km: float = 40.0) -> List[List[Tuple[int, float, float]]]:
    """Greedy clustering based on first point in cluster as representative."""
    clusters: List[List[Tuple[int, float, float]]] = []
    for pt in indexed_points:
        _, lat, lon = pt
        placed = False
        for cluster in clusters:
            _, c_lat, c_lon = cluster[0]
            if _haversine_km(lat, lon, c_lat, c_lon) <= radius_km:
                cluster.append(pt)
                placed = True
                break
        if not placed:
            clusters.append([pt])
    return clusters


def _select_dominant_cluster(clusters: List[List[Tuple[int, float, float]]], total_points: int) -> List[Tuple[int, float, float]]:
    """Pick the largest cluster; if all are size 1, fallback to all points."""
    if not clusters:
        return []
    main = max(clusters, key=len)
    if len(main) <= 1 and total_points > 1:
        combined: List[Tuple[int, float, float]] = []
        for cluster in clusters:
            combined.extend(cluster)
        return combined
    return main


def _filter_points_in_cluster(indexed_points: List[Tuple[int, float, float]], cluster: List[Tuple[int, float, float]]) -> List[Tuple[float, float]]:
    """Return ordered (lat, lon) for points belonging to the chosen cluster."""
    cluster_ids = {idx for idx, _, _ in cluster}
    return [(lat, lon) for idx, lat, lon in indexed_points if idx in cluster_ids]


def simplify_route(points: List[Tuple[float, float]], max_points: int = 25, min_distance_km: float = 0.1) -> List[Tuple[float, float]]:
    """Reduce point count while preserving shape: keep first/last, drop near-duplicates, then downsample."""
    if len(points) < 2:
        return points

    simplified: List[Tuple[float, float]] = [points[0]]
    last_lat, last_lon = points[0]

    for lat, lon in points[1:-1]:
        if _haversine_km(lat, lon, last_lat, last_lon) >= min_distance_km:
            simplified.append((lat, lon))
            last_lat, last_lon = lat, lon

    simplified.append(points[-1])

    if len(simplified) > max_points:
        step = math.ceil((len(simplified) - 2) / max(1, max_points - 2))
        simplified = [simplified[0]] + simplified[1:-1:step] + [simplified[-1]]

    if len(simplified) > max_points and max_points >= 2:
        simplified = simplified[: max_points - 1] + [simplified[-1]]

    if len(simplified) < 2:
        return points

    return simplified


def _compute_bbox(points: List[Tuple[float, float]], padding_ratio: float = 0.15, min_span_deg: float = 0.01) -> dict:
    """Compute padded bbox with span exaggeration for skinny routes."""
    lats = [lat for lat, _ in points]
    lons = [lon for _, lon in points]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)

    span_lat = max(max_lat - min_lat, min_span_deg)
    span_lon = max(max_lon - min_lon, min_span_deg)

    # Exaggerate smaller span if very skinny (<30% of the larger span)
    max_span = max(span_lat, span_lon)
    min_span = min(span_lat, span_lon)
    if min_span / max_span < 0.3:
        if span_lat < span_lon:
            span_lat = max_span * 0.3
        else:
            span_lon = max_span * 0.3

    lat_pad = span_lat * padding_ratio
    lon_pad = span_lon * padding_ratio

    return {
        "min_lat": min_lat - lat_pad,
        "max_lat": max_lat + lat_pad,
        "min_lon": min_lon - lon_pad,
        "max_lon": max_lon + lon_pad,
        "span_lat": span_lat,
        "span_lon": span_lon,
    }


def _normalize_bbox_aspect(
    min_lat: float,
    max_lat: float,
    min_lon: float,
    max_lon: float,
    target_aspect: float,
) -> Tuple[float, float, float, float]:
    """
    Expand bbox (never shrink) to match target aspect (width/height after cos(lat)).
    """
    center_lat = (min_lat + max_lat) / 2.0
    center_lon = (min_lon + max_lon) / 2.0
    lat_span = max(max_lat - min_lat, 1e-6)
    lon_span = max(max_lon - min_lon, 1e-6)
    center_lat_rad = math.radians(center_lat)
    lon_span_vis = lon_span * math.cos(center_lat_rad)
    bbox_aspect = lon_span_vis / lat_span

    if bbox_aspect < target_aspect:
        lon_span_vis_new = target_aspect * lat_span
        lon_span_new = lon_span_vis_new / max(math.cos(center_lat_rad), 1e-6)
        min_lon = center_lon - lon_span_new / 2
        max_lon = center_lon + lon_span_new / 2
    else:
        lat_span_new = lon_span_vis / target_aspect
        min_lat = center_lat - lat_span_new / 2
        max_lat = center_lat + lat_span_new / 2

    return min_lat, max_lat, min_lon, max_lon


def _map_points_to_canvas(
    points: List[Tuple[float, float]],
    width: int,
    height: int,
    margin_px: int = 80,
    shrink_factor: float = 0.96,
    bbox: Optional[dict] = None,
) -> List[Tuple[float, float]]:
    """Project lat/lon to canvas using local equirectangular projection and fixed margins."""
    if not points:
        return []

    if bbox:
        min_lat = bbox["min_lat"]
        max_lat = bbox["max_lat"]
        min_lon = bbox["min_lon"]
        max_lon = bbox["max_lon"]
        lat_center = (min_lat + max_lat) / 2.0
        lon_center = (min_lon + max_lon) / 2.0
    else:
        lats = [lat for lat, _ in points]
        lons = [lon for _, lon in points]
        lat_center = sum(lats) / len(lats)
        lon_center = sum(lons) / len(lons)
    lat_center_rad = math.radians(lat_center)

    locals_xy: List[Tuple[float, float]] = []
    for lat, lon in points:
        dx = (lon - lon_center) * math.cos(lat_center_rad)
        dy = (lat - lat_center)
        locals_xy.append((dx, dy))

    if bbox:
        data_width = (max_lon - min_lon) * math.cos(lat_center_rad)
        data_height = max_lat - min_lat
        min_x, max_x = -data_width / 2.0, data_width / 2.0
        min_y, max_y = -data_height / 2.0, data_height / 2.0
        cx_data, cy_data = 0.0, 0.0
    else:
        xs = [x for x, _ in locals_xy]
        ys = [y for _, y in locals_xy]
        min_x, max_x = min(xs), max(xs)
        min_y, max_y = min(ys), max(ys)
        data_width = max_x - min_x
        data_height = max_y - min_y
        cx_data = (min_x + max_x) / 2.0
        cy_data = (min_y + max_y) / 2.0

    cx_canvas = width / 2.0
    cy_canvas = height / 2.0

    eps = 1e-9
    if data_width < eps and data_height < eps:
        return [(cx_canvas, cy_canvas) for _ in points]

    inner_width = max(width - 2 * margin_px, eps)
    inner_height = max(height - 2 * margin_px, eps)
    scale_x = inner_width / max(data_width, eps)
    scale_y = inner_height / max(data_height, eps)
    scale = min(scale_x, scale_y) * shrink_factor

    mapped: List[Tuple[float, float]] = []
    for dx, dy in locals_xy:
        x_px = cx_canvas + (dx - cx_data) * scale
        y_px = cy_canvas - (dy - cy_data) * scale
        mapped.append((x_px, y_px))

    return mapped


def _draw_marker(draw: ImageDraw.ImageDraw, center: Tuple[float, float], radius: int, fill: str, outline: str) -> None:
    """Draw a circular marker."""
    x, y = center
    bbox = (x - radius, y - radius, x + radius, y + radius)
    stroke_width = max(1, int(2 * UPSCALE_FACTOR))
    draw.ellipse(bbox, fill=fill, outline=outline, width=stroke_width)


def _draw_gradient_polyline(
    draw: ImageDraw.ImageDraw,
    coords: List[Tuple[float, float]],
    start_color: Tuple[int, int, int, int],
    end_color: Tuple[int, int, int, int],
    width: int,
) -> None:
    """Draw a polyline with a start->end color gradient."""
    if len(coords) < 2:
        return

    # Compute cumulative lengths for interpolation
    lengths = [0.0]
    total = 0.0
    for i in range(1, len(coords)):
        x1, y1 = coords[i - 1]
        x2, y2 = coords[i]
        seg = math.hypot(x2 - x1, y2 - y1)
        total += seg
        lengths.append(total)

    if total <= 0:
        return

    for i in range(1, len(coords)):
        t0 = lengths[i - 1] / total
        t1 = lengths[i] / total
        color_t = (t0 + t1) / 2
        color = _interpolate_color(start_color, end_color, color_t)
        draw.line([coords[i - 1], coords[i]], fill=color, width=width, joint="curve")


def _interpolate_color(
    start: Tuple[int, int, int, int], end: Tuple[int, int, int, int], t: float
) -> Tuple[int, int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(s + (e - s) * t) for s, e in zip(start, end))


def _measure_text(font: ImageFont.FreeTypeFont, text: str) -> Tuple[int, int]:
    """Safely measure text size across Pillow versions using getbbox."""
    bbox = font.getbbox(text)
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _draw_legend(
    draw: ImageDraw.ImageDraw,
    width: int,
    height: int,
    start_color: Tuple[int, int, int, int],
    end_color: Tuple[int, int, int, int],
    outline_color: Tuple[int, int, int, int],
    scale: float = UPSCALE_FACTOR,
) -> None:
    """Draw a small legend in the top-right corner."""
    padding = int(LEGEND_MARGIN_PX * scale)
    line_len = int(60 * scale)
    line_gap = int(18 * scale)
    radius = int(5 * scale)
    text_offset = int(8 * scale)
    text_y_offset = int(6 * scale)
    line_width = max(2, int(5 * scale))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", int(12 * scale))
    except Exception:
        font = ImageFont.load_default()

    # Measure text to avoid clipping
    start_text = "Start"
    end_text = "End"
    start_w, _ = _measure_text(font, start_text)
    end_w, _ = _measure_text(font, end_text)
    text_w = max(start_w, end_w)

    x0 = width - padding - line_len - text_offset - text_w
    x0 = max(padding, x0)
    y0 = padding

    # Start
    start_line = [(x0, y0), (x0 + line_len, y0)]
    draw.line(start_line, fill=start_color, width=line_width)
    _draw_marker(draw, start_line[0], radius=radius, fill=ROUTE_MARKER_FILL, outline=start_color)
    draw.text((x0 + line_len + text_offset, y0 - text_y_offset), "Start", fill="#d9e2ec", font=font)

    # End
    y1 = y0 + line_gap
    end_line = [(x0, y1), (x0 + line_len, y1)]
    draw.line(end_line, fill=end_color, width=line_width)
    _draw_marker(draw, end_line[1], radius=radius, fill=ROUTE_MARKER_FILL, outline=end_color)
    draw.text((x0 + line_len + text_offset, y1 - text_y_offset), "End", fill="#d9e2ec", font=font)


def _smooth_polyline(
    points: List[Tuple[float, float]],
    min_total_points: int = 200,
    max_segment_spacing_px: float = 5.0,
) -> List[Tuple[float, float]]:
    """Generate a smoothed polyline using Catmull-Rom interpolation with dense sampling."""
    if len(points) < 4:
        return points

    base_lengths = []
    total_base = 0.0
    for i in range(1, len(points)):
        seg_len = math.hypot(points[i][0] - points[i - 1][0], points[i][1] - points[i - 1][1])
        base_lengths.append(seg_len)
        total_base += seg_len

    if total_base <= 1e-6:
        return points

    samples_per_segment = [
        max(2, math.ceil(seg_len / max_segment_spacing_px)) for seg_len in base_lengths
    ]
    total_samples = sum(samples_per_segment)
    if total_samples < min_total_points:
        scale = math.ceil(min_total_points / max(total_samples, 1))
        samples_per_segment = [max(2, s * scale) for s in samples_per_segment]

    smoothed: List[Tuple[float, float]] = []
    extended = [points[0]] + points + [points[-1]]

    def catmull_rom(p0, p1, p2, p3, t: float) -> Tuple[float, float]:
        t2 = t * t
        t3 = t2 * t
        x = 0.5 * (
            (2 * p1[0])
            + (-p0[0] + p2[0]) * t
            + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2
            + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3
        )
        y = 0.5 * (
            (2 * p1[1])
            + (-p0[1] + p2[1]) * t
            + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2
            + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3
        )
        return x, y

    smoothed.append(points[0])
    for i in range(1, len(extended) - 2):
        p0, p1, p2, p3 = extended[i - 1], extended[i], extended[i + 1], extended[i + 2]
        seg_idx = min(i - 1, len(samples_per_segment) - 1)
        samples = samples_per_segment[seg_idx]
        for j in range(1, samples + 1):
            t = j / float(samples)
            smoothed.append(catmull_rom(p0, p1, p2, p3, t))

    return smoothed


def debug_render_synthetic_routes(output_dir: Path) -> None:
    """
    Generate synthetic route images for quick visual debugging without external data.
    """
    routes = {
        "diag": [
            (37.7700, -122.4700),
            (37.7800, -122.4600),
            (37.7900, -122.4500),
            (37.8000, -122.4400),
        ],
        "loop": [
            (37.7800, -122.4200),
            (37.7820, -122.4180),
            (37.7840, -122.4200),
            (37.7820, -122.4220),
            (37.7800, -122.4200),
        ],
        "east_west": [
            (40.0000, -120.0000),
            (40.0000, -115.0000),
            (40.0000, -110.0000),
            (40.0000, -105.0000),
            (40.0000, -100.0000),
            (40.0000, -95.0000),
            (40.0000, -90.0000),
            (40.0000, -85.0000),
        ],
        "north_south": [
            (30.0000, -100.0000),
            (32.5000, -100.0000),
            (35.0000, -100.0000),
            (37.5000, -100.0000),
            (40.0000, -100.0000),
            (42.5000, -100.0000),
            (45.0000, -100.0000),
        ],
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    width, height = 1600, 1000
    route_width = 7
    margin_px = 90
    shrink_factor = 0.9
    halo_width = 16
    halo_color = (46, 139, 192, 70)
    start_color = (64, 224, 208, 255)
    end_color = (244, 114, 182, 255)
    marker_outline = (255, 255, 255, 60)

    for name, pts in routes.items():
        if len(pts) < 2:
            continue

        simplified = simplify_route(pts, max_points=25, min_distance_km=0.1)
        bbox = _compute_bbox(simplified)
        coords = _map_points_to_canvas(simplified, width, height, margin_px=margin_px, shrink_factor=shrink_factor)
        smoothed_coords = _smooth_polyline(coords, min_total_points=250, max_segment_spacing_px=5.0)
        coords_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in coords]
        smoothed_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in smoothed_coords]
        draw_width, draw_height = width * UPSCALE_FACTOR, height * UPSCALE_FACTOR

        print(f"[MAP][DEBUG] Synthetic '{name}' simplified to {len(simplified)} pts; bbox lat({bbox['min_lat']:.4f},{bbox['max_lat']:.4f}) lon({bbox['min_lon']:.4f},{bbox['max_lon']:.4f})")
        if coords and DEBUG_MAP_RENDERING:
            xs, ys = zip(*coords)
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            safe_left, safe_top = margin_px, margin_px
            safe_right, safe_bottom = width - margin_px, height - margin_px
            print(
                f"[MAP][DEBUG] '{name}' canvas=({width}x{height}) margin={margin_px}px "
                f"route_px=({min_x:.1f},{min_y:.1f})-({max_x:.1f},{max_y:.1f}) "
                f"safe_box=({safe_left},{safe_top})-({safe_right},{safe_bottom}) "
                f"points={len(coords)}"
            )

        img = Image.new("RGBA", (draw_width, draw_height), color="#050910")
        draw = ImageDraw.Draw(img, "RGBA")

        if coords and len(coords) >= 2:
            if DEBUG_MAP_RENDERING:
                safe_box = (
                    margin_px * UPSCALE_FACTOR,
                    margin_px * UPSCALE_FACTOR,
                    draw_width - margin_px * UPSCALE_FACTOR,
                    draw_height - margin_px * UPSCALE_FACTOR,
                )
                draw.rectangle(safe_box, outline="#d0d7de", width=max(1, int(2 * UPSCALE_FACTOR)))

            draw.line(smoothed_scaled, fill=halo_color, width=int(halo_width * UPSCALE_FACTOR), joint="curve")
            _draw_gradient_polyline(draw, smoothed_scaled, start_color, end_color, width=int(route_width * UPSCALE_FACTOR))

            _draw_marker(draw, coords_scaled[0], radius=int(10 * UPSCALE_FACTOR), fill="#3cb371", outline=marker_outline)
            _draw_marker(draw, coords_scaled[-1], radius=int(10 * UPSCALE_FACTOR), fill="#e63946", outline=marker_outline)
            _draw_legend(draw, draw_width, draw_height, start_color, end_color, marker_outline, scale=UPSCALE_FACTOR)

        out_path = output_dir / f"synthetic_{name}.png"
        final_img = img.resize((width, height), resample=Image.LANCZOS)
        final_img.save(out_path, format="PNG")
        print(f"[MAP][DEBUG] Saved synthetic route '{name}' to {out_path}")
