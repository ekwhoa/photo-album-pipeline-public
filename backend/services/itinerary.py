from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple

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
