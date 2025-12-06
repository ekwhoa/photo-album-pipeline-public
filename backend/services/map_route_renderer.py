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

from PIL import Image, ImageDraw


BASE_DIR = Path(__file__).resolve().parents[1]

# Directories
DATA_DIR = BASE_DIR / "data"
MAP_OUTPUT_DIR = DATA_DIR / "maps"
DEBUG_MAP_RENDERING = True

# Ensure directories exist
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
                safe_box = (margin_px, margin_px, width - margin_px, height - margin_px)
                draw.rectangle(safe_box, outline="#d0d7de", width=2)

            draw.line(coords, fill=route_color, width=route_width, joint="curve")

            # Light smoothing at joints to soften corners
            joint_radius = max(route_width // 2 + 1, route_width // 2)
            for x, y in coords:
                bbox_joint = (x - joint_radius, y - joint_radius, x + joint_radius, y + joint_radius)
                draw.ellipse(bbox_joint, fill=route_color, outline=route_color)

            # Start / end markers
            _draw_marker(draw, coords[0], radius=10, fill="#3cb371", outline="#3cb371")
            _draw_marker(draw, coords[-1], radius=10, fill="#e63946", outline="#e63946")

        filename = f"book_{book_id}_route.png"
        output_path = MAP_OUTPUT_DIR / filename
        output_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(output_path, format="PNG")

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
    draw.ellipse(bbox, fill=fill, outline=outline, width=2)


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
    route_width = 6
    route_color = "#2e8bc0"
    margin_px = 90
    shrink_factor = 0.9

    for name, pts in routes.items():
        if len(pts) < 2:
            continue

        simplified = simplify_route(pts, max_points=25, min_distance_km=0.1)
        bbox = _compute_bbox(simplified)
        coords = _map_points_to_canvas(simplified, width, height, margin_px=margin_px, shrink_factor=shrink_factor)

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

        img = Image.new("RGB", (width, height), color="#f6f8fa")
        draw = ImageDraw.Draw(img)

        if coords and len(coords) >= 2:
            if DEBUG_MAP_RENDERING:
                safe_box = (margin_px, margin_px, width - margin_px, height - margin_px)
                draw.rectangle(safe_box, outline="#d0d7de", width=2)

            draw.line(coords, fill=route_color, width=route_width, joint="curve")

            joint_radius = max(route_width // 2 + 1, route_width // 2)
            for x, y in coords:
                bbox_joint = (x - joint_radius, y - joint_radius, x + joint_radius, y + joint_radius)
                draw.ellipse(bbox_joint, fill=route_color, outline=route_color)

            _draw_marker(draw, coords[0], radius=10, fill="#3cb371", outline="#3cb371")
            _draw_marker(draw, coords[-1], radius=10, fill="#e63946", outline="#e63946")

        out_path = output_dir / f"synthetic_{name}.png"
        img.save(out_path, format="PNG")
        print(f"[MAP][DEBUG] Saved synthetic route '{name}' to {out_path}")
