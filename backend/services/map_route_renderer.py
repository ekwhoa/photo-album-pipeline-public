"""
Schematic route map renderer using pure Pillow.

Generates a simple offline PNG showing the route polyline without external tile servers.
"""
from pathlib import Path
from typing import List, Tuple

from PIL import Image, ImageDraw

BASE_DIR = Path(__file__).resolve().parents[1]

# Directories
DATA_DIR = BASE_DIR / "data"
MAP_OUTPUT_DIR = DATA_DIR / "maps"

# Ensure directories exist
MAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# Image dimensions and margins
IMG_WIDTH = 1600
IMG_HEIGHT = 1000
MARGIN_X = 80
MARGIN_Y = 60

# Colors
COLOR_BACKGROUND = (255, 255, 255)
COLOR_ROUTE = (0, 150, 136)  # Teal
COLOR_START = (76, 175, 80)  # Green
COLOR_END = (244, 67, 54)    # Red
COLOR_BORDER = (200, 200, 200)  # Light gray


def _compute_padded_bbox(points: List[Tuple[float, float]], padding_ratio: float = 0.1) -> Tuple[float, float, float, float]:
    """
    Compute a padded bounding box for the given lat/lon points.
    
    Returns (min_lat, max_lat, min_lon, max_lon) with padding applied.
    """
    lats = [p[0] for p in points]
    lons = [p[1] for p in points]
    
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    
    lat_range = max_lat - min_lat
    lon_range = max_lon - min_lon
    
    # Handle case where all points are the same (single location)
    if lat_range == 0:
        lat_range = 0.01
    if lon_range == 0:
        lon_range = 0.01
    
    padding_lat = lat_range * padding_ratio
    padding_lon = lon_range * padding_ratio
    
    return (
        min_lat - padding_lat,
        max_lat + padding_lat,
        min_lon - padding_lon,
        max_lon + padding_lon,
    )


def _latlon_to_pixel(
    lat: float, lon: float,
    bbox: Tuple[float, float, float, float],
    img_width: int, img_height: int,
    margin_x: int, margin_y: int
) -> Tuple[int, int]:
    """
    Map lat/lon to pixel coordinates within the image area (inside margins).
    """
    min_lat, max_lat, min_lon, max_lon = bbox
    
    drawable_width = img_width - 2 * margin_x
    drawable_height = img_height - 2 * margin_y
    
    # Normalize to 0-1 range
    norm_x = (lon - min_lon) / (max_lon - min_lon)
    norm_y = (lat - min_lat) / (max_lat - min_lat)
    
    # Convert to pixel coords (flip Y since image origin is top-left)
    px = margin_x + int(norm_x * drawable_width)
    py = margin_y + int((1 - norm_y) * drawable_height)
    
    return (px, py)


def render_route_map(book_id: str, points: List[Tuple[float, float]]) -> Tuple[str, str]:
    """
    Render a schematic PNG map for the given route points using pure Pillow.

    Args:
        book_id: Book identifier (used for filename)
        points: Ordered list of (lat, lon) tuples

    Returns:
        (relative_path, absolute_path). Empty strings if rendering fails or insufficient points.
        relative_path is relative to the static mount root (data/).
    """
    if len(points) < 2:
        return "", ""

    print(f"[MAP] Starting schematic route render for book {book_id} with {len(points)} points")

    try:
        # Compute bounding box
        bbox = _compute_padded_bbox(points)
        min_lat, max_lat, min_lon, max_lon = bbox
        print(f"[MAP] Computed bbox: lat [{min_lat:.4f}, {max_lat:.4f}], lon [{min_lon:.4f}, {max_lon:.4f}]")

        # Create image with white background
        img = Image.new("RGB", (IMG_WIDTH, IMG_HEIGHT), COLOR_BACKGROUND)
        draw = ImageDraw.Draw(img)

        # Draw light border
        draw.rectangle(
            [MARGIN_X - 2, MARGIN_Y - 2, IMG_WIDTH - MARGIN_X + 2, IMG_HEIGHT - MARGIN_Y + 2],
            outline=COLOR_BORDER,
            width=2
        )

        # Convert all points to pixel coordinates
        pixel_points = [
            _latlon_to_pixel(lat, lon, bbox, IMG_WIDTH, IMG_HEIGHT, MARGIN_X, MARGIN_Y)
            for lat, lon in points
        ]

        # Draw route polyline
        if len(pixel_points) >= 2:
            draw.line(pixel_points, fill=COLOR_ROUTE, width=4)

        # Draw start marker (green circle)
        start_px, start_py = pixel_points[0]
        draw.ellipse(
            [start_px - 10, start_py - 10, start_px + 10, start_py + 10],
            fill=COLOR_START,
            outline=(255, 255, 255),
            width=2
        )

        # Draw end marker (red circle)
        end_px, end_py = pixel_points[-1]
        draw.ellipse(
            [end_px - 10, end_py - 10, end_px + 10, end_py + 10],
            fill=COLOR_END,
            outline=(255, 255, 255),
            width=2
        )

        # Save the image
        filename = f"book_{book_id}_route.png"
        output_path = MAP_OUTPUT_DIR / filename
        img.save(output_path, format="PNG")

        rel_path = str(output_path.relative_to(DATA_DIR))
        abs_path = str(output_path.resolve())

        print(f"[MAP] Rendered schematic route map for book {book_id} with {len(points)} points -> {output_path}")

        return rel_path, abs_path

    except Exception as e:
        print(f"[MAP] Failed to render schematic route map for book {book_id}: {e}")
        return "", ""
