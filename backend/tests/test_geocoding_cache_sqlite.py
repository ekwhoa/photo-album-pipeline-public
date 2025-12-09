import io
from unittest.mock import patch

import pytest

from services import geocoding as geo


class DummyResponse:
    def __init__(self, json_data):
        self._json = json_data

    def raise_for_status(self):  # not used anymore but kept for compatibility
        return None

    def json(self):
        return self._json


@pytest.fixture(autouse=True)
def clear_cache(monkeypatch, tmp_path):
    geo.reverse_geocode_label.cache_clear()
    monkeypatch.setattr(geo, "_CACHE_DB", None, raising=False)
    monkeypatch.setattr(geo, "NOMINATIM_CACHE_PATH", str(tmp_path / "geocode.sqlite"))
    monkeypatch.setattr(geo, "NOMINATIM_CACHE_TTL_SECONDS", 1000)


def test_reverse_geocode_label_uses_sqlite_cache(monkeypatch):
    call_count = {"count": 0}

    def fake_get(url, params=None, headers=None, timeout=None):
        call_count["count"] += 1
        return DummyResponse({
            "address": {
                "city": "Chicago",
                "state": "Illinois",
                "country": "United States",
            }
        })

    monkeypatch.setattr(geo, "_throttled_get", fake_get)

    # First call hits HTTP
    label1 = geo.reverse_geocode_label(41.88, -87.63)
    # Second call should hit the SQLite cache
    label2 = geo.reverse_geocode_label(41.88, -87.63)

    assert label1 is not None
    assert label2 is not None
    assert call_count["count"] == 1
    assert label2.short_label == "Chicago, Illinois"
