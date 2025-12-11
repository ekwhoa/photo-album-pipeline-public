"""
Lightweight Places client using Nominatim (OSM) with shared rate limiting and headers.
"""
from __future__ import annotations

import logging
from typing import List, Optional

from services.geocoding import NOMINATIM_BASE_URL, NOMINATIM_HEADERS, _throttled_get
from services.places_cache_sqlite import PlacesCache, get_default_places_cache
from services.places_types import PlaceResult


class PlacesClient:
    def __init__(
        self,
        provider: str = "osm",
        base_url: Optional[str] = None,
        cache: Optional[PlacesCache] = None,
        default_radius_m: float = 200.0,
    ):
        self.provider = provider
        base = base_url or NOMINATIM_BASE_URL
        if base.endswith("/reverse"):
            base = base.rsplit("/", 1)[0]
        self.base_url = base.rstrip("/")
        self.cache = cache or get_default_places_cache()
        self.default_radius_m = default_radius_m
        self.logger = logging.getLogger(__name__)

    def _reverse_lookup(self, lat: float, lon: float, zoom: int = 18) -> Optional[dict]:
        params = {
            "format": "jsonv2",
            "lat": str(lat),
            "lon": str(lon),
            "zoom": str(zoom),
            "addressdetails": "1",
            "namedetails": "1",
        }
        try:
            resp = _throttled_get(
                f"{self.base_url}/reverse",
                params=params,
                headers=NOMINATIM_HEADERS,
                timeout=5.0,
            )
            if not resp:
                return None
            return resp.json()
        except Exception:
            return None

    def search_nearby(
        self,
        lat: float,
        lon: float,
        radius_m: float,
        kind: Optional[str] = None,
        max_results: int = 10,
    ) -> List[PlaceResult]:
        radius = radius_m or self.default_radius_m
        cached = self.cache.get_places(
            provider=self.provider,
            lat=lat,
            lon=lon,
            radius_m=radius,
            kind=kind,
        )
        if cached is not None:
            return cached

        data = self._reverse_lookup(lat, lon) or {}

        results: List[PlaceResult] = []
        if data:
            try:
                types = [t for t in (data.get("category"), data.get("type")) if t]
                name = data.get("name") or data.get("display_name") or ""
                results.append(
                    PlaceResult(
                        provider=self.provider,
                        place_id=str(data.get("place_id", "")),
                        name=name,
                        lat=float(data.get("lat", 0.0)),
                        lon=float(data.get("lon", 0.0)),
                        types=types,
                        confidence=float(data.get("importance", 1.0) or 1.0),
                        raw=data,
                    )
                )
            except Exception:
                results = []

        try:
            self.cache.put_places(
                provider=self.provider,
                lat=lat,
                lon=lon,
                radius_m=radius,
                kind=kind,
                places=results,
                ttl_seconds=None,
            )
        except Exception:
            pass
        self.logger.debug(
            "PlacesClient.search_nearby: provider=%s lat=%.6f lon=%.6f radius_m=%.1f kind=%s got %d results",
            self.provider,
            lat,
            lon,
            radius,
            kind,
            len(results),
        )
        return results


_default_places_client: Optional[PlacesClient] = None


def get_default_places_client() -> PlacesClient:
    global _default_places_client
    if _default_places_client is None:
        _default_places_client = PlacesClient()
    return _default_places_client
