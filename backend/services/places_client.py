"""
Lightweight Places client using Nominatim (OSM) with shared rate limiting and headers.
"""
from __future__ import annotations

import logging
import re
from typing import List, Optional

from services.geocoding import NOMINATIM_BASE_URL, NOMINATIM_HEADERS, _throttled_get
from services.places_cache_sqlite import PlacesCache, get_default_places_cache
from services.places_types import PlaceResult


def format_place_display_name(result: PlaceResult) -> str:
    """
    Produce a short, book-ready display name for a place.

    Rules:
    - Prefer a concrete 'name' when Nominatim gives one (e.g. 'Alinea', 'Hotel EMC2').
    - If 'name' is missing, build something compact from the address or raw Nominatim data.
    - Strip boilerplate suffixes like 'United States', state, ZIP, county, township, etc.
    - Keep it relatively short (< 60 chars); truncate with '…' if necessary.
    """
    if result.name and result.name.strip():
        name = result.name.strip()
        if len(name) > 60:
            name = name[:57] + "…"
        return name

    # Try to extract from raw Nominatim data if available
    raw = result.raw or {}
    
    # Attempt to build from address parts if available
    address = raw.get("address", {})
    if isinstance(address, dict):
        # Prefer: house_number + road, or just road + city
        parts = []
        if address.get("house_number"):
            parts.append(str(address["house_number"]))
        if address.get("road"):
            parts.append(str(address["road"]))
        elif address.get("street"):
            parts.append(str(address["street"]))
        
        if not parts and address.get("street_name"):
            parts.append(str(address["street_name"]))
        
        # Add city if we only have a street
        if len(parts) < 2 and address.get("city"):
            parts.append(str(address["city"]))
        elif len(parts) == 0 and address.get("city"):
            parts.append(str(address["city"]))
        
        if parts:
            result_str = ", ".join(p for p in parts if p)
            if len(result_str) > 60:
                result_str = result_str[:57] + "…"
            return result_str
    
    # Fallback: trim the Nominatim display_name heavily
    display_name = raw.get("display_name", "")
    if display_name:
        # Split on comma and filter out boilerplate
        boilerplate_tokens = {
            "united states", "usa", "county", "township", "state",
            "zip code", "postal code", "province", "region"
        }
        parts = [p.strip() for p in display_name.split(",")]
        filtered = []
        for part in parts:
            lower_part = part.lower()
            # Skip obvious boilerplate
            if lower_part in boilerplate_tokens:
                continue
            # Skip ZIP/postal codes
            if re.match(r'^\d{5}(-\d{4})?$', part):
                continue
            filtered.append(part)
        
        # Keep first 2-3 components
        result_str = ", ".join(filtered[:3])
        if len(result_str) > 60:
            result_str = result_str[:57] + "…"
        return result_str if result_str else f"({result.lat:.4f}, {result.lon:.4f})"
    
    # Last resort: coordinates
    return f"({result.lat:.4f}, {result.lon:.4f})"


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

    def _score_raw_result(self, item: dict) -> tuple:
        venue_classes = {"amenity", "tourism", "leisure", "shop", "place"}
        venue_types = {"restaurant", "bar", "pub", "cafe", "stadium", "theatre", "attraction"}
        has_name = bool(item.get("name"))
        cls = item.get("class")
        typ = item.get("type")
        is_venue_class = cls in venue_classes
        is_venue_type = typ in venue_types
        importance = float(item.get("importance", 0.0) or 0.0)
        return (
            1 if has_name else 0,
            1 if is_venue_class else 0,
            1 if is_venue_type else 0,
            importance,
        )

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
                candidates = data if isinstance(data, list) else [data]
                candidates_sorted = sorted(candidates, key=self._score_raw_result, reverse=True)
                for item in candidates_sorted[:max_results]:
                    types = [t for t in (item.get("category"), item.get("type")) if t]
                    name = item.get("name") or item.get("display_name") or ""
                    place_result = PlaceResult(
                        provider=self.provider,
                        place_id=str(item.get("place_id", "")),
                        name=name,
                        lat=float(item.get("lat", 0.0)),
                        lon=float(item.get("lon", 0.0)),
                        types=types,
                        confidence=float(item.get("importance", 1.0) or 1.0),
                        raw=item,
                    )
                    # Derive display_name from the result
                    place_result.display_name = format_place_display_name(place_result)
                    results.append(place_result)
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
