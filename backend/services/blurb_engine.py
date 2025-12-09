from dataclasses import dataclass
from typing import Optional


@dataclass
class TripSummaryContext:
    num_days: int
    num_photos: int
    num_events: Optional[int] = None
    num_locations: Optional[int] = None


@dataclass
class DayIntroContext:
    photos_count: int
    segments_total_distance_km: Optional[float] = None
    segment_count: Optional[int] = None
    travel_segments_count: int = 0
    local_segments_count: int = 0


def _round_distance_km(distance: float, base: int = 10) -> int:
    """Round distance to a friendly bucket (default: nearest 10km)."""
    if distance <= 0:
        return 0
    return int(round(distance / float(base)) * base)


def build_trip_summary_blurb(ctx: TripSummaryContext) -> str:
    """
    Return a short, deterministic one-liner for the trip summary page.
    """
    days = ctx.num_days
    photos = ctx.num_photos
    events = ctx.num_events or 0
    locations = ctx.num_locations or 0

    # Base sentence
    sentence = f"A {days}-day trip captured in {photos} photos."

    # Enrich with events/locations if present
    if locations >= 20:
        sentence = f"A {days}-day trip with {photos} photos across about {locations} places."
        if events > 0:
            sentence += f" Highlights from {events} key moments."
    else:
        extras = []
        if events > 0:
            extras.append(f"{events} key moment" + ("s" if events != 1 else ""))
        if locations > 0:
            extras.append(f"{locations} spots")
        if extras:
            sentence = f"A {days}-day trip captured in {photos} photos with " + " and ".join(extras) + "."

    return sentence


def build_day_intro_tagline(ctx: DayIntroContext) -> Optional[str]:
    """
    Generate a concise tagline for a day intro page based on distance/time/segments.
    """
    distance = ctx.segments_total_distance_km or 0.0
    segment_count = ctx.segment_count or 0
    photos = ctx.photos_count
    travel_segments = ctx.travel_segments_count or 0
    local_segments = ctx.local_segments_count or 0
    is_travel_heavy = travel_segments > 0 and travel_segments >= local_segments and distance > 100
    is_local_heavy = local_segments > 0 and travel_segments == 0

    # If we truly have no movement data and no photos, bail out
    if segment_count <= 0 and distance < 0.1 and photos <= 0:
        return None

    rounded_km = _round_distance_km(distance, base=10)

    if distance >= 150:
        base = "Big travel day"
        detail = f"covering about {rounded_km} km"
        return f"{base} {detail}"

    if is_travel_heavy:
        return f"Travel day with {travel_segments} segment(s) covering about {rounded_km} km"

    if is_local_heavy and distance < 50:
        return f"Exploring nearby spots with about {photos} photos"

    if distance >= 15:
        base = "Covering some ground"
        detail = f"moving around about {rounded_km} km"
        return f"{base}, {detail}"

    if distance >= 0.3:
        return f"Exploring nearby spots with about {photos} photos"

    # Very low movement
    if photos > 0:
        return f"A relaxed day close to home with {photos} photos"
    return "Staying close to home base today"
