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

        simplified_points = simplify_route(core_points, max_points=200, min_distance_km=0.05)
        print(
            f"[MAP] Simplified route from {len(core_points)} to "
            f"{len(simplified_points)} points"
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

        # Map points to canvas
        coords = [
            _latlon_to_xy(lat, lon, bbox, width, height)
            for lat, lon in simplified_points
        ]

        print(
            f"[MAP] Drawing {len(simplified_points)} core points "
            f"(ignored {len(cluster_points) - len(core_points)} edge points)"
        )

        if len(coords) >= 2:
            draw.line(coords, fill="#2e8bc0", width=6, joint="curve")

            # Start / end markers
            _draw_marker(draw, coords[0], radius=10, fill="#3cb371", outline="#1f7a4d")
            _draw_marker(draw, coords[-1], radius=10, fill="#e63946", outline="#b22234")

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


def simplify_route(points: List[Tuple[float, float]], max_points: int = 200, min_distance_km: float = 0.05) -> List[Tuple[float, float]]:
    """
    Reduce point count while preserving shape: keep first/last, drop near-duplicates, then downsample.
    """
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


def _latlon_to_xy(lat: float, lon: float, bbox: dict, width: int, height: int) -> Tuple[float, float]:
    """Map lat/lon to canvas coordinates using the padded bbox."""
    # Invert latitude for y (north at top)
    x = (lon - bbox["min_lon"]) / max(bbox["span_lon"], 1e-9)
    y = (bbox["max_lat"] - lat) / max(bbox["span_lat"], 1e-9)
    return x * width, y * height


def _draw_marker(draw: ImageDraw.ImageDraw, center: Tuple[float, float], radius: int, fill: str, outline: str) -> None:
    """Draw a circular marker."""
    x, y = center
    bbox = (x - radius, y - radius, x + radius, y + radius)
    draw.ellipse(bbox, fill=fill, outline=outline, width=2)
