import io
from unittest.mock import MagicMock

from PIL import Image

from services import map_route_renderer as mrr


def _mock_tile_response(color="blue"):
    img = Image.new("RGB", (8, 8), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf.getvalue()


def test_tile_cache_hits(monkeypatch, tmp_path):
    # use temp cache path
    cache_path = tmp_path / "tiles.sqlite"
    monkeypatch.setattr(mrr, "MAP_TILE_CACHE_PATH", cache_path)
    monkeypatch.setattr(mrr, "_CACHE_DB", None, raising=False)
    mrr._fetch_tile_cached.cache_clear()
    # ensure fresh DB
    if cache_path.exists():
        cache_path.unlink()

    call_counter = {"count": 0}

    def fake_http(z, x, y):
        call_counter["count"] += 1
        data = _mock_tile_response("red")
        return Image.open(io.BytesIO(data)).convert("RGB")

    monkeypatch.setattr(mrr, "_fetch_tile_http", fake_http)

    img1 = mrr._fetch_tile_cached(5, 10, 12)
    img2 = mrr._fetch_tile_cached(5, 10, 12)

    assert img1 is not None
    assert img2 is not None
    assert call_counter["count"] == 1
    # cache file should exist
    assert cache_path.exists()
