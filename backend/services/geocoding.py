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
import sqlite3
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
NOMINATIM_CACHE_PATH = os.getenv("NOMINATIM_CACHE_PATH")
if not NOMINATIM_CACHE_PATH:
    NOMINATIM_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "geocode_cache.sqlite")
NOMINATIM_CACHE_TTL_SECONDS = int(os.getenv("NOMINATIM_CACHE_TTL_SECONDS", str(180 * 24 * 3600)))

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

_CACHE_DB_LOCK = threading.Lock()
_CACHE_DB: Optional[sqlite3.Connection] = None


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


def _get_geocode_db() -> sqlite3.Connection:
    """Lazily open the geocode cache DB and ensure schema exists."""
    global _CACHE_DB
    with _CACHE_DB_LOCK:
        if _CACHE_DB is None:
            os.makedirs(os.path.dirname(NOMINATIM_CACHE_PATH), exist_ok=True)
            _CACHE_DB = sqlite3.connect(NOMINATIM_CACHE_PATH)
            _CACHE_DB.execute(
                """
                CREATE TABLE IF NOT EXISTS geocodes (
                    lat REAL NOT NULL,
                    lon REAL NOT NULL,
                    zoom INTEGER NOT NULL,
                    fetched_at INTEGER NOT NULL,
                    short_label TEXT,
                    full_label TEXT,
                    PRIMARY KEY (lat, lon, zoom)
                )
                """
            )
            _CACHE_DB.commit()
        return _CACHE_DB


def _get_geocode_from_cache(lat: float, lon: float, zoom: int) -> Optional[PlaceLabel]:
    """Lookup geocode result in SQLite cache respecting TTL."""
    try:
        db = _get_geocode_db()
        cur = db.execute(
            "SELECT fetched_at, short_label, full_label FROM geocodes WHERE lat=? AND lon=? AND zoom=?",
            (lat, lon, zoom),
        )
        row = cur.fetchone()
        if not row:
            print(f"[GEOCODE] cache miss {lat},{lon} z={zoom}")
            return None
        fetched_at, short_label, full_label = row
        if NOMINATIM_CACHE_TTL_SECONDS > 0:
            age = time.time() - (fetched_at or 0)
            if age > NOMINATIM_CACHE_TTL_SECONDS:
                print(f"[GEOCODE] cache expired {lat},{lon} z={zoom}")
                return None
        print(f"[GEOCODE] cache hit {lat},{lon} z={zoom}")
        label = PlaceLabel(city=None, state=None, country=None)
        # Rebuild label from stored strings where possible
        # We can't fully reconstruct city/state/country reliably from short/full,
        # so store in short_label/full_label form.
        # Use full_label first if it exists, otherwise short_label.
        if full_label:
            parts = [p.strip() for p in full_label.split(",") if p.strip()]
            if len(parts) >= 3:
                label = PlaceLabel(city=parts[0], state=parts[1], country=parts[2])
            elif len(parts) == 2:
                label = PlaceLabel(city=parts[0], state=parts[1], country=None)
            elif len(parts) == 1:
                label = PlaceLabel(city=parts[0], state=None, country=None)
        elif short_label:
            parts = [p.strip() for p in short_label.split(",") if p.strip()]
            if len(parts) >= 3:
                label = PlaceLabel(city=parts[0], state=parts[1], country=parts[2])
            elif len(parts) == 2:
                label = PlaceLabel(city=parts[0], state=parts[1], country=None)
            elif len(parts) == 1:
                label = PlaceLabel(city=parts[0], state=None, country=None)
        return label if label.short_label else None
    except Exception as exc:
        print(f"[GEOCODE] cache read failed for {lat},{lon} z={zoom}: {exc}")
        return None


def _store_geocode_in_cache(lat: float, lon: float, zoom: int, label: PlaceLabel) -> None:
    """Upsert geocode result into SQLite cache."""
    try:
        db = _get_geocode_db()
        db.execute(
            "INSERT OR REPLACE INTO geocodes (lat, lon, zoom, fetched_at, short_label, full_label) VALUES (?, ?, ?, ?, ?, ?)",
            (lat, lon, zoom, int(time.time()), label.short_label, label.short_label),
        )
        db.commit()
        print(f"[GEOCODE] cache store {lat},{lon} z={zoom}")
    except Exception as exc:
        print(f"[GEOCODE] cache write failed for {lat},{lon} z={zoom}: {exc}")
        return


@lru_cache(maxsize=512)
def reverse_geocode_label(lat: float, lon: float) -> Optional[PlaceLabel]:
    """Reverse geocode a coordinate into a PlaceLabel using Nominatim.

    Returns None on network or parsing errors. Results are cached and inputs
    rounded to avoid hammering the upstream service.
    """
    lat_r = _round_coord(lat)
    lon_r = _round_coord(lon)
    zoom_val = 10

    cached = _get_geocode_from_cache(lat_r, lon_r, zoom_val)
    if cached:
        return cached
    print(f"[GEOCODE] cache miss {lat_r},{lon_r} z={zoom_val}")

    global _logged_ua
    if not _logged_ua:
        logger.debug("Nominatim User-Agent: %s", _redact_email(_ua_value))
        _logged_ua = True

    params = {
        "format": "jsonv2",
        "lat": str(lat_r),
        "lon": str(lon_r),
        "zoom": str(zoom_val),
        "addressdetails": "1",
    }

    try:
        resp = _throttled_get(
            NOMINATIM_BASE_URL, params=params, headers=NOMINATIM_HEADERS, timeout=5.0
        )
    except Exception as exc:
        logger.warning(
            "Nominatim reverse geocode error for lat=%s lon=%s: %s", lat_r, lon_r, exc
        )
        return None

    if resp is None:
        return None

    try:
        data = resp.json()
    except Exception as exc:
        logger.warning(
            "Nominatim reverse geocode JSON error for lat=%s lon=%s: %s",
            lat_r,
            lon_r,
            exc,
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
    try:
        _store_geocode_in_cache(lat_r, lon_r, zoom_val, label)
    except Exception as exc:  # pragma: no cover
        print(f"[GEOCODE] cache store error for {lat_r},{lon_r} z={zoom_val}: {exc}")
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
