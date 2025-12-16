from __future__ import annotations

from typing import List, Dict, Any, Optional
from datetime import datetime
import logging

from services.photo_quality import analyze_book_photos, PhotoQualityMetrics
from services.duplicate_photos import find_duplicate_photos, DuplicateGroup

logger = logging.getLogger(__name__)

# Tunable constants
MAX_LIKELY_REJECTS_DEFAULT = 50
MAX_DUPLICATE_GROUPS_DEFAULT = 25
SEVERE_FLAGS = {"very_dark", "very_blurry", "blurry", "very_low_edge_density", "low_contrast"}


def _choose_best_in_group(members: List[str], metrics_by_id: Dict[str, PhotoQualityMetrics], meta_by_id: Dict[str, Any], representative: Optional[str] = None) -> str:
    """Choose the best photo to keep among members.

    Lower quality_score is better (0 best, 1 worst).
    Tie-breakers: higher resolution (width*height), fewer severe flags, then representative if present.
    """
    def score_key(pid: str):
        m = metrics_by_id.get(pid)
        quality = m.quality_score if m is not None else 1.0
        md = meta_by_id.get(pid) or {}
        width = md.get("width") or 0
        height = md.get("height") or 0
        resolution = (width or 0) * (height or 0)
        flags = set((m.flags or [])) if m else set()
        severe_count = len(flags & SEVERE_FLAGS)
        # sort: primary lower quality, then higher resolution, then fewer severe flags
        return (quality, -resolution, severe_count)

    # pick minimal by key
    best = min(members, key=score_key)
    # if we have representative and it's close, prefer it as tiebreaker if equal key
    return best


def compute_curation_suggestions(book, storage, max_likely_rejects: int = MAX_LIKELY_REJECTS_DEFAULT, max_duplicate_groups: int = MAX_DUPLICATE_GROUPS_DEFAULT) -> Dict[str, Any]:
    """Compute curation suggestions combining quality metrics and duplicate groups.

    Returns a serializable dict suitable for API responses.
    """
    # Compute quality metrics
    quality_list = analyze_book_photos(book, storage)
    metrics_by_id: Dict[str, PhotoQualityMetrics] = {m.photo_id: m for m in quality_list}

    # Build metadata lookup via assets repository indirectly by reading metrics' file paths
    # metrics don't include width/height; but assets' metadata available to API route which calls this.
    # For portability, we include a simple empty meta map here; route can augment if needed.
    meta_by_id: Dict[str, Dict[str, Any]] = {}

    # Duplicate groups
    dup_groups = find_duplicate_photos(book, storage, max_groups=max_duplicate_groups)

    # Build duplicate suggestions
    duplicate_suggestions = []
    duplicate_reject_ids = set()
    for g in dup_groups:
        members = list(g.photo_ids or [])
        if len(members) < 2:
            continue
        keep = _choose_best_in_group(members, metrics_by_id, meta_by_id, representative=g.representative_id)
        reject_ids = [mid for mid in members if mid != keep]
        for rid in reject_ids:
            duplicate_reject_ids.add(rid)

        # prepare member info
        members_info = []
        for mid in members:
            m = metrics_by_id.get(mid)
            members_info.append({
                "photo_id": mid,
                "similarity": float(g.scores.get(mid, 0.0)) if g.scores else 0.0,
                "quality_score": float(m.quality_score) if m else None,
                "flags": list(m.flags) if m and m.flags else [],
            })

        duplicate_suggestions.append({
            "representative_id": g.representative_id,
            "keep_photo_id": keep,
            "reject_photo_ids": reject_ids,
            "members": members_info,
            "reasons": [f"Near-duplicates (sim threshold). Keeping best by quality/resolution."],
        })

    # Likely rejects: select photos with severe flags or poor quality, excluding ones in duplicate_reject_ids
    likely_rejects = []
    for m in sorted(quality_list, key=lambda x: x.quality_score, reverse=True):
        if m.photo_id in duplicate_reject_ids:
            continue
        # determine reasons
        reasons = []
        flags = set(m.flags or [])
        if flags & SEVERE_FLAGS:
            reasons.append("Severe quality flags: " + ", ".join(sorted(flags & SEVERE_FLAGS)))
        # combinations
        if "blurry" in flags and "low_contrast" in flags:
            reasons.append("Blurry with low contrast")
        if "very_low_edge_density" in flags:
            reasons.append("Very low edge density")

        if not reasons:
            # skip non-severe
            continue

        likely_rejects.append({
            "photo_id": m.photo_id,
            "thumbnail_url": None,
            "file_path": getattr(m, "file_path", None),
            "quality_score": float(m.quality_score),
            "flags": list(m.flags or []),
            "reasons": reasons,
            "current_status": None,
        })
        if len(likely_rejects) >= max_likely_rejects:
            break

    result = {
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "params": {"max_likely_rejects": max_likely_rejects, "max_duplicate_groups": max_duplicate_groups},
        "likely_rejects": likely_rejects,
        "duplicate_groups": duplicate_suggestions,
    }

    return result
