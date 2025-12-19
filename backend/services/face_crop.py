"""
Face focus helper (improved).

This file contains a single public function `compute_safe_crop` which returns
either a crop rect and center percentages when faces are detected and a safe
crop can be computed, or `None` when no faces were found. It uses an SQLite
cache in `backend/data/face_crops.sqlite` and writes debug overlays only when
`DEBUG_FACE_CROPS=1`.
"""

from __future__ import annotations

import os
import sqlite3
import logging
import json
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime

try:
    from PIL import Image, ImageDraw
except Exception:
    Image = None
    ImageDraw = None

try:
    import mediapipe as mp
    _HAS_MEDIAPIPE = True
except Exception:
    _HAS_MEDIAPIPE = False

logger = logging.getLogger(__name__)

# Cache DB path under backend/data
_DB_PATH = Path(__file__).resolve().parents[1] / "data" / "face_crops.sqlite"
_DB_INITIALIZED = False


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


def _make_key_parts(path: Path, target_aspect: Optional[float], params: Dict[str, Any]) -> Tuple[str, int]:
    try:
        st = path.stat()
        mtime = int(st.st_mtime)
    except Exception:
        mtime = 0
    key_meta = json.dumps({"aspect": target_aspect, **params}, sort_keys=True)
    key = f"{str(path.resolve())}:{key_meta}"
    return key, mtime


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


def _detect_faces_mediapipe(img: Image.Image, min_confidence: float) -> List[Dict[str, Any]]:
    """Return list of detections with relative bbox and score (xmin,ymin,width,height,score)."""
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


def detect_faces(image_path: str, min_confidence: float) -> List[Dict[str, Any]]:
    """Return list of boxes in pixel coords: {l,t,r,b,score}."""
    if Image is None:
        return []
    try:
        img = Image.open(image_path)
        w, h = img.size
        rels = _detect_faces_mediapipe(img, min_confidence)
        boxes: List[Dict[str, Any]] = []
        for d in rels:
            xmin = d.get("xmin", 0.0)
            ymin = d.get("ymin", 0.0)
            width = d.get("width", 0.0)
            height = d.get("height", 0.0)
            score = d.get("score", 0.0) or 0.0
            l = int(max(0, xmin * w))
            t = int(max(0, ymin * h))
            r = int(min(w, (xmin + width) * w))
            b = int(min(h, (ymin + height) * h))
            boxes.append({"l": l, "t": t, "r": r, "b": b, "score": score})
        return boxes
    except Exception:
        logger.exception("detect_faces failed for %s", image_path)
        return []


def _iou(box1: Dict[str, int], box2: Dict[str, int]) -> float:
    l1, t1, r1, b1 = box1["l"], box1["t"], box1["r"], box1["b"]
    l2, t2, r2, b2 = box2["l"], box2["t"], box2["r"], box2["b"]
    ix1 = max(l1, l2)
    iy1 = max(t1, t2)
    ix2 = min(r1, r2)
    iy2 = min(b1, b2)
    iw = max(0, ix2 - ix1)
    ih = max(0, iy2 - iy1)
    inter = iw * ih
    area1 = max(0, (r1 - l1)) * max(0, (b1 - t1))
    area2 = max(0, (r2 - l2)) * max(0, (b2 - t2))
    union = area1 + area2 - inter
    if union <= 0:
        return 0.0
    return inter / union


def _merge_boxes(boxes: List[Dict[str, int]], iou_thresh: float = 0.5) -> List[Dict[str, int]]:
    merged: List[Dict[str, int]] = []
    for b in boxes:
        placed = False
        for m in merged:
            if _iou(b, m) > iou_thresh:
                m["l"] = min(m["l"], b["l"])
                m["t"] = min(m["t"], b["t"])
                m["r"] = max(m["r"], b["r"])
                m["b"] = max(m["b"], b["b"])
                placed = True
                break
        if not placed:
            merged.append({"l": b["l"], "t": b["t"], "r": b["r"], "b": b["b"], "score": b.get("score", 0.0)})
    return merged


def compute_crop_from_boxes(img_w: int, img_h: int, boxes: List[Dict[str, int]], *,
                            safe_margin_frac: float = 0.12, pad_x: float = 1.8, pad_y: float = 2.2) -> Tuple[int, int, int, int]:
    """Given image size and merged face boxes (pixel coords), compute a crop rect (l,t,r,b).

    Algorithm:
    - Compute union U over boxes.
    - Expand U by pad_x/pad_y (centered) to obtain desired region D.
    - Start C as D (clamped to image bounds).
    - Ensure U lies within inset(C, safe_margin_frac). If not, shift C; if shifting cannot satisfy, expand C.
    - Return clamped C.
    """
    if not boxes:
        return (0, 0, img_w, img_h)
    ul = min(b["l"] for b in boxes)
    ut = min(b["t"] for b in boxes)
    ur = max(b["r"] for b in boxes)
    ub = max(b["b"] for b in boxes)

    u_w = max(1, ur - ul)
    u_h = max(1, ub - ut)
    center_x = ul + u_w / 2.0
    center_y = ut + u_h / 2.0

    target_w = min(img_w, int(u_w * pad_x))
    target_h = min(img_h, int(u_h * pad_y))

    # start crop centered at union center
    c_w = target_w
    c_h = target_h
    c_left = int(max(0, min(img_w - c_w, center_x - c_w / 2)))
    c_top = int(max(0, min(img_h - c_h, center_y - c_h / 2)))
    c_right = int(min(img_w, c_left + c_w))
    c_bottom = int(min(img_h, c_top + c_h))

    def inset_rect(l, t, r, b, frac):
        w = r - l
        h = b - t
        il = l + int(w * frac)
        it = t + int(h * frac)
        ir = r - int(w * frac)
        ib = b - int(h * frac)
        return il, it, ir, ib

    il, it, ir, ib = inset_rect(c_left, c_top, c_right, c_bottom, safe_margin_frac)

    # If union isn't inside inset, shift
    shift_x = 0
    shift_y = 0
    if ul < il:
        shift_x = ul - il
    elif ur > ir:
        shift_x = ur - ir
    if ut < it:
        shift_y = ut - it
    elif ub > ib:
        shift_y = ub - ib

    if shift_x != 0 or shift_y != 0:
        new_left = int(max(0, min(img_w - c_w, c_left + shift_x)))
        new_top = int(max(0, min(img_h - c_h, c_top + shift_y)))
        c_left, c_top = new_left, new_top
        c_right = c_left + c_w
        c_bottom = c_top + c_h
        il, it, ir, ib = inset_rect(c_left, c_top, c_right, c_bottom, safe_margin_frac)

    # If still not contained, expand until satisfied (prefer expanding over clipping)
    expand_loop = 0
    while (ul < il or ur > ir or ut < it or ub > ib) and (c_w < img_w or c_h < img_h):
        grow_w = int(min(img_w - c_w, max(1, c_w * 0.05)))
        grow_h = int(min(img_h - c_h, max(1, c_h * 0.05)))
        c_w = min(img_w, c_w + grow_w)
        c_h = min(img_h, c_h + grow_h)
        c_left = int(max(0, min(img_w - c_w, center_x - c_w / 2)))
        c_top = int(max(0, min(img_h - c_h, center_y - c_h / 2)))
        c_right = c_left + c_w
        c_bottom = c_top + c_h
        il, it, ir, ib = inset_rect(c_left, c_top, c_right, c_bottom, safe_margin_frac)
        expand_loop += 1
        if expand_loop > 200:
            break

    # Final clamp
    c_left = int(max(0, c_left))
    c_top = int(max(0, c_top))
    c_right = int(min(img_w, c_right))
    c_bottom = int(min(img_h, c_bottom))

    return (c_left, c_top, c_right, c_bottom)


def compute_safe_crop(image_path: str, *, target_aspect: Optional[float] = None,
                      conf_high: float = 0.80, conf_low: float = 0.55,
                      min_area_frac: float = 0.004, edge_frac: float = 0.08, edge_min_area_frac: float = 0.002,
                      safe_margin_frac: float = 0.12, pad_x: float = 1.8, pad_y: float = 2.2) -> Optional[Dict[str, Any]]:
    """
    Compute a safe crop rect for the image or return None when no faces detected.

    Returns dict {crop: [l,t,r,b], center_x_pct, center_y_pct, box_area} or None.
    """
    if Image is None:
        return None
    src = Path(image_path)
    if not src.exists():
        return None

    params = {
        "conf_high": conf_high,
        "conf_low": conf_low,
        "min_area_frac": min_area_frac,
        "edge_frac": edge_frac,
        "edge_min_area_frac": edge_min_area_frac,
        "safe_margin_frac": safe_margin_frac,
        "pad_x": pad_x,
        "pad_y": pad_y,
    }
    key, mtime = _make_key_parts(src, target_aspect, params)
    cached = _query_cache(key)
    if cached is not None:
        if cached["found_faces"] and cached.get("meta", {}).get("crop"):
            meta = cached.get("meta", {})
            crop = meta.get("crop")
            return {"crop": crop, "center_x_pct": cached.get("center_x"), "center_y_pct": cached.get("center_y"), "box_area": cached.get("box_area")}
        return None

    try:
        img = Image.open(src)
        img_w, img_h = img.size

        # Pass A: strict
        boxes_a = detect_faces(str(src), conf_high)

        # Pass B: permissive but filtered
        raw_b = detect_faces(str(src), conf_low)
        boxes_b: List[Dict[str, int]] = []
        for b in raw_b:
            l, t, r, bt = b["l"], b["t"], b["r"], b["b"]
            area = max(0, (r - l)) * max(0, (bt - t))
            if area <= 0:
                continue
            area_frac = area / (img_w * img_h)
            if area_frac >= min_area_frac:
                boxes_b.append(b)
                continue
            near_edge = (l <= edge_frac * img_w) or (t <= edge_frac * img_h) or (r >= (1 - edge_frac) * img_w) or (bt >= (1 - edge_frac) * img_h)
            if near_edge and area_frac >= edge_min_area_frac:
                boxes_b.append(b)

        all_boxes = boxes_a + boxes_b
        merged = _merge_boxes(all_boxes, iou_thresh=0.5)

        if not merged:
            _write_cache(key, mtime, 0, None, None, None, {"count": 0})
            return None

        # Compute crop from merged boxes
        crop = compute_crop_from_boxes(img_w, img_h, merged, safe_margin_frac=safe_margin_frac, pad_x=pad_x, pad_y=pad_y)
        c_left, c_top, c_right, c_bottom = crop
        crop_w = max(1, c_right - c_left)
        crop_h = max(1, c_bottom - c_top)
        center_x_pct = (c_left + crop_w / 2.0) / img_w
        center_y_pct = (c_top + crop_h / 2.0) / img_h

        box_area_px = max(0, (max(b["r"] for b in merged) - min(b["l"] for b in merged))) * max(0, (max(b["b"] for b in merged) - min(b["t"] for b in merged)))
        box_area_ratio = box_area_px / (img_w * img_h if img_w * img_h > 0 else 1)

        meta = {"crop": [c_left, c_top, c_right, c_bottom], "count": len(merged)}
        _write_cache(key, mtime, 1, center_x_pct, center_y_pct, box_area_ratio, meta)

        # optional debug overlay
        try:
            if os.environ.get("DEBUG_FACE_CROPS") in ("1", "true", "True") and ImageDraw is not None:
                debug_dir = Path(__file__).resolve().parents[1] / "data" / "face_crops_debug"
                debug_dir.mkdir(parents=True, exist_ok=True)
                dbg_name = f"dbg_{src.stat().st_ino}_{hash(key) & 0xFFFF_FFFF:08x}.jpg"
                dbg_path = debug_dir / dbg_name
                try:
                    draw_img = img.convert("RGB")
                    d = ImageDraw.Draw(draw_img)
                    # draw merged boxes
                    for m in merged:
                        d.rectangle([m["l"], m["t"], m["r"], m["b"]], outline=(255, 165, 0), width=3)
                    # union
                    ul = min(m["l"] for m in merged)
                    ut = min(m["t"] for m in merged)
                    ur = max(m["r"] for m in merged)
                    ub = max(m["b"] for m in merged)
                    d.rectangle([ul, ut, ur, ub], outline=(255, 0, 0), width=3)
                    # crop
                    d.rectangle([c_left, c_top, c_right, c_bottom], outline=(0, 255, 0), width=4)
                    draw_img.save(dbg_path, format="JPEG", quality=85)
                    logger.info("face_crop: wrote debug overlay %s", dbg_path)
                except Exception:
                    logger.exception("face_crop: failed to write debug overlay")
        except Exception:
            logger.exception("face_crop: debug write error")

        return {"crop": [c_left, c_top, c_right, c_bottom], "center_x_pct": center_x_pct, "center_y_pct": center_y_pct, "box_area": box_area_ratio}
    except Exception:
        logger.exception("compute_safe_crop failed for %s", image_path)
        return None
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


    def detect_faces(image_path: str, min_confidence: float) -> list[Dict[str, Any]]:
        """
        Detect faces and return list of boxes in pixel coords: dicts with
        {l,t,r,b,score} where coords are integers in source image pixels.
        """
        if Image is None:
            return []
        try:
            img = Image.open(image_path)
            w, h = img.size
            rels = _detect_faces_mediapipe(img, min_confidence)
            boxes = []
            for d in rels:
                xmin = d.get("xmin", 0.0)
                ymin = d.get("ymin", 0.0)
                width = d.get("width", 0.0)
                height = d.get("height", 0.0)
                score = d.get("score", 0.0) or 0.0
                l = int(max(0, xmin * w))
                t = int(max(0, ymin * h))
                r = int(min(w, (xmin + width) * w))
                b = int(min(h, (ymin + height) * h))
                boxes.append({"l": l, "t": t, "r": r, "b": b, "score": score})
            return boxes
        except Exception:
            logger.exception("detect_faces failed for %s", image_path)
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
