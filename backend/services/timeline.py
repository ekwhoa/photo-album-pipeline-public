"""
Timeline service for grouping manifest entries into days and events.

This is a key extension point for smarter photo organization.
"""
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Optional, Dict
from domain.models import Asset, Day, Event, Manifest, ManifestEntry


def build_days_and_events(manifest: Manifest) -> List[Day]:
    """
    Group manifest entries into days and events.
    
    Current implementation:
    - Groups photos by date (day)
    - Each day has a single event (all photos from that day)
    
    Future improvements:
    - Time-based event splitting (e.g., morning/afternoon/evening)
    - Location-based event splitting
    - Activity detection
    
    Args:
        manifest: The timeline manifest
    
    Returns:
        List of Day objects, each containing Events
    """
    if not manifest.entries:
        return []
    
    # Group entries by date
    entries_by_date: dict[str, List[ManifestEntry]] = defaultdict(list)
    
    for entry in manifest.entries:
        if entry.timestamp:
            date_key = entry.timestamp.strftime("%Y-%m-%d")
        else:
            date_key = "unknown"
        entries_by_date[date_key].append(entry)
    
    # Sort dates
    sorted_dates = sorted(entries_by_date.keys())
    
    # Build Day objects
    days = []
    for day_index, date_key in enumerate(sorted_dates):
        entries = entries_by_date[date_key]
        
        # Parse date if possible
        day_date = None
        if date_key != "unknown":
            try:
                day_date = datetime.strptime(date_key, "%Y-%m-%d")
            except ValueError:
                pass
        
        # Create a single event per day for now
        # Future: split into multiple events based on time gaps or locations
        event = Event(
            index=0,
            entries=entries,
            name=f"Day {day_index + 1}" if day_date else "Photos",
        )
        
        # Update entry indices
        for i, entry in enumerate(entries):
            entry.day_index = day_index
            entry.event_index = 0
        
        day = Day(
            index=day_index,
            date=day_date,
            events=[event],
        )
        days.append(day)
    
    return days


def get_day_summary(day: Day) -> dict:
    """
    Get a summary of a day for display.
    
    Returns:
        Dict with day info: date, photo count, event count
    """
    return {
        "index": day.index,
        "date": day.date.isoformat() if day.date else None,
        "photo_count": len(day.all_entries),
        "event_count": len(day.events),
    }


# ============================================
# Future: Advanced grouping
# ============================================

def split_by_time_gaps(entries: List[ManifestEntry], 
                       gap_hours: float = 3.0) -> List[List[ManifestEntry]]:
    """
    Placeholder for splitting entries by time gaps.
    
    If there's more than gap_hours between photos, start a new event.
    """
    if not entries:
        return []
    
    groups = [[entries[0]]]
    gap_delta = timedelta(hours=gap_hours)
    
    for entry in entries[1:]:
        prev_time = groups[-1][-1].timestamp
        curr_time = entry.timestamp
        
        if prev_time and curr_time and (curr_time - prev_time) > gap_delta:
            groups.append([entry])
        else:
            groups[-1].append(entry)
    
    return groups


def split_by_location(entries: List[ManifestEntry],
                      distance_km: float = 5.0) -> List[List[ManifestEntry]]:
    """
    Placeholder for splitting entries by location.
    
    Group photos taken within distance_km of each other.
    """
    # TODO: Implement using haversine distance
    return [entries]


class TimelineService:
    """Lightweight organizer to group assets by day for planning."""

    def organize_assets_by_day(self, assets: List[Asset]) -> List[Day]:
        # Group assets by taken_at date (fallback: unknown)
        grouped: Dict[str, List[Asset]] = defaultdict(list)
        for asset in assets:
            if asset.metadata and asset.metadata.taken_at:
                key = asset.metadata.taken_at.date().isoformat()
            else:
                key = "unknown"
            grouped[key].append(asset)

        days: List[Day] = []
        for idx, (key, group) in enumerate(sorted(grouped.items())):
            # Sort within day by taken_at
            group_sorted = sorted(
                group,
                key=lambda a: a.metadata.taken_at if a.metadata and a.metadata.taken_at else datetime.min,
            )
            entries = [
                ManifestEntry(asset_id=a.id, timestamp=a.metadata.taken_at if a.metadata else None)
                for a in group_sorted
            ]
            event = Event(index=0, entries=entries, name=f"Day {idx + 1}" if key != "unknown" else "Photos")
            for i, entry in enumerate(entries):
                entry.day_index = idx
                entry.event_index = 0
            day_date = None
            if key != "unknown":
                try:
                    day_date = datetime.fromisoformat(key)
                except Exception:
                    day_date = None
            days.append(Day(index=idx, date=day_date, events=[event]))

        return days
