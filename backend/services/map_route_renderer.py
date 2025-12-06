"""
Route map renderer using Pillow (schematic).

Generates a static PNG for map route pages.
Focuses on the dominant trip cluster and exaggerates skinny routes.
"""
import os
import math
from pathlib import Path
from statistics import median
from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont, ImageFilter


BASE_DIR = Path(__file__).resolve().parents[1]
UPSCALE_FACTOR = 4

# Directories
DATA_DIR = BASE_DIR / "data"
MAP_OUTPUT_DIR = DATA_DIR / "maps"
DEBUG_MAP_RENDERING = True

# Ensure directories exist
MAP_OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# TODO(map-v2): explore further smoothing/anti-aliasing for extreme zoom levels,
# or switching to an SVG/vector-based route renderer if we ever need ultra-high DPI.
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
        print(
            f"[MAP] BBox lat({bbox['min_lat']:.4f},{bbox['max_lat']:.4f}) "
            f"lon({bbox['min_lon']:.4f},{bbox['max_lon']:.4f}) "
            f"span_lat={bbox['span_lat']:.4f} span_lon={bbox['span_lon']:.4f}"
        )

        # Render schematic map with Pillow
        width, height = 1600, 1000
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
        frame_color = "#0f1724"
        frame_width = 3
        halo_color = (46, 139, 192, 70)
        halo_width = 16
        route_width = 7
        start_color = (64, 224, 208, 255)  # turquoise
        end_color = (244, 114, 182, 255)  # coral/pink
        marker_outline = (255, 255, 255, 60)
        margin_px = 90
        coords = _map_points_to_canvas(simplified_points, width, height, margin_px=margin_px, shrink_factor=0.9)
        smoothed_coords = _smooth_polyline(
            coords,
            min_total_points=250,
            max_segment_spacing_px=5.0,
        )

        draw_width, draw_height = width * UPSCALE_FACTOR, height * UPSCALE_FACTOR
        coords_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in coords]
        smoothed_scaled = [(x * UPSCALE_FACTOR, y * UPSCALE_FACTOR) for x, y in smoothed_coords]

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
            if DEBUG_MAP_RENDERING:
                safe_box = (
                    margin_px * UPSCALE_FACTOR,
                    margin_px * UPSCALE_FACTOR,
                    draw_width - margin_px * UPSCALE_FACTOR,
                    draw_height - margin_px * UPSCALE_FACTOR,
                )
                bg_draw.rectangle(safe_box, outline="#d0d7de", width=max(1, int(2 * UPSCALE_FACTOR)))

            route_layer = Image.new("RGBA", (draw_width, draw_height), (0, 0, 0, 0))
            route_draw = ImageDraw.Draw(route_layer, "RGBA")

            route_draw.line(smoothed_scaled, fill=halo_color, width=int(halo_width * UPSCALE_FACTOR), joint="curve")
            _draw_gradient_polyline(route_draw, smoothed_scaled, start_color, end_color, width=int(route_width * UPSCALE_FACTOR))

            blurred_route = route_layer.filter(ImageFilter.GaussianBlur(radius=1.0 * UPSCALE_FACTOR))
            blended_route = Image.alpha_composite(blurred_route, route_layer)

            composed = Image.alpha_composite(background_img, blended_route)

            overlay_draw = ImageDraw.Draw(composed, "RGBA")
            _draw_marker(overlay_draw, coords_scaled[0], radius=int(10 * UPSCALE_FACTOR), fill="#3cb371", outline=marker_outline)
            _draw_marker(overlay_draw, coords_scaled[-1], radius=int(10 * UPSCALE_FACTOR), fill="#e63946", outline=marker_outline)

            _draw_legend(overlay_draw, draw_width, draw_height, start_color, end_color, marker_outline, scale=UPSCALE_FACTOR)

            frame_margin = int(8 * UPSCALE_FACTOR)
            frame_bbox = (
                frame_margin,
                frame_margin,
                draw_width - frame_margin,
                draw_height - frame_margin,
            )
            overlay_draw.rounded_rectangle(frame_bbox, radius=int(12 * UPSCALE_FACTOR), outline=frame_color, width=int(frame_width * UPSCALE_FACTOR))
        else:
            composed = background_img

        filename = f"book_{book_id}_route.png"
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


def _map_points_to_canvas(
    points: List[Tuple[float, float]],
    width: int,
    height: int,
    margin_px: int = 80,
    shrink_factor: float = 0.9,
) -> List[Tuple[float, float]]:
    """Project lat/lon to canvas using local equirectangular projection and fixed margins."""
    if not points:
        return []

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
    padding = int(20 * scale)
    line_len = int(70 * scale)
    line_gap = int(18 * scale)
    radius = int(5 * scale)
    text_offset = int(8 * scale)
    text_y_offset = int(6 * scale)
    line_width = max(2, int(5 * scale))
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", int(12 * scale))
    except Exception:
        font = ImageFont.load_default()

    x0 = width - padding - line_len
    y0 = padding

    # Start
    start_line = [(x0, y0), (x0 + line_len, y0)]
    draw.line(start_line, fill=start_color, width=line_width)
    _draw_marker(draw, start_line[0], radius=radius, fill="#3cb371", outline=outline_color)
    draw.text((x0 + line_len + text_offset, y0 - text_y_offset), "Start", fill="#d9e2ec", font=font)

    # End
    y1 = y0 + line_gap
    end_line = [(x0, y1), (x0 + line_len, y1)]
    draw.line(end_line, fill=end_color, width=line_width)
    _draw_marker(draw, end_line[1], radius=radius, fill="#e63946", outline=outline_color)
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
