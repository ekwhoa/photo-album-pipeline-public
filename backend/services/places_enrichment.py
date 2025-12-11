from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from services.places_client import get_default_places_client
from services.places_types import PlaceResult
from services.itinerary import PlaceCandidate
from settings import settings

PREFERRED_TYPES = {"tourism", "attraction", "stadium", "hotel", "restaurant", "park", "museum", "bar", "cafe"}


def _pick_best_place_name(results: Sequence[PlaceResult]) -> Optional[str]:
    best: Optional[PlaceResult] = None
    for r in results:
        if not r.name:
            continue
        if set(r.types or []).intersection(PREFERRED_TYPES):
            best = r
            break
        if best is None:
            best = r
    return best.name if best and best.name else None


def enrich_place_candidates_with_names(
    candidates: Iterable[PlaceCandidate],
    max_lookups: int = 10,
) -> List[PlaceCandidate]:
    """
    Populate best_place_name on candidates using PlacesClient when enabled.
    """
    result = list(candidates)
    if not settings.PLACES_LOOKUP_ENABLED:
        return result

    client = get_default_places_client()
    for cand in result[:max_lookups]:
        if getattr(cand, "best_place_name", None):
            continue
        try:
            search = client.search_nearby(
                cand.center_lat,
                cand.center_lon,
                radius_m=200.0,
                max_results=5,
            )
        except Exception:
            continue
        best_name = _pick_best_place_name(search)
        if best_name:
            cand.best_place_name = best_name
    return result
