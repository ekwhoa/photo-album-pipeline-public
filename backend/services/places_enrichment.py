from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

from services.places_client import get_default_places_client, format_place_display_name
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
    Populate best_place_name, raw_name, and display_name on candidates using PlacesClient when enabled.
    """
    result = list(candidates)
    if not settings.PLACES_LOOKUP_ENABLED:
        return result

    client = get_default_places_client()
    for cand in result[:max_lookups]:
        # If the candidate already has a best_place_name OR the user supplied an override,
        # skip enrichment so we don't clobber a user-provided display name.
        if getattr(cand, "best_place_name", None) or getattr(cand, "override_name", None):
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
        
        # Also populate raw_name and display_name from the best result
        if search:
            best_result = search[0]  # Already sorted by score
            cand.raw_name = best_result.name or None
            cand.display_name = best_result.display_name or format_place_display_name(best_result)
    
    return result
