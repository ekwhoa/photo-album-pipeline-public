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
from services.geocoding import compute_centroid, reverse_geocode_label
from services.book_planner import _build_segments_for_day, _build_segment_summaries


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
        for summary in summaries:
            polyline = summary.get("polyline")
            short, full = _label_from_polyline(polyline)
            stops.append(
                ItineraryStop(
                    segment_index=summary.get("index", len(stops) + 1),
                    distance_km=summary.get("distance_km", 0.0) or 0.0,
                    duration_hours=summary.get("duration_hours", 0.0) or 0.0,
                    location_short=short,
                    location_full=full,
                    polyline=polyline,
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

        date_iso = day.date.date().isoformat() if day.date else ""
        itinerary_days.append(
            ItineraryDay(
                day_index=(day.index + 1) if day.index is not None else (idx_day + 1),
                date_iso=date_iso,
                photos_count=len(ordered_assets),
                segments_total_distance_km=total_distance,
                segments_total_duration_hours=total_duration,
                location_short=day_short,
                location_full=day_full,
                stops=stops,
            )
        )

    return itinerary_days
