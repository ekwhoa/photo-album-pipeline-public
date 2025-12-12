from dataclasses import dataclass
from typing import List, Optional


@dataclass
class PlaceResult:
    provider: str  # e.g. "osm", "google", "here"
    place_id: str  # provider-specific place/venue id
    name: str
    lat: float
    lon: float
    types: List[str]
    confidence: float
    raw: Optional[dict] = None
    display_name: Optional[str] = None  # cleaned, book-ready name (derived from raw Nominatim data)
