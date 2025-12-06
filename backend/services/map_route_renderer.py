"""
Route map renderer using staticmap + OpenStreetMap tiles.

Generates a static PNG for map route pages. Falls back gracefully on errors.
"""
import os
from pathlib import Path
from typing import List, Tuple

from PIL import Image
import requests

# Pillow >=10 removed Image.ANTIALIAS; staticmap still references it.
if not hasattr(Image, "ANTIALIAS") and hasattr(Image, "Resampling"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS

# Respect OSM tile policy: supply an identifying User-Agent (with contact) and optional Referer.
_TILE_USER_AGENT = os.getenv(
    "MAP_TILE_USER_AGENT",
    "PhotoAlbumPipeline/1.0 (contact: support@example.com)",
)
_TILE_REFERER = os.getenv("MAP_TILE_REFERER", "")

_original_request = requests.sessions.Session.request


def _patched_request(self, method, url, **kwargs):
    headers = kwargs.setdefault("headers", {})
    headers.setdefault("User-Agent", _TILE_USER_AGENT)
    if _TILE_REFERER and "Referer" not in headers:
        headers["Referer"] = _TILE_REFERER
    return _original_request(self, method, url, **kwargs)


# Patch requests so staticmap tile fetches include the required headers.
requests.sessions.Session.request = _patched_request

BASE_DIR = Path(__file__).resolve().parents[1]

# Directories
DATA_DIR = BASE_DIR / "data"
MAP_CACHE_DIR = DATA_DIR / "map_cache"
MAP_OUTPUT_DIR = DATA_DIR / "maps"

# Ensure directories exist
MAP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def render_route_map(book_id: str, points: List[Tuple[float, float]]) -> Tuple[str, str]:
    """
    Render a static PNG map for the given route points.

    Args:
        book_id: Book identifier (used for filename)
        points: Ordered list of (lat, lon) tuples

    Returns:
        (relative_path, absolute_path). Empty strings if rendering fails or insufficient points.
        relative_path is relative to the static mount root (data/).
    """
    if len(points) < 2:
        return "", ""

    try:
        from staticmap import StaticMap, Line, CircleMarker
    except ImportError:
        print("[map_route_renderer] staticmap not installed, skipping route rendering")
        return "", ""

    try:
        # Configure map (try to use on-disk tile cache when supported)
        map_kwargs = {
            "url_template": "https://tile.openstreetmap.org/{z}/{x}/{y}.png",
            "tile_cache": str(MAP_CACHE_DIR),
        }
        try:
            m = StaticMap(1600, 1000, **map_kwargs)
        except TypeError:
            # Older staticmap versions don't support tile_cache
            map_kwargs.pop("tile_cache", None)
            print("[map_route_renderer] staticmap missing tile_cache support, rendering without disk cache")
            m = StaticMap(1600, 1000, **map_kwargs)

        # Polyline through points (lon, lat order for staticmap)
        line_points = [(lon, lat) for lat, lon in points]
        line = Line(line_points, "blue", 3)
        m.add_line(line)

        # Start / end markers for quick orientation (optional)
        try:
            m.add_marker(CircleMarker(line_points[0], "green", 8))
            m.add_marker(CircleMarker(line_points[-1], "red", 8))
        except Exception:
            # Marker drawing is best-effort; ignore failures
            pass

        image = m.render()

        filename = f"book_{book_id}_route.png"
        output_path = MAP_OUTPUT_DIR / filename
        image.save(output_path, format="PNG")

        rel_path = str(output_path.relative_to(DATA_DIR))
        abs_path = str(output_path.resolve())
        return rel_path, abs_path
    except Exception as e:
        print(f"[map_route_renderer] Failed to render route map for book {book_id}: {e}")
        return "", ""
