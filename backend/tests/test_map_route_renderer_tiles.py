import io
from unittest.mock import MagicMock

from PIL import Image

from services import map_route_renderer as mrr


def _mock_tile_response():
    img = Image.new("RGB", (8, 8), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    resp = MagicMock()
    resp.content = buf.getvalue()
    resp.raise_for_status.return_value = None
    return resp


def test_fetch_tile_cached_uses_cache(monkeypatch):
    mrr._fetch_tile_cached.cache_clear()
    monkeypatch.setattr(mrr, "MAP_TILES_ENABLED", True)
    monkeypatch.setattr(mrr, "MAP_TILE_URL_TEMPLATE", "http://example/{z}/{x}/{y}.png")

    mock_resp = _mock_tile_response()
    call_counter = {"count": 0}

    def fake_get(url, headers=None, timeout=None):
        call_counter["count"] += 1
        return mock_resp

    monkeypatch.setattr(mrr._TILE_SESSION, "get", fake_get)

    tile1 = mrr._fetch_tile_cached(1, 2, 3)
    tile2 = mrr._fetch_tile_cached(1, 2, 3)

    assert tile1 is not None
    assert tile2 is not None
    assert call_counter["count"] == 1
