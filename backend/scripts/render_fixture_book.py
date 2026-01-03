"""Render a deterministic fixture book and generate per-page thumbnails.

Usage:
    python -m backend.scripts.render_fixture_book

Outputs go to `backend/tests/artifacts/fixture_run/` and are gitignored.

This script is intentionally conservative: it generates simple placeholder
images using Pillow if fixture images are not present. It then constructs a
small `Book` and a sequence of `PageLayout` objects that exercise common
page types and calls the existing rendering pipeline `render_book_to_pdf`.

Thumbnail generation uses PyMuPDF (`fitz`) when available, otherwise it will
skip thumbnails but still produce the PDF. This keeps the harness optional
and easy to run on CI or local dev machines.
"""

from __future__ import annotations

import os
from pathlib import Path
import logging
import sys
from typing import List

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = None

try:
    import fitz  # PyMuPDF
except Exception:
    fitz = None

from domain.models import (
    Book,
    BookSize,
    Page,
    PageType,
    Asset,
    AssetType,
    AssetStatus,
    PageLayout,
    LayoutRect,
    RenderContext,
    Theme,
)
from services.render_pdf import render_book_to_pdf

ROOT = Path(__file__).resolve().parents[1]
FIXTURES_DIR = ROOT / "tests" / "fixtures"
IMAGES_DIR = FIXTURES_DIR / "images"
ARTIFACTS_DIR = ROOT / "tests" / "artifacts" / "fixture_run"

LOG = logging.getLogger("render_fixture_book")


def ensure_fixture_images():
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    # Define fixtures
    specs = [
        ("face_1.jpg", (800, 800), "face"),
        ("face_2.jpg", (600, 900), "face"),
        ("landscape.jpg", (1200, 800), "landscape"),
        ("portrait.jpg", (800, 1200), "portrait"),
        ("no_face.jpg", (1000, 700), "scene"),
        ("spread_hero.jpg", (2400, 1600), "hero"),
        ("map_stub.jpg", (1200, 800), "map"),
    ]

    for name, size, kind in specs:
        p = IMAGES_DIR / name
        if p.exists():
            continue
        if Image is None:
            LOG.warning("Pillow not available; cannot generate fixture image %s", name)
            continue
        img = Image.new("RGB", size, (240, 240, 240))
        d = ImageDraw.Draw(img)
        w, h = size
        # simple decorations by kind
        if kind == "face":
            # draw a simple face-like circle
            cx, cy = w // 2, h // 2
            r = min(w, h) // 4
            d.ellipse((cx - r, cy - r, cx + r, cy + r), fill=(255, 224, 189), outline=(120, 80, 40))
            d.ellipse((cx - r // 3, cy - r // 4, cx - r // 6, cy - r // 6), fill=(0, 0, 0))
            d.ellipse((cx + r // 6, cy - r // 4, cx + r // 3, cy - r // 6), fill=(0, 0, 0))
            d.arc((cx - r // 2, cy, cx + r // 2, cy + r // 1), 0, 180, fill=(120, 50, 40), width=6)
        elif kind == "landscape":
            d.rectangle((0, int(h * 0.6), w, h), fill=(34, 139, 34))
            d.rectangle((0, 0, w, int(h * 0.6)), fill=(135, 206, 235))
        elif kind == "portrait":
            d.rectangle((0, 0, w, int(h * 0.4)), fill=(70, 130, 180))
            d.rectangle((0, int(h * 0.4), w, h), fill=(205, 133, 63))
        elif kind == "scene":
            d.rectangle((0, 0, w, h), fill=(200, 200, 220))
            d.text((20, 20), "No face scene", fill=(80, 80, 80))
        elif kind == "hero":
            d.rectangle((0, 0, w, h), fill=(180, 120, 200))
            d.text((40, 40), "Spread hero", fill=(255, 255, 255))
        elif kind == "map":
            d.rectangle((0, 0, w, h), fill=(245, 245, 245))
            # draw a stub polyline
            poly = [(int(w * x), int(h * (0.2 + 0.6 * (i / 8)))) for i, x in enumerate([0.05, 0.12, 0.24, 0.45, 0.62, 0.78, 0.92])]
            for i in range(len(poly) - 1):
                d.line((poly[i], poly[i + 1]), fill=(20, 120, 200), width=6)

        try:
            img.save(p, format="JPEG", quality=85)
            LOG.info("Generated fixture image %s", p)
        except Exception:
            LOG.exception("Failed to save fixture image %s", p)


def build_fixture_book() -> (Book, List[PageLayout], dict):
    # Build a small book and layouts manually
    book = Book(id="fixture-book", title="Fixture Book", size=BookSize.SQUARE_8)

    # Assets: map filenames to Asset objects. Use relative `tests/fixtures/...` paths
    assets = {}
    filenames = sorted([f.name for f in (IMAGES_DIR.glob("*.jpg"))])
    for idx, name in enumerate(filenames):
        aid = f"asset-{idx}"
        assets[aid] = Asset(
            id=aid,
            book_id=book.id,
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path=str(Path("tests") / "fixtures" / "images" / name),
        )

    # Helper mappings
    asset_ids = list(assets.keys())
    name_to_aid = {Path(a.file_path).name: a.id for a in assets.values()}
    def pick_by_name(name):
        return name_to_aid.get(name)
    def pick(i):
        return asset_ids[i % len(asset_ids)]

    layouts: List[PageLayout] = []

    # Front cover (hero)
    # Front cover uses the spread hero asset
    layouts.append(PageLayout(page_index=0, page_type=PageType.FRONT_COVER, elements=[
        LayoutRect(x_mm=0, y_mm=0, width_mm=210, height_mm=210, asset_id=pick_by_name("spread_hero.jpg")),
    ], payload={}))

    # Trip summary (text + small image)
    layouts.append(PageLayout(page_index=1, page_type=PageType.TRIP_SUMMARY, elements=[
        LayoutRect(x_mm=20, y_mm=20, width_mm=80, height_mm=60, text="Trip summary: Fixture run", font_size=16),
        LayoutRect(x_mm=110, y_mm=20, width_mm=80, height_mm=60, asset_id=pick_by_name("landscape.jpg")),
    ], payload={}))

    # Map route page — include deterministic `segments` (trip polyline) and set `book_id`
    trip_segments = [
        {"polyline": [
            (37.7749, -122.4194),
            (37.7890, -122.3900),
            (37.8044, -122.2712),
            (37.8715, -122.2730),
        ]}
    ]
    layouts.append(
        PageLayout(
            page_index=2,
            page_type=PageType.MAP_ROUTE,
            elements=[],
            payload={},
            segments=trip_segments,
            book_id=book.id,
        )
    )

    # Day intro (map stripe) — provide a deterministic per-day polyline and book_id
    day1_segments = [
        {"polyline": [
            (37.7749, -122.4194),
            (37.7799, -122.4148),
        ]}
    ]
    layouts.append(
        PageLayout(
            page_index=3,
            page_type=PageType.DAY_INTRO,
            elements=[
                LayoutRect(x_mm=10, y_mm=60, width_mm=190, height_mm=40, text="Day 1: Fixture day intro", font_size=14),
            ],
            payload={},
            segments=day1_segments,
            book_id=book.id,
        )
    )

    # Photo grid default (2x2)
    grid_elems = []
    w = 95
    h = 95
    positions = [(10, 10), (110, 10), (10, 110), (110, 110)]
    for i, (x, y) in enumerate(positions[:4]):
        # reference assets by asset_id so the renderer counts them as photo elements
        grid_elems.append(LayoutRect(x_mm=x, y_mm=y, width_mm=w, height_mm=h, asset_id=pick(i)))
    layouts.append(PageLayout(page_index=4, page_type=PageType.PHOTO_GRID, elements=grid_elems, payload={}))

    # photo_grid grid_4_simple (explicit variant)
    layouts.append(PageLayout(page_index=5, page_type=PageType.PHOTO_GRID, layout_variant="grid_4_simple", elements=grid_elems, payload={}))

    # full page photo
    layouts.append(PageLayout(page_index=6, page_type=PageType.FULL_PAGE_PHOTO, elements=[
        LayoutRect(x_mm=0, y_mm=0, width_mm=210, height_mm=210, asset_id=pick_by_name("portrait.jpg")),
    ], payload={}))

    # photo_spread (two halves)
    layouts.append(PageLayout(page_index=7, page_type=PageType.PHOTO_SPREAD, spread_slot="left", elements=[
        LayoutRect(x_mm=0, y_mm=0, width_mm=105, height_mm=210, asset_id=pick_by_name("landscape.jpg")),
        LayoutRect(x_mm=105, y_mm=0, width_mm=105, height_mm=210, asset_id=pick_by_name("face_1.jpg")),
    ], payload={}))

    # back cover
    layouts.append(PageLayout(page_index=8, page_type=PageType.BACK_COVER, elements=[
        LayoutRect(x_mm=0, y_mm=0, width_mm=210, height_mm=210, asset_id=pick_by_name("no_face.jpg")),
    ], payload={}))

    return book, layouts, assets


def generate_thumbnails(pdf_path: Path, out_dir: Path):
    out_dir.mkdir(parents=True, exist_ok=True)
    if fitz is None:
        LOG.warning("PyMuPDF not installed; skipping thumbnail generation")
        return []

    doc = fitz.open(str(pdf_path))
    out_files = []
    for i, page in enumerate(doc):
        pix = page.get_pixmap(dpi=150)
        out_file = out_dir / f"page_{i+1:03d}.png"
        pix.save(str(out_file))
        out_files.append(out_file)
    return out_files


def main():
    logging.basicConfig(level=logging.INFO)
    ensure_fixture_images()
    book, layouts, assets = build_fixture_book()

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    out_pdf = ARTIFACTS_DIR / "fixture_book.pdf"

    # media_root is the repo root so relative file paths in assets work
    media_root = str(ROOT)
    LOG.info("Rendering PDF to %s", out_pdf)
    try:
        render_book_to_pdf(book, layouts, assets, RenderContext(book_size=book.size), str(out_pdf), media_root)
    except Exception:
        LOG.exception("Failed to render PDF")
        sys.exit(2)

    # thumbnails
    pages_dir = ARTIFACTS_DIR / "pages"
    thumbs = generate_thumbnails(out_pdf, pages_dir)
    LOG.info("Rendered %s pages, thumbnails: %s", len(thumbs), pages_dir)
    print(f"PDF: {out_pdf}")
    print(f"Pages dir: {pages_dir}")

    # --- Smoke assertions for CI / smoke checks ---
    MIN_PDF_BYTES = 50 * 1024
    MIN_PNG_BYTES = 5 * 1024

    ok_checks = []

    # PDF exists and is reasonably large
    try:
        pdf_bytes = out_pdf.stat().st_size
        assert pdf_bytes > MIN_PDF_BYTES, f"PDF too small ({pdf_bytes} bytes)"
        ok_checks.append((str(out_pdf), pdf_bytes))
    except Exception as e:
        LOG.exception("PDF smoke check failed: %s", e)
        sys.exit(3)

    # Trip route PNG
    maps_dir = ROOT / "data" / "maps"
    trip_maps = sorted(maps_dir.glob(f"book_{book.id}_route*.png"))
    if not trip_maps:
        LOG.error("Expected trip route image for book %s not found in %s", book.id, maps_dir)
        sys.exit(4)
    trip_map = trip_maps[-1]
    trip_bytes = trip_map.stat().st_size
    if trip_bytes <= MIN_PNG_BYTES:
        LOG.error("Trip route PNG too small: %s (%d bytes)", trip_map, trip_bytes)
        sys.exit(5)
    ok_checks.append((str(trip_map), trip_bytes))

    # At least one day route PNG
    day_maps = sorted(maps_dir.glob(f"book_{book.id}_day_*_route*.png"))
    if not day_maps:
        LOG.error("No day route images found in %s", maps_dir)
        sys.exit(6)
    # check first day map size
    day_bytes = day_maps[0].stat().st_size
    if day_bytes <= MIN_PNG_BYTES:
        LOG.error("Day route PNG too small: %s (%d bytes)", day_maps[0], day_bytes)
        sys.exit(7)
    ok_checks.append((str(day_maps[0]), day_bytes))

    # Thumbnails (optional)
    if fitz is not None:
        try:
            thumbs_list = sorted(pages_dir.glob("page_*.png"))
            if len(thumbs_list) == 0:
                LOG.error("Thumbnails were expected but none were generated in %s", pages_dir)
                sys.exit(8)
            # ensure a few thumbnails exist and are non-empty
            thumb_checks = 0
            for t in thumbs_list[:3]:
                if t.stat().st_size > 100:
                    thumb_checks += 1
            if thumb_checks == 0:
                LOG.error("Thumbnails exist but appear empty in %s", pages_dir)
                sys.exit(9)
            ok_checks.append(("thumbnails", len(thumbs_list)))
        except Exception:
            LOG.exception("Thumbnail smoke check failed")
            sys.exit(10)

    # Print summary OK
    print("SMOKE OK:")
    for p, s in ok_checks:
        print(f" - {p}: {s}")


if __name__ == "__main__":
    main()
