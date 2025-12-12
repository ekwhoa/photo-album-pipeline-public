"""
Lightweight photo quality diagnostics.

This module provides a small, classical set of heuristics to score image
quality without heavy ML dependencies. It's intended for debugging only —
no automatic changes are made to books or assets.

Quality score interpretation:
- `quality_score` is a heuristic in the range ~0.0..1.0 where 0 is good and
  values closer to 1.0 indicate worse quality (higher = worse). It's a
  weighted combination of blur, brightness deviation, low contrast and low
  edge density. The specific thresholds are declared at module top and are
  intentionally conservative and easy to tweak.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional
import logging

try:
    import numpy as np  # type: ignore
except Exception:
    np = None  # type: ignore

from PIL import Image, ImageFilter

logger = logging.getLogger(__name__)

# --- Tunable thresholds (simple heuristics) ---
MAX_DIM = 512

# Laplacian variance thresholds (higher = sharper). Values are approximate
# for downscaled grayscale images; adjust if you change downscale size.
BLUR_VERY_BLURRY_THRESHOLD = 100.0
BLUR_BLURRY_THRESHOLD = 300.0

# Brightness: 0..255
BRIGHTNESS_DARK_THRESHOLD = 40.0
BRIGHTNESS_BRIGHT_THRESHOLD = 220.0

# Contrast (stddev) threshold
CONTRAST_LOW_THRESHOLD = 20.0

# Edge density threshold (fraction of pixels considered edges)
EDGE_LOW_THRESHOLD = 0.02


@dataclass
class PhotoQualityMetrics:
    photo_id: str
    blur_score: float
    brightness: float
    contrast: float
    edge_density: float
    quality_score: float
    face_count: Optional[int]
    flags: List[str]


def _downscale_and_grayscale(image: Image.Image) -> Image.Image:
    img = image.convert("L")
    img.thumbnail((MAX_DIM, MAX_DIM))
    return img


def _variance_of_laplacian_with_numpy(arr: "np.ndarray") -> float:
    # arr is 2D grayscale uint8
    # Compute 3x3 laplacian via slicing (fast and no scipy dependency)
    try:
        a = arr.astype(float)
        center = a[1:-1, 1:-1]
        up = a[:-2, 1:-1]
        down = a[2:, 1:-1]
        left = a[1:-1, :-2]
        right = a[1:-1, 2:]
        lap = up + down + left + right - 4.0 * center
        return float(lap.var())
    except Exception:
        return 0.0


def analyze_photo(image_path: Path, photo_id: Optional[str] = None) -> PhotoQualityMetrics:
    """
    Analyze a single image file and return heuristic quality metrics.

    Returns a PhotoQualityMetrics with `face_count=None` (placeholder).
    Any error reading or decoding the image returns a very-bad-quality result
    with `flags=['missing_or_unreadable']`.
    """
    pid = str(photo_id) if photo_id is not None else (str(image_path.name) if image_path else "-")
    try:
        with Image.open(image_path) as img:
            img = img.convert("RGB")
            # Respect EXIF orientation
            # PIL.ImageOps.exif_transpose may be used elsewhere; here we keep it simple
            gray = _downscale_and_grayscale(img)

            # Pixel array
            try:
                if np is not None:
                    arr = np.array(gray)
                    blur_score = _variance_of_laplacian_with_numpy(arr)
                    # Sobel-like gradients for edge density
                    gx = arr[1:-1, 2:] - arr[1:-1, :-2]
                    gy = arr[2:, 1:-1] - arr[:-2, 1:-1]
                    mag = (gx.astype(float) ** 2 + gy.astype(float) ** 2) ** 0.5
                    edge_pixels = (mag > 40).sum()  # threshold on gradient magnitude
                    edge_density = float(edge_pixels) / float(mag.size)
                else:
                    raise RuntimeError("numpy unavailable")
            except Exception:
                # Fallback to PIL-based edge proxy
                edges = gray.filter(ImageFilter.FIND_EDGES)
                arr_e = list(edges.getdata())
                # compute variance of edge response as a proxy for laplacian variance
                mean_e = sum(arr_e) / max(1, len(arr_e))
                var_e = sum((p - mean_e) ** 2 for p in arr_e) / max(1, len(arr_e))
                blur_score = float(var_e)
                # edge density: fraction above threshold
                edge_threshold = 30
                edge_density = float(sum(1 for p in arr_e if p > edge_threshold)) / float(len(arr_e))

            # Basic brightness/contrast
            pix = list(gray.getdata())
            brightness = float(sum(pix) / max(1, len(pix)))
            # Use population stddev for contrast
            mean = brightness
            variance = sum((p - mean) ** 2 for p in pix) / max(1, len(pix))
            contrast = float(variance ** 0.5)

            # Compute a composite quality score (0 = good, 1 = bad)
            # Normalize components into 0..1 'badness' measures
            blur_bad = max(0.0, (BLUR_VERY_BLURRY_THRESHOLD - blur_score) / max(1.0, BLUR_VERY_BLURRY_THRESHOLD))
            bright_bad = min(1.0, abs(brightness - 127.0) / 127.0)
            contrast_bad = max(0.0, (CONTRAST_LOW_THRESHOLD - contrast) / max(1.0, CONTRAST_LOW_THRESHOLD))
            edge_bad = max(0.0, (EDGE_LOW_THRESHOLD - edge_density) / max(1e-6, EDGE_LOW_THRESHOLD))

            # Weighted sum (higher => worse)
            quality_score = (
                0.45 * blur_bad + 0.2 * bright_bad + 0.2 * contrast_bad + 0.15 * edge_bad
            )

            flags: List[str] = []
            if blur_score < BLUR_VERY_BLURRY_THRESHOLD:
                flags.append("very_blurry")
            elif blur_score < BLUR_BLURRY_THRESHOLD:
                flags.append("blurry")

            if brightness < BRIGHTNESS_DARK_THRESHOLD:
                flags.append("very_dark")
            if brightness > BRIGHTNESS_BRIGHT_THRESHOLD:
                flags.append("very_bright")

            if contrast < CONTRAST_LOW_THRESHOLD:
                flags.append("low_contrast")

            if edge_density < EDGE_LOW_THRESHOLD:
                flags.append("low_edge_density")

            return PhotoQualityMetrics(
                photo_id=pid,
                blur_score=float(blur_score),
                brightness=float(brightness),
                contrast=float(contrast),
                edge_density=float(edge_density),
                quality_score=float(min(max(quality_score, 0.0), 1.0)),
                face_count=None,
                flags=flags,
            )
    except Exception as e:
        logger.exception("Failed to analyze image %s: %s", image_path, e)
        return PhotoQualityMetrics(
            photo_id=pid,
            blur_score=0.0,
            brightness=0.0,
            contrast=0.0,
            edge_density=0.0,
            quality_score=1.0,
            face_count=None,
            flags=["missing_or_unreadable"],
        )


def analyze_book_photos(book, storage) -> List[PhotoQualityMetrics]:
    """
    Analyze all photos for a book and return list of metrics.

    This function is intentionally read-only and does not cache or write results.
    """
    from repositories import AssetsRepository
    from services.curation import filter_approved
    from db import SessionLocal

    repo = AssetsRepository()
    results: List[PhotoQualityMetrics] = []
    with SessionLocal() as session:
        assets = repo.list_assets(session, book.id, status=None)
        # Prefer approved assets (same set used by planner); include all if none
        assets = filter_approved(assets)
        for a in assets:
            try:
                rel = a.file_path
                abs_path = storage.get_absolute_path(rel)
                metrics = analyze_photo(abs_path, photo_id=a.id)
                results.append(metrics)
            except Exception:
                results.append(PhotoQualityMetrics(photo_id=a.id, blur_score=0.0, brightness=0.0, contrast=0.0, edge_density=0.0, quality_score=1.0, face_count=None, flags=["missing_or_unreadable"]))
    return results
