"""Lightweight reverse geocoding helpers using OpenStreetMap Nominatim.

The API surface is intentionally small so it can be reused by PDF rendering
and, later, other presentation layers without introducing heavy dependencies.
"""

from __future__ import annotations

import os
import time
import threading
import logging
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Iterable, Optional, Tuple

import requests

NOMINATIM_BASE_URL = "https://nominatim.openstreetmap.org/reverse"
logger = logging.getLogger(__name__)
_session = requests.Session()
_last_request_ts: float = 0.0
_lock = threading.Lock()
_MIN_INTERVAL_SEC = float(os.getenv("NOMINATIM_MIN_INTERVAL", "1.1"))
_logged_ua = False
NOMINATIM_USER_AGENT = os.getenv("NOMINATIM_USER_AGENT")
NOMINATIM_REFERER = os.getenv("NOMINATIM_REFERER")

FALLBACK_UA = "photo-album-pipeline/0.1 (contact: example@example.com)"
if NOMINATIM_USER_AGENT is None:
    logger.warning(
        "NOMINATIM_USER_AGENT not set in environment; using fallback UA. "
        "This may violate Nominatim usage policy."
    )

def _redact_email(ua: str) -> str:
    if "@" not in ua:
        return ua
    return re.sub(r"\\S+@\\S+", "<redacted>", ua)

_ua_value = NOMINATIM_USER_AGENT or FALLBACK_UA
NOMINATIM_HEADERS = {
    "User-Agent": _ua_value,
}
if NOMINATIM_REFERER:
    NOMINATIM_HEADERS["Referer"] = NOMINATIM_REFERER


@dataclass(frozen=True)
class PlaceLabel:
    city: Optional[str] = None
    state: Optional[str] = None
    country: Optional[str] = None

    @property
    def short_label(self) -> Optional[str]:
        """Return a concise label, preferring city/state when available."""
        parts: list[str] = []
        if self.city and self.state:
            parts = [self.city, self.state]
        elif self.city and self.country:
            parts = [self.city, self.country]
        elif self.state and self.country:
            parts = [self.state, self.country]
        elif self.city:
            parts = [self.city]
        elif self.country:
            parts = [self.country]
        else:
            return None
        return ", ".join(parts)


def _round_coord(value: float, decimals: int = 3) -> float:
    """Round coordinates before caching / lookup to limit request diversity."""
    return round(value, decimals)


def _throttled_get(
    url: str,
    *,
    params: dict[str, Any],
    headers: dict[str, str],
    timeout: float,
) -> requests.Response:
    """Perform a GET request with a simple global rate limit."""
    global _last_request_ts
    with _lock:
        now = time.time()
        delta = now - _last_request_ts
        if delta < _MIN_INTERVAL_SEC:
            time.sleep(_MIN_INTERVAL_SEC - delta)
        _last_request_ts = time.time()
    return _session.get(url, params=params, headers=headers, timeout=timeout)


@lru_cache(maxsize=512)
def reverse_geocode_label(lat: float, lon: float) -> Optional[PlaceLabel]:
    """Reverse geocode a coordinate into a PlaceLabel using Nominatim.

    Returns None on network or parsing errors. Results are cached and inputs
    rounded to avoid hammering the upstream service.
    """
    lat = _round_coord(lat)
    lon = _round_coord(lon)

    params = {
        "format": "jsonv2",
        "lat": str(lat),
        "lon": str(lon),
        "zoom": "10",  # city / region-ish
        "addressdetails": "1",
    }

    global _logged_ua
    if not _logged_ua:
        logger.debug("Nominatim User-Agent: %s", _redact_email(_ua_value))
        _logged_ua = True

    logger.debug(
        "Nominatim reverse geocode: url=%s lat=%s lon=%s params=%r ua_set=%s referer_set=%s",
        NOMINATIM_BASE_URL,
        lat,
        lon,
        params,
        bool(NOMINATIM_USER_AGENT),
        bool(NOMINATIM_REFERER),
    )

    try:
        resp = _throttled_get(
            NOMINATIM_BASE_URL, params=params, headers=NOMINATIM_HEADERS, timeout=5.0
        )
        if resp.status_code != 200:
            logger.warning(
                "Nominatim reverse geocode failed: %s %s ua_set=%s referer_set=%s",
                resp.status_code,
                resp.text[:1000],
                bool(NOMINATIM_USER_AGENT),
                bool(NOMINATIM_REFERER),
            )
            resp.raise_for_status()
        data = resp.json()
        logger.debug(
            "Nominatim reverse geocode success: keys=%s",
            list(data.keys()) if isinstance(data, dict) else data.__class__.__name__,
        )
    except requests.HTTPError as e:
        resp = getattr(e, "response", None)
        body_snippet = ""
        if resp is not None:
            try:
                body_snippet = resp.text[:1000]
            except Exception:
                body_snippet = "<could not read response body>"

        logger.warning(
            "Nominatim reverse geocode HTTPError lat=%s lon=%s status=%s: %s\nResponse body (truncated):\n%s",
            lat,
            lon,
            getattr(resp, "status_code", "?"),
            e,
            body_snippet,
        )
        return None
    except requests.RequestException as e:
        logger.warning(
            "Nominatim reverse geocode error for lat=%s lon=%s: %s", lat, lon, e
        )
        return None
    except Exception as e:  # pragma: no cover - defensive
        logger.warning(
            "Nominatim reverse geocode unexpected error for lat=%s lon=%s: %s",
            lat,
            lon,
            e,
        )
        return None

    address = data.get("address") or {}
    city = (
        address.get("city")
        or address.get("town")
        or address.get("village")
        or address.get("hamlet")
    )
    state = address.get("state")
    country = address.get("country")

    label = PlaceLabel(city=city, state=state, country=country)
    if not label.short_label:
        return None
    return label


def compute_centroid(points: Iterable[Tuple[float, float]]) -> Optional[Tuple[float, float]]:
    """Compute the centroid of a collection of (lat, lon) points."""
    pts = list(points)
    if not pts:
        return None
    lat_sum = 0.0
    lon_sum = 0.0
    for lat, lon in pts:
        lat_sum += lat
        lon_sum += lon
    return (lat_sum / len(pts), lon_sum / len(pts))
