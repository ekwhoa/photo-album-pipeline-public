"""
Lightweight duplicate photo detection heuristics.

This module provides a simple, explainable duplicate detector using a
small perceptual hash (average hash / aHash) and Hamming distance. It is
designed to be fast for a few hundred photos and is intended for
debugging/inspection only — no automatic hiding or writes are performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional, Tuple
from pathlib import Path
import logging
from datetime import datetime, timedelta

try:
    import numpy as np  # type: ignore
except Exception:
    np = None  # type: ignore

from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


@dataclass
class DuplicateGroup:
    photo_ids: List[str]
    representative_id: str
    scores: Dict[str, float]
    # meta_filter_passed is internal-only and not required by the public API
    meta_filter_passed: Optional[bool] = None


def _ahash_array(img: Image.Image, size: int = 16):
    """Compute a simple average hash as a flattened boolean array.

    Args:
        img: PIL Image
        size: hash dimension (size x size)
    Returns:
        tuple(bitarray as list[int], total_bits)
    """
    img = ImageOps.exif_transpose(img)
    img = img.convert("L")
    img = img.resize((size, size), resample=Image.Resampling.BILINEAR)
    if np is not None:
        arr = np.array(img).astype(float)
        mean = arr.mean()
        bits = (arr > mean).astype(int).reshape(-1)
        return bits.tolist(), size * size
    else:
        pix = list(img.getdata())
        mean = sum(pix) / max(1, len(pix))
        bits = [1 if p > mean else 0 for p in pix]
        return bits, size * size


def _hamming_bits(a: List[int], b: List[int]) -> int:
    # assume equal length
    return sum(1 for x, y in zip(a, b) if x != y)


def find_duplicate_photos(
    book,
    storage,
    max_groups: int = 50,
    hash_size: int = 16,
    hamm_threshold: int = 24,
    true_duplicate_sim: float = 0.92,
    maybe_duplicate_sim_low: float = 0.90,
):
    """
    Find duplicate photo groups for a book using a simple average-hash and
    Hamming distance. Returns a list of DuplicateGroup, groups with at
    least two photos.

    This is intentionally O(N^2) for small N (200-500) and runs on-demand.
    """
    from repositories import AssetsRepository
    from db import SessionLocal

    repo = AssetsRepository()
    results: List[DuplicateGroup] = []

    with SessionLocal() as session:
        assets = repo.list_assets(session, book.id, status=None)

    # Build list of items with metadata for filtering
    items: List[Tuple[str, str, str, Optional[str], Optional[int], Optional[int], Optional[str], Optional[datetime]]] = []
    for a in assets:
        if not a.file_path:
            continue
        abs_path = storage.get_absolute_path(a.file_path)
        md = a.metadata
        taken_at = None
        try:
            taken_at = md.taken_at if getattr(md, 'taken_at', None) else None
        except Exception:
            taken_at = None

        items.append((a.id, abs_path, a.file_path, a.thumbnail_path, md.width, md.height, md.orientation, taken_at))

    n = len(items)
    if n < 2:
        return []

    # Compute hashes
    hashes = []  # list of (id, bits)
    # also keep metadata lookup by id
    meta_by_id: Dict[str, Tuple[Optional[int], Optional[int], Optional[str], Optional[datetime], str]] = {}
    for aid, abs_path, rel_path, thumb, width, height, orientation, taken_at in items:
        try:
            with Image.open(abs_path) as img:
                bits, total = _ahash_array(img, size=hash_size)
                hashes.append((aid, bits))
                meta_by_id[aid] = (width, height, orientation, taken_at, rel_path)
        except Exception:
            logger.exception("Failed to hash image %s", abs_path)

    # Representative-based grouping with metadata filtering and strict thresholds.
    id_list = [aid for aid, _ in hashes]
    bits_by_id = {aid: bits for aid, bits in hashes}
    max_bits = hash_size * hash_size

    # helper: metadata checks
    def meta_pass(aid1: str, aid2: str) -> bool:
        w1, h1, o1, t1, _ = meta_by_id.get(aid1, (None, None, None, None, None))
        w2, h2, o2, t2, _ = meta_by_id.get(aid2, (None, None, None, None, None))

        # Require orientation match if both present
        if o1 and o2 and o1 != o2:
            return False

        # Require width/height within 10% if both present
        if w1 is None or h1 is None or w2 is None or h2 is None:
            return False
        try:
            if abs(w1 - w2) / max(1, max(w1, w2)) > 0.10:
                return False
            if abs(h1 - h2) / max(1, max(h1, h2)) > 0.10:
                return False
        except Exception:
            return False

        # If both have timestamps, require within ±10 minutes
        if t1 and t2:
            try:
                delta = abs((t1 - t2).total_seconds())
                if delta > 10 * 60:
                    return False
            except Exception:
                return False

        return True

    unassigned = set(id_list)
    groups: List[DuplicateGroup] = []

    for rep in id_list:
        if rep not in unassigned:
            continue

        rep_bits = bits_by_id.get(rep)
        if rep_bits is None:
            continue

        confirmed: List[str] = [rep]
        scores: Dict[str, float] = {rep: 1.0}
        maybe: List[str] = []

        for other in id_list:
            if other == rep:
                continue
            if other not in unassigned:
                continue

            # Only consider if metadata checks pass (or at least sizes/orientation present)
            if not meta_pass(rep, other):
                continue

            bits_o = bits_by_id.get(other)
            if bits_o is None:
                continue
            try:
                dist = _hamming_bits(rep_bits, bits_o)
                sim = 1.0 - (dist / float(max_bits))
            except Exception:
                continue

            # classify by thresholds
            if sim >= true_duplicate_sim:
                confirmed.append(other)
                scores[other] = float(sim)
            elif sim >= maybe_duplicate_sim_low:
                maybe.append(other)
                scores[other] = float(sim)

        # Only form a group if confirmed has at least two members
        if len(confirmed) >= 2:
            # mark assigned: all confirmed included in group
            for a in confirmed:
                if a in unassigned:
                    unassigned.remove(a)

            # sort confirmed by similarity desc (rep first)
            confirmed_sorted = sorted(confirmed, key=lambda x: -scores.get(x, 0.0))
            groups.append(DuplicateGroup(photo_ids=confirmed_sorted, representative_id=rep, scores=scores, meta_filter_passed=True))

    # Sort groups by size desc, then by representative id as tiebreaker
    groups.sort(key=lambda g: (-len(g.photo_ids), g.representative_id))

    return groups[:max_groups]
