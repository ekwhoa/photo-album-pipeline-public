from unittest.mock import MagicMock, patch

from services.geocoding import (
    PlaceLabel,
    compute_centroid,
    reverse_geocode_label,
)


def test_compute_centroid_basic():
    pts = [(0.0, 0.0), (2.0, 4.0)]
    lat, lon = compute_centroid(pts)  # type: ignore
    assert lat == 1.0
    assert lon == 2.0


@patch("services.geocoding._session.get")
def test_reverse_geocode_label_parses_city_state(mock_get):
    reverse_geocode_label.cache_clear()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {
        "address": {
            "city": "Chicago",
            "state": "Illinois",
            "country": "United States",
        }
    }
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    label = reverse_geocode_label(41.88, -87.63)
    assert isinstance(label, PlaceLabel)
    assert label.short_label == "Chicago, Illinois"


@patch("services.geocoding._session.get")
def test_reverse_geocode_label_returns_none_on_missing_address(mock_get):
    reverse_geocode_label.cache_clear()
    mock_resp = MagicMock()
    mock_resp.json.return_value = {}
    mock_resp.raise_for_status.return_value = None
    mock_get.return_value = mock_resp

    label = reverse_geocode_label(0.0, 0.0)
    assert label is None
