"""Render just the postcard cover for a given book id.

Usage:
    python -m backend.scripts.render_postcard_cover_only --book-id <id> [--style enhanced|classic] [--max-letters 8] [--seed 123]

This avoids the full book render and is useful for quickly checking postcard letter-image halos.
Outputs land in media/books/<book_id>/exports/assets (fingerprinted). When PHOTOBOOK_DEBUG_ARTIFACTS=1,
debug layers are written under .../assets/debug/cover_only_<fingerprint>/.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import random
import sys
from pathlib import Path
from typing import List

import logging
from PIL import Image

from backend.services.cover_postcard import (
    CoverPostcardSpec,
    generate_composited_cover,
    generate_postcard_cover,
)
from backend.vendor.postcard_renderer import engine as postcard_engine

logger = logging.getLogger("render_postcard_cover_only")


def _collect_letter_images(letter_dir: Path, max_letters: int, seed: int) -> List[Image.Image]:
    imgs: List[Image.Image] = []
    if not letter_dir.exists():
        return imgs
    files = sorted([p for p in letter_dir.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png"}])
    if not files:
        return imgs
    rng = random.Random(seed)
    files = files[:]
    rng.shuffle(files)
    for p in files[:max_letters]:
        try:
            imgs.append(Image.open(p).convert("RGBA"))
        except Exception:
            continue
    return imgs


def main() -> int:
    if not logger.handlers:
        logging.basicConfig(level=logging.INFO, format="%(message)s")
    parser = argparse.ArgumentParser(description="Render only the postcard cover for a book id.")
    parser.add_argument("--book-id", required=True, help="Book id to use for output scoping.")
    parser.add_argument("--title", default=None, help="Override title text (defaults to book id).")
    parser.add_argument("--top-text", default="Greetings from")
    parser.add_argument("--bottom-text", default="")
    parser.add_argument("--media-root", default=str(Path(__file__).resolve().parents[1] / "media"))
    parser.add_argument("--style", choices=["classic", "enhanced"], default="enhanced")
    parser.add_argument("--letter-dir", default=None, help="Directory of letter images; defaults to book photos dir.")
    parser.add_argument("--letter-mode", action="store_true", help="Force per-letter image mode (fail if none found unless --allow-scenery-fallback is set).")
    parser.add_argument("--allow-scenery-fallback", action="store_true", help="If set, when --letter-mode is requested but no images found, fall back to scenery fill instead of erroring.")
    parser.add_argument("--compare-scenery", action="store_true", help="Render a scenery postcard alongside letter-mode and save side-by-side + crop in debug dir.")
    parser.add_argument("--max-letters", type=int, default=8)
    parser.add_argument("--seed", type=int, default=123)
    parser.add_argument("--force", action="store_true", help="Force regeneration even if cached.")
    args = parser.parse_args()

    media_root = Path(args.media_root).resolve()
    book_id = args.book_id
    book_dir = media_root / "books" / book_id
    photos_dir = Path(args.letter_dir).resolve() if args.letter_dir else book_dir / "photos"
    assets_dir = book_dir / "exports" / "assets"
    assets_dir.mkdir(parents=True, exist_ok=True)

    title = args.title or book_id
    letters = _collect_letter_images(photos_dir, max_letters=args.max_letters, seed=args.seed)
    use_letter_mode = args.letter_mode or len(letters) > 0
    if args.letter_mode and not letters and not args.allow_scenery_fallback:
        raise SystemExit(f"--letter-mode requested but no letter images found in {photos_dir}")

    fingerprint_payload = {
        "book_id": book_id,
        "title": title,
        "top_text": args.top_text,
        "bottom_text": args.bottom_text,
        "style": args.style,
        "letter_mode": use_letter_mode,
        "letter_count": len(letters),
        "letters": [getattr(getattr(img, "filename", ""), "name", getattr(img, "filename", "")) for img in letters],
        "seed": args.seed,
        "max_letters": args.max_letters,
    }
    fingerprint = hashlib.sha256(str(fingerprint_payload).encode("utf-8")).hexdigest()
    fname_stub = fingerprint[:12]

    debug_enabled = os.getenv("PHOTOBOOK_DEBUG_ARTIFACTS", "0") == "1"
    debug_dir = assets_dir / "debug" / f"cover_only_{fname_stub}" if debug_enabled else None
    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)

    postcard_path = assets_dir / f"cover_postcard_{fname_stub}.png"
    composite_path = assets_dir / f"cover_front_composite_{fname_stub}.png"

    if args.force or not postcard_path.exists():
        spec = CoverPostcardSpec(
            title=title,
            top_text=args.top_text,
            bottom_text=args.bottom_text,
            out_path=postcard_path,
        )
        generate_postcard_cover(spec, debug_dir=debug_dir, letter_images=letters if use_letter_mode else None)

    if args.style == "enhanced":
        texture_path = Path(__file__).resolve().parents[1] / "assets" / "cover" / "postcard_paper_texture.jpg"
        generate_composited_cover(
            postcard_path=postcard_path,
            out_path=composite_path,
            texture_path=texture_path,
            debug_dir=debug_dir,
        )

    # Optional comparison artifacts (only in letter mode with debug enabled)
    if debug_dir and args.compare_scenery and use_letter_mode:
        try:
            scenery_out = debug_dir / "postcard_scenery.png"
            spec_scenery = CoverPostcardSpec(
                title=title,
                top_text=args.top_text,
                bottom_text=args.bottom_text,
                out_path=scenery_out,
            )
            generate_postcard_cover(spec_scenery, debug_dir=debug_dir, letter_images=None)
            if postcard_path.exists() and scenery_out.exists():
                letter_img = Image.open(postcard_path).convert("RGBA")
                scenery_img = Image.open(scenery_out).convert("RGBA")
                side_by_side = Image.new(
                    "RGBA",
                    (letter_img.width + scenery_img.width, max(letter_img.height, scenery_img.height)),
                    (255, 255, 255, 255),
                )
                side_by_side.paste(letter_img, (0, 0))
                side_by_side.paste(scenery_img, (letter_img.width, 0))
                side_by_side_path = debug_dir / "compare_letter_vs_scenery.png"
                side_by_side.save(side_by_side_path)

                # Crop around the center of the letter alpha bbox
                alpha = letter_img.split()[-1]
                bbox = alpha.getbbox() or (letter_img.width // 4, letter_img.height // 4, 3 * letter_img.width // 4, 3 * letter_img.height // 4)
                cx = (bbox[0] + bbox[2]) // 2
                cy = (bbox[1] + bbox[3]) // 2
                crop_w, crop_h = 300, 150
                left = max(0, cx - crop_w // 2)
                top = max(0, cy - crop_h // 2)
                right = min(letter_img.width, left + crop_w)
                bottom = min(letter_img.height, top + crop_h)
                left = max(0, right - crop_w)
                top = max(0, bottom - crop_h)
                box = (left, top, right, bottom)
                letter_crop_path = debug_dir / "edge_crop_letter.png"
                scenery_crop_path = debug_dir / "edge_crop_scenery.png"
                letter_img.crop(box).save(letter_crop_path)
                scenery_img.crop(box).save(scenery_crop_path)
                logger.info(
                    "[postcard-compare] debug_dir=%s side_by_side=%s letter_crop=%s scenery_crop=%s",
                    debug_dir,
                    side_by_side_path,
                    letter_crop_path,
                    scenery_crop_path,
                )
        except Exception:
            logger.warning("Failed to save comparison artifacts", exc_info=True)

    mode_label = "LETTER_IMAGES" if use_letter_mode else "SCENERY"
    sha = ""
    try:
        sha = hashlib.sha256(postcard_path.read_bytes()).hexdigest()
    except Exception:
        sha = "n/a"
    logger.info(
        "[postcard] mode=%s interpreter=%s engine=%s scenery_path=%s letter_images_count=%s letter_images_dir=%s output=%s sha256=%s",
        mode_label,
        sys.executable,
        getattr(postcard_engine, "__file__", "n/a"),
        (Path(args.media_root).resolve() / "books" / book_id / "photos"),
        len(letters),
        photos_dir,
        postcard_path,
        sha,
    )
    logger.info("Rendered postcard assets:")
    logger.info("  postcard: %s", postcard_path)
    if args.style == "enhanced":
        logger.info("  composite: %s", composite_path)
    if debug_dir:
        logger.info("  debug_dir: %s", debug_dir)
        if args.compare_scenery and use_letter_mode:
            logger.info(
                "  compare: %s | letter_crop: %s | scenery_crop: %s",
                debug_dir / "compare_letter_vs_scenery.png",
                debug_dir / "edge_crop_letter.png",
                debug_dir / "edge_crop_scenery.png",
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
