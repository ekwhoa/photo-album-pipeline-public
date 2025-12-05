"""
Curation service for managing asset approval workflow.

Currently implements manual curation. Future extensions:
- Automatic blur detection
- Duplicate detection
- Face/scene recognition for grouping
"""
from typing import List, Optional
from domain.models import Asset, AssetStatus


def set_asset_status(asset: Asset, status: AssetStatus) -> Asset:
    """
    Update the status of an asset.
    
    Args:
        asset: The asset to update
        status: New status (approved/rejected)
    
    Returns:
        Updated asset
    """
    asset.status = status
    return asset


def approve_asset(asset: Asset) -> Asset:
    """Mark an asset as approved for inclusion in the book."""
    return set_asset_status(asset, AssetStatus.APPROVED)


def reject_asset(asset: Asset) -> Asset:
    """Mark an asset as rejected (excluded from the book)."""
    return set_asset_status(asset, AssetStatus.REJECTED)


def filter_approved(assets: List[Asset]) -> List[Asset]:
    """Filter to only approved assets."""
    return [a for a in assets if a.status == AssetStatus.APPROVED]


def filter_by_status(assets: List[Asset], status: AssetStatus) -> List[Asset]:
    """Filter assets by status."""
    return [a for a in assets if a.status == status]


def get_curation_stats(assets: List[Asset]) -> dict:
    """
    Get statistics about asset curation status.
    
    Returns:
        Dict with counts for each status
    """
    stats = {
        "total": len(assets),
        "imported": 0,
        "approved": 0,
        "rejected": 0,
    }
    for asset in assets:
        stats[asset.status.value] += 1
    return stats


# ============================================
# Future: Advanced curation hooks
# ============================================

def detect_blurry(asset: Asset) -> float:
    """
    Placeholder for blur detection.
    
    Returns:
        Blur score (0 = sharp, 1 = very blurry)
    """
    # TODO: Implement using OpenCV Laplacian variance
    return 0.0


def find_duplicates(assets: List[Asset]) -> List[List[str]]:
    """
    Placeholder for duplicate detection.
    
    Returns:
        List of groups, each group is a list of similar asset IDs
    """
    # TODO: Implement using perceptual hashing
    return []


def auto_curate(assets: List[Asset], 
                reject_blurry: bool = True,
                blur_threshold: float = 0.7) -> List[Asset]:
    """
    Placeholder for automatic curation.
    
    This would:
    1. Reject blurry images
    2. Flag duplicates
    3. Auto-approve clear, unique images
    """
    # TODO: Implement
    return assets
