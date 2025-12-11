"""
Lightweight Places client using Nominatim (OSM) with shared rate limiting and headers.
"""
from __future__ import annotations

from typing import List, Optional

from services.geocoding import NOMINATIM_BASE_URL, NOMINATIM_HEADERS, _throttled_get
from services.places_cache_sqlite import PlacesCache, get_default_places_cache
from services.places_types import PlaceResult


def _derive_search_url(base_url: str) -> str:
    if base_url.endswith("/reverse"):
        return base_url.rsplit("/", 1)[0] + "/search"
    return base_url.rstrip("/") + "/search"


class PlacesClient:
    def __init__(
        self,
        provider: str = "osm",
        base_url: Optional[str] = None,
        cache: Optional[PlacesCache] = None,
        default_radius_m: float = 200.0,
    ):
        self.provider = provider
        self.base_url = _derive_search_url(base_url or NOMINATIM_BASE_URL)
        self.cache = cache or get_default_places_cache()
        self.default_radius_m = default_radius_m

    def _search(self, params: dict) -> Optional[List[dict]]:
        try:
            resp = _throttled_get(
                self.base_url,
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

        # Approximate bounding box based search
        deg_per_meter = 1.0 / 111_000.0
        delta_deg = radius * deg_per_meter
        params = {
            "format": "jsonv2",
            "q": kind or "",
            "limit": str(max_results),
            "bounded": 1,
            "viewbox": f"{lon - delta_deg},{lat + delta_deg},{lon + delta_deg},{lat - delta_deg}",
            "lat": str(lat),
            "lon": str(lon),
        }
        data = self._search(params) or []

        results: List[PlaceResult] = []
        for item in data:
            try:
                types = [t for t in (item.get("category"), item.get("type")) if t]
                results.append(
                    PlaceResult(
                        provider=self.provider,
                        place_id=str(item.get("place_id", "")),
                        name=item.get("display_name") or item.get("name") or "",
                        lat=float(item.get("lat", 0.0)),
                        lon=float(item.get("lon", 0.0)),
                        types=types,
                        confidence=float(item.get("importance", 0.0)),
                        raw=item,
                    )
                )
            except Exception:
                continue

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
        return results


_default_places_client: Optional[PlacesClient] = None


def get_default_places_client() -> PlacesClient:
    global _default_places_client
    if _default_places_client is None:
        _default_places_client = PlacesClient()
    return _default_places_client
