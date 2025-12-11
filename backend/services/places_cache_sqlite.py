"""
SQLite-backed cache for place lookups (infrastructure for future Place API calls).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from typing import List, Optional

from services.places_types import PlaceResult

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DATA_DIR = os.path.join(BASE_DIR, "data")
PLACES_CACHE_DB_FILENAME = "places_cache.sqlite"


def _quantize_coord(value: float, step: float = 0.0005) -> float:
    """Quantize coordinates to reduce cache key diversity (~50m grid)."""
    return round(value / step) * step


class PlacesCache:
    def __init__(self, db_path: Optional[str] = None, default_ttl_seconds: int = 30 * 24 * 3600):
        self.db_path = db_path or os.path.join(DATA_DIR, PLACES_CACHE_DB_FILENAME)
        self.default_ttl_seconds = default_ttl_seconds
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS place_cache (
                id INTEGER PRIMARY KEY,
                provider TEXT NOT NULL,
                key_lat REAL NOT NULL,
                key_lon REAL NOT NULL,
                radius_m REAL NOT NULL,
                kind TEXT,
                response_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                ttl_seconds INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_place_cache_key
            ON place_cache(provider, key_lat, key_lon, radius_m, kind)
            """
        )
        self._conn.commit()

    def _row_to_results(self, row: sqlite3.Row) -> Optional[List[PlaceResult]]:
        if not row:
            return None
        _, _, _, _, _, _, response_json, created_at, ttl_seconds = row
        if ttl_seconds > 0 and (time.time() - created_at) > ttl_seconds:
            return None
        try:
            payload = json.loads(response_json)
        except Exception:
            return None
        results: List[PlaceResult] = []
        for item in payload or []:
            try:
                results.append(
                    PlaceResult(
                        provider=item.get("provider", ""),
                        place_id=item.get("place_id", ""),
                        name=item.get("name", ""),
                        lat=float(item.get("lat", 0.0)),
                        lon=float(item.get("lon", 0.0)),
                        types=item.get("types", []) or [],
                        confidence=float(item.get("confidence", 0.0)),
                        raw=item.get("raw"),
                    )
                )
            except Exception:
                continue
        return results or None

    def get_places(
        self,
        provider: str,
        lat: float,
        lon: float,
        radius_m: float,
        kind: Optional[str] = None,
    ) -> Optional[List[PlaceResult]]:
        """
        Return cached PlaceResult list if non-expired entry exists for key.
        """
        key_lat = _quantize_coord(lat)
        key_lon = _quantize_coord(lon)
        try:
            cur = self._conn.execute(
                """
                SELECT * FROM place_cache
                WHERE provider=? AND key_lat=? AND key_lon=? AND radius_m=? AND kind IS ?
                LIMIT 1
                """,
                (provider, key_lat, key_lon, radius_m, kind),
            )
            row = cur.fetchone()
            return self._row_to_results(row)
        except Exception:
            return None

    def put_places(
        self,
        provider: str,
        lat: float,
        lon: float,
        radius_m: float,
        kind: Optional[str],
        places: List[PlaceResult],
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """Store PlaceResult list in cache for key."""
        key_lat = _quantize_coord(lat)
        key_lon = _quantize_coord(lon)
        ttl = ttl_seconds if ttl_seconds is not None else self.default_ttl_seconds
        payload = [
            {
                "provider": p.provider,
                "place_id": p.place_id,
                "name": p.name,
                "lat": p.lat,
                "lon": p.lon,
                "types": p.types,
                "confidence": p.confidence,
                "raw": p.raw,
            }
            for p in places
        ]
        try:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO place_cache
                (id, provider, key_lat, key_lon, radius_m, kind, response_json, created_at, ttl_seconds)
                VALUES (
                    (SELECT id FROM place_cache WHERE provider=? AND key_lat=? AND key_lon=? AND radius_m=? AND kind IS ?),
                    ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    provider,
                    key_lat,
                    key_lon,
                    radius_m,
                    kind,
                    provider,
                    key_lat,
                    key_lon,
                    radius_m,
                    kind,
                    json.dumps(payload),
                    int(time.time()),
                    ttl,
                ),
            )
            self._conn.commit()
        except Exception:
            return


_default_places_cache: Optional[PlacesCache] = None


def get_default_places_cache() -> PlacesCache:
    global _default_places_cache
    if _default_places_cache is None:
        _default_places_cache = PlacesCache()
    return _default_places_cache
