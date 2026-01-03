import pytest
import math

import services.map_route_renderer as m


def _make_segment(points):
    return {"polyline": points}


def test_day_map_reuses_canonical_points_and_viewport(monkeypatch):
    raw_points = [
        (0.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
        (1.0, 1.5),
    ]
    calls = []

    def fake_render(
        book_id,
        points,
        width,
        height,
        filename_prefix="route",
        markers=None,
        stops_for_legend=None,
        stops_drawn_out=None,
        right_safe_frac=0.0,
        preprocessed=False,
        bbox_override=None,
        start_end_override=None,
    ):
        calls.append(
            {
                "book_id": book_id,
                "points": points,
                "preprocessed": preprocessed,
                "bbox_override": bbox_override,
                "markers": markers,
                "start_end_override": start_end_override,
                "filename_prefix": filename_prefix,
                "stops_drawn_out": stops_drawn_out,
                "right_safe_frac": right_safe_frac,
            }
        )
        return "", ""

    monkeypatch.setattr(m, "_render_route_image", fake_render)
    m._CANONICAL_CACHE.clear()

    # Populate canonical cache via trip render.
    m.render_route_map("b1", raw_points)
    canonical_points = m._CANONICAL_CACHE["b1"].points

    # Day render should reuse the cached canonical list, override bbox, and skip place markers.
    day_segments = [_make_segment(raw_points[:3])]
    m.render_day_route_image("b1", day_segments)

    assert len(calls) == 2
    day_call = calls[-1]
    assert day_call["points"] is canonical_points
    assert day_call["preprocessed"] is True
    assert day_call["markers"] == []
    assert day_call["bbox_override"] is not None
    assert day_call["filename_prefix"] == "day_route"
    # Day viewport should be tighter than the trip bbox for this subset.
    trip_bbox = m._compute_bbox(canonical_points)
    day_bbox = day_call["bbox_override"]
    assert day_bbox["max_lat"] - day_bbox["min_lat"] <= trip_bbox["max_lat"] - trip_bbox["min_lat"]
    assert day_bbox["max_lon"] - day_bbox["min_lon"] <= trip_bbox["max_lon"] - trip_bbox["min_lon"]
    # Start/end indices should map to a subset of the canonical points.
    assert day_call["start_end_override"] is not None
    start_idx, end_idx = day_call["start_end_override"]
    assert 0 <= start_idx <= end_idx < len(canonical_points)


def test_right_safe_area_shrinks_route_extent():
    raw_points = [
        (0.0, 0.0),
        (0.0, 1.0),
        (1.0, 1.0),
    ]
    width, height = 1000, 500
    margin = 80
    # Without safe area
    coords_default = m._map_points_to_canvas(raw_points, width, height, margin_px=margin, shrink_factor=1.0)
    xs_default = [x for x, _ in coords_default]
    max_default = max(xs_default)

    # With 40% right safe area
    coords_safe = m._map_points_to_canvas(raw_points, width, height, margin_px=margin, shrink_factor=1.0, right_safe_frac=0.4)
    xs_safe = [x for x, _ in coords_safe]
    max_safe = max(xs_safe)

    # Max X should be materially left of the full width minus margin when safe area applied
    assert max_safe < max_default
    assert max_safe <= (width * (1 - 0.4)) - margin + 1e-6


def test_stop_badge_constants_are_enlarged():
    assert m.STOP_BADGE_RADIUS >= 14
    assert m.STOP_BADGE_FONT_SIZE >= 18
    assert m.STOP_BADGE_OUTLINE_WIDTH >= 0


def test_bbox_expansion_matches_drawable_aspect():
    pts = [(37.0, -122.0), (37.5, -122.5), (37.2, -122.2)]
    width, height = 1600, 1000
    margin = 80
    safe = 0.35
    drawable_w = (width - 2 * margin) * (1 - safe)
    drawable_h = height - 2 * margin
    target_aspect = drawable_w / drawable_h
    bbox = m._compute_bbox(pts)
    expanded = m._expand_bbox_to_aspect(bbox, target_aspect)
    lat_center = (expanded["min_lat"] + expanded["max_lat"]) / 2.0
    cos_lat = math.cos(math.radians(lat_center))
    aspect_expanded = (expanded["span_lon"] * cos_lat) / expanded["span_lat"]
    assert abs(aspect_expanded - target_aspect) / target_aspect < 0.05


def test_tile_layout_mapping_is_consistent_with_bbox():
    bbox = {
        "min_lat": 0.0,
        "max_lat": 1.0,
        "min_lon": 0.0,
        "max_lon": 1.0,
    }
    ctx = m._compute_tile_layout(bbox, 800, 600)
    assert ctx is not None
    pts = [(bbox["min_lat"], bbox["min_lon"]), (bbox["max_lat"], bbox["max_lon"])]
    mapped = m._map_points_to_tile_pixels(pts, ctx)
    assert len(mapped) == 2
    (x0, y0), (x1, y1) = mapped
    # Mapped coords should lie within image bounds with padding applied by layout.
    assert -50 <= x0 <= 850
    assert -50 <= y0 <= 650
    assert -50 <= x1 <= 850
    assert -50 <= y1 <= 650


def test_tiles_and_route_use_same_layout(monkeypatch, tmp_path):
    raw_points = [(0.0, 0.0), (0.5, 0.5)]
    fake_layout = {
        "zoom": 8,
        "x_min": 1,
        "x_max": 2,
        "y_min": 3,
        "y_max": 4,
        "scaled_tile_size": 50,
        "offset_x": 10,
        "offset_y": 20,
    }
    layouts_seen = []
    maps_seen = []

    monkeypatch.setattr(m, "MAP_TILES_ENABLED", True)
    monkeypatch.setattr(m, "MAP_TILE_URL_TEMPLATE", "dummy")

    def fake_compute(bbox, w, h):
        layouts_seen.append(("compute", bbox, w, h))
        return fake_layout

    def fake_draw(img, bbox, layout=None):
        layouts_seen.append(("draw", layout))
        return True, layout or fake_layout

    def fake_map(points, layout):
        maps_seen.append(layout)
        return [(0.0, 0.0), (100.0, 100.0)]

    monkeypatch.setattr(m, "_compute_tile_layout", fake_compute)
    monkeypatch.setattr(m, "_draw_tile_background", fake_draw)
    monkeypatch.setattr(m, "_map_points_to_tile_pixels", fake_map)

    m._render_route_image(
        "b-tiles",
        raw_points,
        width=200,
        height=100,
        filename_prefix="route_test",
        preprocessed=True,
    )

    assert maps_seen, "route mapping should have used tile pixel mapper"
    assert layouts_seen, "tile background should have been invoked"
    mapped_layout = maps_seen[0]
    draw_layout = layouts_seen[-1][1]
    assert mapped_layout is draw_layout is fake_layout


def test_trip_route_map_renders_with_stops(monkeypatch, tmp_path):
    tmp_data = tmp_path / "data"
    tmp_maps = tmp_data / "maps"
    tmp_maps.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(m, "DATA_DIR", tmp_data)
    monkeypatch.setattr(m, "MAP_OUTPUT_DIR", tmp_maps)
    monkeypatch.setattr(m, "DEBUG_MAP_RENDERING", False)

    raw_points = [(0.0, 0.0), (0.1, 0.1)]
    stops = [
        {"label": "Alpha", "lat": 0.0, "lon": 0.0, "photo_count": 3, "day_index": 1},
        {"label": "Beta", "lat": 0.1, "lon": 0.1, "photo_count": 2, "day_index": 2},
    ]

    rel_path, abs_path = m.render_trip_route_map(
        "book-stops",
        raw_points,
        stops_for_legend=stops,
    )

    assert rel_path
    assert abs_path
    assert (tmp_data / rel_path).exists()


def test_stop_markers_use_day_colors(monkeypatch, tmp_path):
    tmp_data = tmp_path / "data"
    tmp_maps = tmp_data / "maps"
    tmp_maps.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(m, "DATA_DIR", tmp_data)
    monkeypatch.setattr(m, "MAP_OUTPUT_DIR", tmp_maps)
    monkeypatch.setattr(m, "DEBUG_MAP_RENDERING", False)

    raw_points = [(0.0, 0.0), (0.1, 0.1)]
    stops = [
        {"label": "One", "lat": 0.0, "lon": 0.0, "photo_count": 1, "day_index": 1},
        {"label": "Two", "lat": 0.1, "lon": 0.1, "photo_count": 1, "day_index": 2},
    ]

    fills = []

    orig_ellipse = m.ImageDraw.ImageDraw.ellipse

    def recording_ellipse(self, xy, fill=None, outline=None, width=0):
        fills.append(fill)
        return orig_ellipse(self, xy, fill=fill, outline=outline, width=width)

    monkeypatch.setattr(m.ImageDraw.ImageDraw, "ellipse", recording_ellipse, raising=False)

    m.render_trip_route_map(
        "book-stop-colors",
        raw_points,
        stops_for_legend=stops,
    )

    # Expect at least two distinct RGBA fills coming from stop badges (palette)
    unique_fills = {f for f in fills if isinstance(f, tuple)}
    assert len(unique_fills) >= 2
