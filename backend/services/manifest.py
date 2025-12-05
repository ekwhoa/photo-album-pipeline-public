"""
Manifest builder service.

Builds a timeline manifest from approved assets, which is then
used to organize photos into days and events.
"""
from datetime import datetime
from typing import List, Optional
from domain.models import Asset, Manifest, ManifestEntry


def build_manifest(book_id: str, approved_assets: List[Asset]) -> Manifest:
    """
    Build a manifest/timeline from approved assets.
    
    For now, this creates entries ordered by:
    1. Photo taken date (if available in metadata)
    2. Otherwise by filename/creation order
    
    Args:
        book_id: ID of the book
        approved_assets: List of approved assets
    
    Returns:
        Manifest with ordered entries
    """
    # Sort assets by timestamp if available, otherwise by creation order
    def sort_key(asset: Asset) -> tuple:
        timestamp = asset.metadata.taken_at or asset.created_at
        return (timestamp, asset.id)
    
    sorted_assets = sorted(approved_assets, key=sort_key)
    
    entries = []
    for asset in sorted_assets:
        entry = ManifestEntry(
            asset_id=asset.id,
            timestamp=asset.metadata.taken_at or asset.created_at,
        )
        entries.append(entry)
    
    return Manifest(
        book_id=book_id,
        entries=entries,
    )


def get_date_range(manifest: Manifest) -> tuple[Optional[datetime], Optional[datetime]]:
    """
    Get the date range covered by the manifest.
    
    Returns:
        Tuple of (start_date, end_date) or (None, None) if no timestamps
    """
    timestamps = [e.timestamp for e in manifest.entries if e.timestamp]
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def get_entry_count(manifest: Manifest) -> int:
    """Get the number of entries in the manifest."""
    return len(manifest.entries)
