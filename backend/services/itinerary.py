from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional, Tuple, Sequence
import math

from domain.models import (
    Asset,
    Book,
    Day,
    ItineraryDay,
    ItineraryStop,
)
import os
from services.geocoding import compute_centroid, reverse_geocode_label
from domain.models import ItineraryLocation
from services.book_planner import _build_segments_for_day, _build_segment_summaries


ITINERARY_MAX_KM_PER_DAY = float(os.getenv("ITINERARY_MAX_KM_PER_DAY", "800"))
MAX_PHOTO_DISTANCE_KM = 0.25
MAX_THUMBS_PER_PLACE = 6


def _classify_stop_kind(distance_km: float, duration_hours: float) -> str:
    """
    Classify a stop as 'travel' or 'local' using simple heuristics.
    """
    if distance_km >= 150 or duration_hours >= 4:
        return "travel"
    return "local"


def _bucket_time_of_day(ts: Optional[datetime]) -> Optional[str]:
    """
    Bucket a datetime into morning/afternoon/evening/night. Returns None if ts is None.
    """
    if ts is None:
        return None
    hour = ts.hour
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "night"


def _label_from_polyline(polyline: Optional[List[Tuple[float, float]]]) -> Tuple[Optional[str], Optional[str]]:
    """Compute (short, full) labels from a polyline centroid using the geocoder."""
    if not polyline:
        return None, None
    centroid = compute_centroid(polyline)
    if not centroid:
        return None, None
    place = reverse_geocode_label(*centroid)
    if not place:
        return None, None
    short = place.short_label
    full_parts = [p for p in (place.city, place.state, place.country) if p]
    full = ", ".join(full_parts) if full_parts else None
    return short, full


def _build_day_location_lines(stops: List[ItineraryStop]) -> List[str]:
    """
    Collapse raw PlaceLabel data for a day's stops into a small, ordered list of
    human-friendly lines, with minimal duplication.
    """
    lines: List[str] = []
    seen_keys: set[str] = set()
    for stop in stops:
        candidates = [stop.location_full, stop.location_short]
        for label in candidates:
            key = _normalize_location_key(label)
            if key and key not in seen_keys and label:
                seen_keys.add(key)
                lines.append(label)
    # TODO: later, incorporate neighborhood / POI tiers here.
    return lines


def _truncate_label_to_two_parts(label: str) -> str:
    """
    For display only: truncate a comma-separated place label to at most
    two parts (e.g., "Chicago, Illinois, United States" -> "Chicago, Illinois").
    """
    parts = [p.strip() for p in label.split(",") if p.strip()]
    if len(parts) <= 2:
        return ", ".join(parts)
    return ", ".join(parts[:2])


def _normalize_location_key(label: Optional[str]) -> str:
    """
    Normalize a human-readable label into a key just for grouping/dedup.
    We DO NOT change the display label, we only group similar strings.
    """
    if not label:
        return ""
    parts = [p.strip().lower() for p in label.split(",") if p.strip()]
    if not parts:
        return ""
    if len(parts) >= 2:
        return f"{parts[0]}, {parts[1]}"
    return parts[0]


def _is_reasonable_day_distance_km(total_km: Optional[float]) -> bool:
    if total_km is None:
        return False
    if total_km < 0:
        return False
    return total_km <= ITINERARY_MAX_KM_PER_DAY


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute distance in kilometers between two lat/lon points."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def _asset_latlon(asset: Asset) -> Optional[Tuple[float, float]]:
    """Extract a usable lat/lon from asset metadata if present."""
    if not asset or not asset.metadata:
        return None
    lat = asset.metadata.gps_lat
    lon = asset.metadata.gps_lon
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    loc = asset.metadata.location or {}
    lat = loc.get("lat")
    lon = loc.get("lon") if "lon" in loc else loc.get("lng")
    if lat is not None and lon is not None:
        return float(lat), float(lon)
    return None


def _collect_photo_ids_for_place(
    center_lat: float,
    center_lon: float,
    photos: Sequence[Asset],
    max_distance_km: float = MAX_PHOTO_DISTANCE_KM,
) -> list[str]:
    """Collect photo IDs whose GPS is within a small radius of the place center."""
    ids: list[str] = []
    seen: set[str] = set()
    for photo in photos:
        coords = _asset_latlon(photo)
        if not coords:
            continue
        plat, plon = coords
        if _haversine_km(center_lat, center_lon, plat, plon) <= max_distance_km:
            if photo.id not in seen:
                seen.add(photo.id)
                ids.append(photo.id)
    return ids


def _score_place_candidate(place: "PlaceCandidate") -> float:
    """Compute a simple importance score for sorting/debug purposes."""
    visits_weight = 2.0
    photos_weight = 0.1
    duration_weight = 1.0
    distance_weight = 0.05
    return (
        visits_weight * (place.visit_count or 0)
        + photos_weight * (place.total_photos or 0)
        + duration_weight * (place.total_duration_hours or 0.0)
        + distance_weight * (place.total_distance_km or 0.0)
    )


def build_place_candidates(
    itinerary: List[ItineraryDay],
    photos: Optional[Sequence[Asset]] = None,
) -> List[PlaceCandidate]:
    """
    Aggregate nearby local stops into candidate places for future POI labeling.
    """
    clusters: List[dict] = []
    if not itinerary:
        return []
    photos = photos or []

    for idx, day in enumerate(itinerary):
        day_index = getattr(day, "day_index", idx + 1)
        stops = getattr(day, "stops", None) or []
        for stop in stops:
            if getattr(stop, "kind", None) != "local":
                continue
            polyline = getattr(stop, "polyline", None)
            if not polyline:
                continue
            centroid = compute_centroid(polyline)
            if centroid is None:
                try:
                    centroid = polyline[0]
                except Exception:
                    continue
            lat, lon = centroid
            duration = getattr(stop, "duration_hours", None) or 0.0
            distance = getattr(stop, "distance_km", None) or 0.0

            merged = False
            for cluster in clusters:
                dist_km = _haversine_km(lat, lon, cluster["center_lat"], cluster["center_lon"])
                if dist_km <= 0.1:
                    count = cluster["visit_count"]
                    new_count = count + 1
                    cluster["center_lat"] = (cluster["center_lat"] * count + lat) / new_count
                    cluster["center_lon"] = (cluster["center_lon"] * count + lon) / new_count
                    cluster["total_duration_hours"] += duration
                    cluster["total_distance_km"] += distance
                    cluster["visit_count"] = new_count
                    if day_index not in cluster["day_indices"]:
                        cluster["day_indices"].append(day_index)
                    merged = True
                    break

            if not merged:
                clusters.append(
                    {
                        "center_lat": lat,
                        "center_lon": lon,
                        "total_duration_hours": duration,
                        "total_photos": 0,
                        "total_distance_km": distance,
                        "visit_count": 1,
                        "day_indices": [day_index],
                    }
                )

    photo_lookup = {p.id: p for p in photos} if photos else {}
    if photos:
        for cluster in clusters:
            photo_ids = _collect_photo_ids_for_place(
                cluster["center_lat"],
                cluster["center_lon"],
                photos,
            )
            cluster["photo_ids"] = photo_ids
            cluster["total_photos"] = len(photo_ids)
    else:
        for cluster in clusters:
            cluster["photo_ids"] = []

    candidates = [
        PlaceCandidate(
            center_lat=c["center_lat"],
            center_lon=c["center_lon"],
            total_duration_hours=c["total_duration_hours"],
            total_photos=c["total_photos"],
            total_distance_km=c["total_distance_km"],
            visit_count=c["visit_count"],
            day_indices=sorted(c["day_indices"]),
            score=0.0,
            best_place_name=None,
            thumbnails=[
                PlaceCandidateThumbnail(
                    id=pid,
                    thumbnail_path=photo_lookup.get(pid).thumbnail_path if pid in photo_lookup else None,
                    file_path=photo_lookup.get(pid).file_path if pid in photo_lookup else None,
                )
                for pid in (c.get("photo_ids") or [])[:MAX_THUMBS_PER_PLACE]
                if pid in photo_lookup
            ],
        )
        for c in clusters
    ]

    for candidate in candidates:
        candidate.score = _score_place_candidate(candidate)

    candidates.sort(key=lambda c: c.score, reverse=True)

    MAX_CANDIDATES = 50
    if len(candidates) > MAX_CANDIDATES:
        candidates = candidates[:MAX_CANDIDATES]
    return candidates


@dataclass
class PlaceCandidate:
    center_lat: float
    center_lon: float
    total_duration_hours: float
    total_photos: int
    total_distance_km: float
    visit_count: int
    day_indices: List[int]
    score: float = 0.0
    best_place_name: Optional[str] = None
    raw_name: Optional[str] = None  # short name from Nominatim (e.g. 'Alinea')
    display_name: Optional[str] = None  # cleaned, book-ready name for UI/PDF
    thumbnails: List["PlaceCandidateThumbnail"] = field(default_factory=list)


@dataclass
class PlaceCandidateThumbnail:
    id: str
    thumbnail_path: Optional[str] = None
    file_path: Optional[str] = None


def build_book_itinerary(book: Book, days: List[Day], assets: List[Asset]) -> List[ItineraryDay]:
    """Build an itinerary (by day) using existing segment summaries and geocoding."""
    asset_lookup = {a.id: a for a in assets}
    itinerary_days: List[ItineraryDay] = []

    for idx_day, day in enumerate(days):
        day_asset_ids = [entry.asset_id for entry in day.all_entries]
        ordered_assets: List[Asset] = []
        for aid in day_asset_ids:
            if aid in asset_lookup:
                ordered_assets.append(asset_lookup[aid])
        ordered_assets.sort(
            key=lambda a: (
                a.metadata.taken_at is None if a.metadata else True,
                a.metadata.taken_at if a.metadata and a.metadata.taken_at else datetime.min,
            )
        )

        segments_raw, *_ = _build_segments_for_day(ordered_assets)
        summaries = _build_segment_summaries(segments_raw, asset_lookup)

        stops: List[ItineraryStop] = []
        day_locations: List[ItineraryLocation] = []
        seen_keys: set[str] = set()

        for summary in summaries:
            polyline = summary.get("polyline")
            short, full = _label_from_polyline(polyline)
            display_label = None
            if full:
                display_label = _truncate_label_to_two_parts(full)
            elif short:
                display_label = _truncate_label_to_two_parts(short)
            distance_km = summary.get("distance_km", 0.0) or 0.0
            duration_hours = summary.get("duration_hours", 0.0) or 0.0
            kind = _classify_stop_kind(distance_km, duration_hours)
            time_bucket = None  # No per-segment timestamps yet; reserved for future use.
            stops.append(
                ItineraryStop(
                    segment_index=summary.get("index", len(stops) + 1),
                    distance_km=distance_km,
                    duration_hours=duration_hours,
                    location_short=short,
                    location_full=full,
                    polyline=polyline,
                    kind=kind,
                    time_bucket=time_bucket,
                )
            )
            key = _normalize_location_key(display_label or short or full)
            if key and key not in seen_keys and display_label:
                seen_keys.add(key)
                day_locations.append(
                    ItineraryLocation(
                        location_short=display_label,
                        location_full=display_label,
                    )
                )

        total_distance = sum(stop.distance_km for stop in stops)
        total_duration = sum(stop.duration_hours for stop in stops)

        # Day-level label from all points
        all_points: List[Tuple[float, float]] = []
        for stop in stops:
            if stop.polyline:
                all_points.extend(stop.polyline)
        day_short, day_full = _label_from_polyline(all_points) if all_points else (None, None)
        if day_short:
            day_short = _truncate_label_to_two_parts(day_short)
        if day_full:
            day_full = _truncate_label_to_two_parts(day_full)
        location_lines = _build_day_location_lines(stops)
        if location_lines:
            # Use first distinct label as primary short; second as full when available
            day_short = day_short or location_lines[0]
            if len(location_lines) > 1:
                day_full = day_full or location_lines[1]
        itinerary_locations = day_locations or [
            ItineraryLocation(location_short=None, location_full=line) for line in location_lines
        ]

        date_iso = day.date.date().isoformat() if day.date else ""

        display_distance = total_distance if _is_reasonable_day_distance_km(total_distance) else None
        itinerary_days.append(
            ItineraryDay(
                day_index=(day.index + 1) if day.index is not None else (idx_day + 1),
                date_iso=date_iso,
                photos_count=len(ordered_assets),
                segments_total_distance_km=total_distance,
                segments_total_duration_hours=total_duration,
                location_short=day_short,
                location_full=day_full,
                locations=itinerary_locations,
                stops=stops,
            )
        )

    return itinerary_days
