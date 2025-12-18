"""
Face focus helper.

This module performs lightweight face detection (MediaPipe when available)
and returns a small focus descriptor suitable for guiding PDF layout. By
default it will NOT write any debug crops to disk. Detection results are
cached in an SQLite database under `backend/data/face_crops.sqlite` to make
repeat renders fast. If the env var `DEBUG_FACE_CROPS=1` is set, debug images
may be written under `backend/data/face_crops_debug/` (also ignored by git).

Public function:
  compute_face_focus(image_path, min_confidence=0.8, min_box_area_ratio=0.005)
    -> dict with center_x_pct, center_y_pct, box_area_ratio or None

The function returns None when no sufficiently-large / confident faces are
detected so callers can fall back to existing center-crop behavior.
"""

import os
import sqlite3
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, Tuple
from datetime import datetime
import os

try:
    from PIL import Image
except Exception:
    Image = None

try:
    import mediapipe as mp
    _HAS_MEDIAPIPE = True
except Exception:
    _HAS_MEDIAPIPE = False

_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "face_crops.sqlite"
_DB_INITIALIZED = False
_COUNTER = {
    "calls": 0,
    "hits": 0,
    "faces": 0,
    "no_faces": 0,
}
_LOG_EVERY = 100
logger = logging.getLogger(__name__)


def _ensure_db():
    global _DB_INITIALIZED
    if _DB_INITIALIZED:
        return
    db_dir = _DB_PATH.parent
    db_dir.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS face_cache (
                key TEXT PRIMARY KEY,
                mtime INTEGER,
                found_faces INTEGER,
                center_x REAL,
                center_y REAL,
                box_area REAL,
                meta TEXT,
                created_at TEXT
            )
            """
        )
        conn.commit()
    finally:
        conn.close()
    _DB_INITIALIZED = True


def _make_key(path: Path, aspect: float, margin: float) -> Tuple[str, int]:
    try:
        st = path.stat()
        mtime = int(st.st_mtime)
    except Exception:
        mtime = 0
    key = f"{str(path.resolve())}:{aspect:.6f}:{margin:.3f}"
    return (key, mtime)


def _query_cache(key: str) -> Optional[Dict[str, Any]]:
    _ensure_db()
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute("SELECT found_faces, center_x, center_y, box_area, meta FROM face_cache WHERE key=?", (key,))
        row = cur.fetchone()
        if not row:
            return None
        found_faces, cx, cy, box_area, meta = row
        return {"found_faces": found_faces, "center_x": cx, "center_y": cy, "box_area": box_area, "meta": json.loads(meta) if meta else {}}
    finally:
        conn.close()


def _write_cache(key: str, mtime: int, found_faces: int, center_x: Optional[float], center_y: Optional[float], box_area: Optional[float], meta: Optional[Dict[str, Any]] = None):
    _ensure_db()
    conn = sqlite3.connect(str(_DB_PATH))
    try:
        cur = conn.cursor()
        cur.execute(
            "REPLACE INTO face_cache (key, mtime, found_faces, center_x, center_y, box_area, meta, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (key, mtime, found_faces, center_x, center_y, box_area, json.dumps(meta or {}), datetime.utcnow().isoformat()),
        )
        conn.commit()
    finally:
        conn.close()


def _detect_faces_mediapipe(img: Image.Image, min_confidence: float) -> list[Dict[str, Any]]:
    """Return list of detections with relative bbox and score."""
    if not _HAS_MEDIAPIPE:
        return []
    try:
        mp_face = mp.solutions.face_detection
        with mp_face.FaceDetection(model_selection=0, min_detection_confidence=min_confidence) as detector:
            import numpy as np

            arr = np.array(img.convert("RGB"))
            results = detector.process(arr)
            detections = []
            if results.detections:
                for det in results.detections:
                    rbox = det.location_data.relative_bounding_box
                    score = 0.0
                    try:
                        # MediaPipe exposes detection_score in different places; be defensive
                        score = float(det.score[0]) if getattr(det, "score", None) else 0.0
                    except Exception:
                        score = 0.0
                    detections.append({
                        "xmin": max(0.0, rbox.xmin),
                        "ymin": max(0.0, rbox.ymin),
                        "width": max(0.0, rbox.width),
                        "height": max(0.0, rbox.height),
                        "score": score,
                    })
            return detections
    except Exception:
        logger.exception("mediapipe face detection failed")
        return []


def compute_face_focus(image_path: str, *, min_confidence: float = 0.8, min_box_area_ratio: float = 0.005, margin: float = 0.25) -> Optional[Dict[str, Any]]:
    """
    Compute a focus descriptor for the primary face(s) in the image.

    Returns a dict: {center_x_pct, center_y_pct, box_area_ratio} or None when
    no faces pass thresholds. Results are cached in `backend/data/face_crops.sqlite`.
    """
    global _COUNTER
    _COUNTER["calls"] += 1

    src = Path(image_path)
    if not src.exists() or Image is None:
        _COUNTER["no_faces"] += 1
        if _COUNTER["calls"] % _LOG_EVERY == 0:
            logger.info("face_crop: calls=%s hits=%s faces=%s no_faces=%s", _COUNTER["calls"], _COUNTER["hits"], _COUNTER["faces"], _COUNTER["no_faces"])
        return None

    # derive an aspect key so different aspect requests are cached separately
    aspect = 0.0
    try:
        aspect = 1.0  # caller may pass aspect in future; keep stable key behaviour
    except Exception:
        aspect = 1.0
    key, mtime = _make_key(src, aspect, margin)
    cached = _query_cache(key)
    if cached is not None:
        _COUNTER["hits"] += 1
        if cached["found_faces"] and cached["center_x"] is not None:
            _COUNTER["faces"] += 1
            if _COUNTER["calls"] % _LOG_EVERY == 0:
                logger.info("face_crop: cache hit face for %s", src)
            return {"center_x_pct": cached["center_x"], "center_y_pct": cached["center_y"], "box_area": cached["box_area"]}
        else:
            _COUNTER["no_faces"] += 1
            if _COUNTER["calls"] % _LOG_EVERY == 0:
                logger.info("face_crop: cache hit no-face for %s", src)
            return None

    # Not cached; run detection if available
    try:
        img = Image.open(src)
        img_w, img_h = img.size
        detections = _detect_faces_mediapipe(img, min_confidence)
        # Filter by score and minimum box area
        filtered = []
        for d in detections:
            score = d.get("score", 0.0) or 0.0
            area = (d.get("width", 0.0) * d.get("height", 0.0))
            if score < min_confidence:
                continue
            if area < min_box_area_ratio:
                continue
            filtered.append(d)

        if not filtered:
            _write_cache(key, mtime, 0, None, None, None, {"count": 0})
            _COUNTER["no_faces"] += 1
            if _COUNTER["calls"] % _LOG_EVERY == 0:
                logger.info("face_crop: calls=%s hits=%s faces=%s no_faces=%s", _COUNTER["calls"], _COUNTER["hits"], _COUNTER["faces"], _COUNTER["no_faces"])
            return None

        # Combine multiple faces into union box
        xmin = min(d["xmin"] for d in filtered)
        ymin = min(d["ymin"] for d in filtered)
        xmax = max(d["xmin"] + d["width"] for d in filtered)
        ymax = max(d["ymin"] + d["height"] for d in filtered)
        # convert relative to pixel coords
        px_l = int(xmin * img_w)
        px_t = int(ymin * img_h)
        px_r = int(xmax * img_w)
        px_b = int(ymax * img_h)
        box_area_px = max(0, (px_r - px_l)) * max(0, (px_b - px_t))
        img_area = img_w * img_h if img_w * img_h > 0 else 1
        box_area_ratio = box_area_px / img_area

        # center in pixel coords
        center_x = (px_l + px_r) / 2.0
        center_y = (px_t + px_b) / 2.0
        center_x_pct = max(0.0, min(1.0, center_x / img_w))
        center_y_pct = max(0.0, min(1.0, center_y / img_h))

        _write_cache(key, mtime, 1, center_x_pct, center_y_pct, box_area_ratio, {"count": len(filtered)})
        _COUNTER["faces"] += 1
        if _COUNTER["calls"] % _LOG_EVERY == 0:
            logger.info("face_crop: calls=%s hits=%s faces=%s no_faces=%s", _COUNTER["calls"], _COUNTER["hits"], _COUNTER["faces"], _COUNTER["no_faces"])

        # Optionally write a debug image showing the crop if env var set
        try:
            if os.environ.get("DEBUG_FACE_CROPS") in ("1", "true", "True"):
                debug_dir = Path(__file__).resolve().parents[1] / "data" / "face_crops_debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                dbg_name = f"dbg_{src.stat().st_ino}_{_make_key(src, aspect, margin)[0][:8]}.jpg"
                dbg_path = debug_dir / dbg_name
                try:
                    # draw a small marker at the center
                    draw = img.convert("RGB")
                    from PIL import ImageDraw

                    d = ImageDraw.Draw(draw)
                    cx = int(center_x)
                    cy = int(center_y)
                    r = max(3, int(min(img_w, img_h) * 0.01))
                    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=(255, 0, 0))
                    draw.save(dbg_path, format="JPEG", quality=85)
                    logger.info("face_crop: wrote debug crop %s", dbg_path)
                except Exception:
                    logger.exception("face_crop: failed to write debug image")
        except Exception:
            logger.exception("face_crop: debug write error")

        return {"center_x_pct": center_x_pct, "center_y_pct": center_y_pct, "box_area": box_area_ratio}
    except Exception:
        logger.exception("face_crop: detection failed for %s", image_path)
        _COUNTER["no_faces"] += 1
        return None
