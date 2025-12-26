import hashlib
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps, ImageFilter, ImageDraw

from domain.models import Asset, AssetStatus, AssetType, LayoutRect, PageLayout, PageType, RenderContext
from vendor.postcard_renderer.renderer import PostcardConfig, render_postcard

logger = logging.getLogger(__name__)


@dataclass
class CoverPostcardSpec:
    title: str
    top_text: str = "Greetings from"
    bottom_text: str = ""
    background_image: Optional[Path] = None
    out_path: Path = Path("cover_postcard.png")


def generate_postcard_cover(spec: CoverPostcardSpec) -> Path:
    """Render a postcard-style cover image to the requested path."""
    spec.out_path.parent.mkdir(parents=True, exist_ok=True)

    cfg_kwargs = {
        "text": spec.title,
        "script_top_text": spec.top_text,
        "script_bottom_text": spec.bottom_text,
        "output_filename": str(spec.out_path),
    }
    if spec.background_image:
        cfg_kwargs["background_image"] = str(spec.background_image)

    config = PostcardConfig(**cfg_kwargs)
    render_postcard(config)
    return spec.out_path


def generate_composited_cover(
    postcard_path: Path,
    out_path: Path,
    texture_path: Path,
    rotate_deg: float = -7.0,
    inset_frac: float = 0.1,
    shadow_offset: tuple[int, int] = (18, 18),
    shadow_radius: int = 18,
) -> Path:
    """
    Composite the postcard onto a textured card, then tilt the entire stack with shadow.
    """
    TARGET_FIT_W = 0.78  # rotated bbox max width vs cover width
    TARGET_FIT_H = 0.70  # rotated bbox max height vs cover height
    postcard = Image.open(postcard_path).convert("RGBA")
    canvas_w, canvas_h = postcard.size

    # Base canvas (solid color background; postcard stack sits on top)
    base = Image.new("RGBA", (canvas_w, canvas_h), (22, 58, 107, 255))  # #163a6b

    # Card sizing: slightly smaller than canvas to leave breathing room
    card_target_w = int(canvas_w * 0.75)
    card_target_h = int(card_target_w * (postcard.height / postcard.width))
    if card_target_h > int(canvas_h * 0.9):
        card_target_h = int(canvas_h * 0.9)
        card_target_w = int(card_target_h * (postcard.width / postcard.height))
    card_size = (max(1, card_target_w), max(1, card_target_h))

    # Texture as card face, cropped inward to avoid bright edges before fitting
    texture = Image.open(texture_path).convert("RGB")
    TEX_CROP_LEFT = 0.02
    TEX_CROP_RIGHT = 0.02
    TEX_CROP_TOP = 0.06
    TEX_CROP_BOTTOM = 0.02
    tw, th = texture.size
    crop_box = (
        int(round(tw * TEX_CROP_LEFT)),
        int(round(th * TEX_CROP_TOP)),
        int(round(tw * (1 - TEX_CROP_RIGHT))),
        int(round(th * (1 - TEX_CROP_BOTTOM))),
    )
    texture_cropped = texture.crop(crop_box)
    card_face = ImageOps.fit(texture_cropped, card_size, method=Image.Resampling.LANCZOS).convert("RGBA")

    # Key out near-white artifacts only in the outer ring to keep the border uniform
    RING_THICKNESS_FRAC = 0.04
    ring_thickness = max(1, int(card_size[0] * RING_THICKNESS_FRAC))
    ring_mask = Image.new("L", card_size, 255)
    ImageDraw.Draw(ring_mask).rectangle(
        (ring_thickness, ring_thickness, card_size[0] - ring_thickness, card_size[1] - ring_thickness),
        fill=0,
    )
    ring_data = ring_mask.getdata()
    data = list(card_face.getdata())
    def _is_near_pure_white(r: int, g: int, b: int) -> bool:
        mn = min(r, g, b)
        mx = max(r, g, b)
        return mn >= 248 and (mx - mn) <= 6
    new_data = []
    for (r, g, b, a), m in zip(data, ring_data):
        if m == 0:
            new_data.append((r, g, b, a))
            continue
        if _is_near_pure_white(r, g, b):
            a = 0
        new_data.append((r, g, b, a))
    card_face.putdata(new_data)
    card_layer = Image.new("RGBA", card_size, (0, 0, 0, 0))
    card_layer.paste(card_face, (0, 0))

    # Place postcard art in a centered window with uniform inset using cover crop
    window_inset = int(card_size[0] * 0.04)
    window_w = max(1, card_size[0] - 2 * window_inset)
    window_h = max(1, card_size[1] - 2 * window_inset)
    scale = max(window_w / postcard.width, window_h / postcard.height)
    resized = postcard.resize(
        (max(1, int(postcard.width * scale)), max(1, int(postcard.height * scale))),
        resample=Image.Resampling.LANCZOS,
    )
    left = max(0, (resized.width - window_w) // 2)
    top = max(0, (resized.height - window_h) // 2)
    postcard_cropped = resized.crop((left, top, left + window_w, top + window_h))
    px = window_inset
    py = window_inset
    card_layer.paste(postcard_cropped, (px, py), mask=postcard_cropped)

    # Clean fully transparent pixels to avoid halo during resample
    alpha_mask = card_layer.getchannel("A")
    card_layer = Image.composite(card_layer, Image.new("RGBA", card_layer.size, (0, 0, 0, 0)), alpha_mask)

    # Scale the card so the rotated bbox fits target fractions
    def rotated_size(size: tuple[int, int], angle: float) -> tuple[int, int]:
        dummy = Image.new("RGBA", size, (0, 0, 0, 0)).rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        return dummy.size

    rot_w, rot_h = rotated_size(card_layer.size, rotate_deg)
    scale = min(
        (canvas_w * TARGET_FIT_W) / rot_w,
        (canvas_h * TARGET_FIT_H) / rot_h,
        1.0,
    )
    if scale < 0.999:
        new_size = (max(1, int(card_layer.width * scale)), max(1, int(card_layer.height * scale)))
        card_layer = card_layer.resize(new_size, resample=Image.Resampling.LANCZOS)

    # Shadow based on scaled card alpha
    mask = card_layer.getchannel("A")
    soft_mask = mask.filter(ImageFilter.GaussianBlur(radius=1.5))
    shadow = Image.new("RGBA", card_layer.size, (0, 0, 0, 0))
    shadow_base = Image.new("RGBA", card_layer.size, (0, 0, 0, 140))
    shadow.paste(shadow_base, mask=soft_mask)
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=shadow_radius))
    shadow_offset_canvas = Image.new(
        "RGBA",
        (shadow.width + abs(shadow_offset[0]) + 4, shadow.height + abs(shadow_offset[1]) + 4),
        (0, 0, 0, 0),
    )
    ox = max(shadow_offset[0], 0)
    oy = max(shadow_offset[1], 0)
    shadow_offset_canvas.paste(shadow, (ox, oy), mask=shadow)

    # Rotate shadow and card together
    shadow_rot = shadow_offset_canvas.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    card_rot = card_layer.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))

    # Composite onto base canvas, centered
    final = base.copy()
    sx = (canvas_w - shadow_rot.width) // 2
    sy = (canvas_h - shadow_rot.height) // 2
    final.paste(shadow_rot, (sx, sy), mask=shadow_rot)
    cx = (canvas_w - card_rot.width) // 2
    cy = (canvas_h - card_rot.height) // 2
    final.paste(card_rot, (cx, cy), mask=card_rot)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    final.convert("RGB").save(out_path, format="PNG")
    return out_path


def _to_posix_rel(target: Path, base: Path) -> str:
    try:
        rel = target.relative_to(base)
    except Exception:
        rel = Path(os.path.relpath(target, start=base))
    return rel.as_posix()


def _load_fingerprint(path: Path) -> Optional[dict]:
    try:
        if not path.exists():
            return None
        return json.loads(path.read_text())
    except Exception:
        return None


def _write_fingerprint(path: Path, payload: dict) -> None:
    try:
        path.write_text(json.dumps(payload, indent=2))
    except Exception:
        logger.debug("Failed to write fingerprint at %s", path)


def ensure_cover_asset(
    book: object,
    layouts: list[PageLayout],
    assets: dict[str, Asset],
    context: RenderContext,
    media_root: str,
    output_path: str,
    cover_style_env: Optional[str] = None,
    mode_label: str = "unknown",
) -> Optional[str]:
    """
    Ensure a front-cover asset exists, registered, and wired into the front cover layout.

    Returns the chosen asset_id, or None on failure.
    """
    try:
        front_cover = next((l for l in layouts if getattr(l, "page_type", None) == PageType.FRONT_COVER), None)
        if front_cover is None:
            return None

        payload = getattr(front_cover, "payload", {}) or {}
        cover_style = (cover_style_env or os.environ.get("PHOTOBOOK_COVER_STYLE") or "classic").strip().lower()
        if cover_style not in ("classic", "enhanced"):
            cover_style = "classic"

        title = (payload.get("title") or getattr(book, "title", "") or "TRIP").strip() or "TRIP"
        bottom_text = payload.get("date_range") or payload.get("subtitle") or payload.get("stats_line") or ""
        hero_asset_id = payload.get("hero_asset_id")
        background_asset_id = payload.get("cover_background_asset_id")
        if not background_asset_id and hero_asset_id:
            background_asset_id = hero_asset_id
        if not background_asset_id:
            # Deterministic pick: first photo asset id sorted
            photo_assets = [a for a in assets.values() if getattr(a, "type", None) == AssetType.PHOTO]
            photo_assets.sort(key=lambda a: a.id)
            if photo_assets:
                background_asset_id = photo_assets[0].id
        background_image = None
        if background_asset_id and background_asset_id in assets:
            candidate_path = Path(media_root) / assets[background_asset_id].file_path
            payload["cover_background_asset_id"] = background_asset_id
            if candidate_path.exists():
                background_image = candidate_path
                payload["cover_background_path"] = _to_posix_rel(candidate_path, Path(media_root))

        assets_dir = Path(output_path).parent / "assets"
        assets_dir.mkdir(parents=True, exist_ok=True)
        fingerprint_payload = {
            "cover_style": cover_style,
            "title": title,
            "bottom_text": bottom_text,
            "background_asset_id": background_asset_id,
            "background_image": str(background_image) if background_image else None,
            "rotate_deg": -7.0,
            "window_inset_frac": 0.04,
            "ring_thickness_frac": 0.04,
            "target_fit_w": 0.78,
            "target_fit_h": 0.70,
        }
        fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()
        fname_stub = fingerprint[:12]
        postcard_path = assets_dir / f"cover_postcard_{fname_stub}.png"
        composite_path = assets_dir / f"cover_front_composite_{fname_stub}.png"

        def generate_base() -> None:
            spec = CoverPostcardSpec(
                title=title,
                top_text=payload.get("top_text") or "Greetings from",
                bottom_text=bottom_text or "",
                background_image=background_image,
                out_path=postcard_path,
            )
            generate_postcard_cover(spec)

        def generate_final(style: str) -> Path:
            if not postcard_path.exists():
                generate_base()
            if style == "enhanced":
                texture_path = Path(__file__).resolve().parent.parent / "assets" / "cover" / "postcard_paper_texture.jpg"
                if not texture_path.exists():
                    raise FileNotFoundError(f"Texture missing at {texture_path}")
                generate_composited_cover(
                    postcard_path=postcard_path,
                    out_path=composite_path,
                    texture_path=texture_path,
                    rotate_deg=-7.0,
                    inset_frac=0.1,
                )
                return composite_path
            else:
                return postcard_path

        def ensure_generated(style: str) -> Path:
            target_path = composite_path if style == "enhanced" else postcard_path
            sidecar = target_path.with_suffix(target_path.suffix + ".json")
            existing_fp = _load_fingerprint(sidecar)
            if target_path.exists() and existing_fp == fingerprint_payload:
                return target_path
            # Always refresh base when fingerprint changes
            generate_base()
            final_path = generate_final(style)
            _write_fingerprint(sidecar, fingerprint_payload)
            return final_path

        try:
            cover_path = ensure_generated(cover_style)
        except Exception:
            logger.exception("[cover] Failed enhanced generation; falling back to classic")
            cover_style = "classic"
            cover_path = ensure_generated("classic")

        cover_rel_path = _to_posix_rel(cover_path, Path(media_root))
        asset_id = cover_path.stem  # include fingerprint for cache-busting
        assets[asset_id] = Asset(
            id=asset_id,
            book_id=getattr(book, "id", "") or "",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path=cover_rel_path,
        )

        front_cover.elements = [
            LayoutRect(
                x_mm=0,
                y_mm=0,
                width_mm=context.page_width_mm,
                height_mm=context.page_height_mm,
                asset_id=asset_id,
            )
        ]
        payload["hero_asset_id"] = asset_id
        payload["cover_image_path"] = cover_rel_path
        payload["cover_style"] = cover_style
        front_cover.payload = payload

        # Debug log/print to align preview and PDF usage
        file_to_hash = cover_path
        sha = ""
        try:
            sha = hashlib.sha256(file_to_hash.read_bytes()).hexdigest()[:12]
        except Exception:
            sha = "n/a"
        msg = (
            f"[cover] mode={mode_label} book={getattr(book, 'id', None)} style={cover_style} "
            f"assets_dir={assets_dir} bg_asset_id={background_asset_id} "
            f"postcard={postcard_path} composite={composite_path} asset_id={asset_id} "
            f"page_type={getattr(front_cover, 'page_type', None)} cover_image_path={cover_rel_path} "
            f"size={cover_path.stat().st_size if cover_path.exists() else 'missing'} sha={sha}"
        )
        logger.info(msg)
        print(msg)

        return asset_id
    except Exception:
        logger.exception("[cover] Failed to ensure cover asset")
        return None
