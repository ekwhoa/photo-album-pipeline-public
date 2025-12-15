"""
Lightweight duplicate photo detection heuristics.

This module provides a simple, explainable duplicate detector using a
small perceptual hash (average hash / aHash) and Hamming distance. It is
designed to be fast for a few hundred photos and is intended for
debugging/inspection only — no automatic hiding or writes are performed.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path
import logging

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


def find_duplicate_photos(book, storage, max_groups: int = 50, hash_size: int = 16, hamm_threshold: int = 24):
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

    # Build list of (id, path)
    items = []
    for a in assets:
        if not a.file_path:
            continue
        abs_path = storage.get_absolute_path(a.file_path)
        items.append((a.id, abs_path, a.file_path, a.thumbnail_path))

    n = len(items)
    if n < 2:
        return []

    # Compute hashes
    hashes = []  # list of (id, bits)
    for aid, abs_path, rel_path, thumb in items:
        try:
            with Image.open(abs_path) as img:
                bits, total = _ahash_array(img, size=hash_size)
                hashes.append((aid, bits))
        except Exception:
            logger.exception("Failed to hash image %s", abs_path)

    # Pairwise compare and union-find to cluster
    parent = {aid: aid for aid, _ in hashes}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        rx = find(x)
        ry = find(y)
        if rx != ry:
            parent[ry] = rx

    for i in range(len(hashes)):
        ai, bi = hashes[i]
        for j in range(i + 1, len(hashes)):
            aj, bj = hashes[j]
            try:
                dist = _hamming_bits(bi, bj)
                if dist <= hamm_threshold:
                    union(ai, aj)
            except Exception:
                continue

    clusters = {}
    for aid, _ in hashes:
        root = find(aid)
        clusters.setdefault(root, []).append(aid)

    # Build DuplicateGroup list
    groups: List[DuplicateGroup] = []
    for root, members in clusters.items():
        if len(members) < 2:
            continue
        # Representative = first
        rep = members[0]
        # Compute per-photo similarity scores relative to rep
        rep_bits = None
        for aid, bits in hashes:
            if aid == rep:
                rep_bits = bits
                break
        scores = {}
        if rep_bits is not None:
            max_bits = hash_size * hash_size
            for m in members:
                bits_m = next((b for aid2, b in hashes if aid2 == m), None)
                if bits_m is None:
                    continue
                dist = _hamming_bits(rep_bits, bits_m)
                sim = 1.0 - (dist / float(max_bits))
                scores[m] = float(sim)
        groups.append(DuplicateGroup(photo_ids=members, representative_id=rep, scores=scores))

    # Sort groups by size desc, then by rep id
    groups.sort(key=lambda g: (-len(g.photo_ids), g.representative_id))

    return groups[:max_groups]
