import glob
import hashlib
import json
import logging
import math
import os
import contextlib
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
import shutil
from PIL import Image, ImageOps, ImageFilter, ImageDraw, ImageChops

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


@contextlib.contextmanager
def _temporary_cwd(path: Path):
    prev = Path.cwd()
    os.chdir(path)
    try:
        yield
    finally:
        os.chdir(prev)


def _copy_debug_artifact(src_path: Path, debug_dir: Path) -> None:
    dst_path = (debug_dir / src_path.name)
    try:
        if src_path.resolve() == dst_path.resolve():
            return
    except Exception:
        pass
    try:
        shutil.copy2(src_path, dst_path)
    except Exception:
        logger.warning("[debug-artifacts] failed to copy %s -> %s", src_path, dst_path, exc_info=True)


def generate_postcard_cover(
    spec: CoverPostcardSpec,
    debug_dir: Optional[Path] = None,
    letter_images: Optional[list] = None,
) -> Path:
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

    temp_ctx = None
    prev_debug_env = os.environ.get("DEBUG")
    prev_debug_artifacts = os.environ.get("PHOTOBOOK_DEBUG_ARTIFACTS")
    from vendor.postcard_renderer import engine as postcard_engine
    prev_engine_debug = getattr(postcard_engine, "DEBUG", False)

    if debug_dir:
        os.environ["PHOTOBOOK_DEBUG_ARTIFACTS"] = "1"
        os.environ["DEBUG"] = "1"
        postcard_engine.DEBUG = True
        debug_dir.mkdir(parents=True, exist_ok=True)
        workdir = debug_dir
    else:
        temp_ctx = tempfile.TemporaryDirectory()
        workdir = Path(temp_ctx.name)
    cwd_ctx = _temporary_cwd(workdir)

    with cwd_ctx:
        render_postcard(config, letter_images=letter_images if letter_images else None)

    # Copy debug artifacts if requested
    if debug_dir:
        files_in_workdir = sorted([Path(p).name for p in glob.glob(str(workdir / "temp*.png"))])
        files_in_cwd = sorted([Path(p).name for p in glob.glob("temp*.png")])
        for f in glob.glob(str(workdir / "temp*.png")):
            src = Path(f)
            if src.exists():
                try:
                    _copy_debug_artifact(src, debug_dir)
                except Exception:
                    logger.warning("[debug-artifacts] failed to retain %s", src, exc_info=True)
        logger.info(
            "[debug-artifacts] after_render cwd=%s workdir=%s found_in_workdir=%s found_in_cwd=%s",
            Path.cwd(),
            workdir,
            files_in_workdir,
            files_in_cwd,
        )

    if temp_ctx:
        temp_ctx.cleanup()
    if prev_debug_env is None:
        os.environ.pop("DEBUG", None)
    else:
        os.environ["DEBUG"] = prev_debug_env
    if prev_debug_artifacts is None:
        os.environ.pop("PHOTOBOOK_DEBUG_ARTIFACTS", None)
    else:
        os.environ["PHOTOBOOK_DEBUG_ARTIFACTS"] = prev_debug_artifacts
    postcard_engine.DEBUG = prev_engine_debug
    return spec.out_path


def generate_composited_cover(
    postcard_path: Path,
    out_path: Path,
    texture_path: Path,
    rotate_deg: float = -7.0,
    inset_frac: float = 0.08,
    shadow_offset: tuple[int, int] = (18, 18),
    shadow_radius: int = 18,
    debug_dir: Optional[Path] = None,
) -> Path:
    """
    Composite the postcard onto a textured card, then tilt the entire stack with shadow.
    """
    def _magic_wand_cutout(img: Image.Image, tolerance_v: float = 0.90, tolerance_s: float = 0.12) -> tuple[Image.Image, Image.Image]:
        """
        Flood-fill from corners to remove connected near-white background without cropping.
        Returns (rgba_with_cutout, cutout_mask_white_removed).
        """
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        w, h = img.size
        pix = img.load()
        visited = [[False] * h for _ in range(w)]
        from collections import deque
        q = deque()
        for p in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
            q.append(p)
        mask = Image.new("L", (w, h), 0)
        mask_data = mask.load()

        def _within_tol(px):
            r, g, b, a = px
            if a < 10:
                return True
            mx = max(r, g, b) / 255.0
            mn = min(r, g, b) / 255.0
            v = mx
            s = 0 if mx == 0 else (mx - mn) / mx
            return v >= tolerance_v and s <= tolerance_s

        while q:
            x, y = q.popleft()
            if x < 0 or y < 0 or x >= w or y >= h or visited[x][y]:
                continue
            visited[x][y] = True
            if not _within_tol(pix[x, y]):
                continue
            mask_data[x, y] = 255
            q.append((x + 1, y))
            q.append((x - 1, y))
            q.append((x, y + 1))
            q.append((x, y - 1))

        mask = mask.filter(ImageFilter.MaxFilter(3))
        mask = mask.filter(ImageFilter.GaussianBlur(radius=1))
        rgba = img.copy()
        a = rgba.split()[-1]
        a = ImageChops.subtract(a, mask)
        rgba.putalpha(a)
        return rgba, mask
    def rotated_size(size: tuple[int, int], deg: float) -> tuple[float, float]:
        w, h = size
        rad = math.radians(deg)
        cos_a = abs(math.cos(rad))
        sin_a = abs(math.sin(rad))
        return (w * cos_a + h * sin_a, w * sin_a + h * cos_a)

    TARGET_FIT_W = 0.75  # rotated bbox max width vs cover width
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

    # Texture as card face (keep full texture; apply rounded mask)
    texture_source = Image.open(texture_path).convert("RGB")
    card_face_base = texture_source.resize(card_size, resample=Image.Resampling.LANCZOS).convert("RGBA")
    card_face = card_face_base.copy()
    card_face_cutout, cutout_mask = _magic_wand_cutout(card_face, tolerance_v=0.90, tolerance_s=0.12)

    # Masks
    mask_window = Image.new("L", card_size, 0)
    ImageDraw.Draw(mask_window).rectangle((0, 0, card_size[0] - 1, card_size[1] - 1), fill=255)

    # Card mask remains fully opaque/rectangular (no rounded alpha)
    mask_card = Image.new("L", card_size, 255)
    card_face = card_face_cutout.copy()
    card_layer = Image.new("RGBA", card_size, (0, 0, 0, 0))
    card_layer.paste(card_face, (0, 0))

    # Place postcard art scaled to cover the enlarged inner window; rotate once at the end
    WINDOW_MARGIN_X_FACTOR = 0.60
    WINDOW_MARGIN_Y_FACTOR = 0.75
    window_inset_x = int(card_size[0] * inset_frac * WINDOW_MARGIN_X_FACTOR)
    window_inset_y = int(card_size[1] * inset_frac * WINDOW_MARGIN_Y_FACTOR)
    window_w = max(1, card_size[0] - 2 * window_inset_x)
    window_h = max(1, card_size[1] - 2 * window_inset_y)
    scale_pc = max(window_w / postcard.width, window_h / postcard.height)
    def _resize_rgba_premultiplied(img: Image.Image, size: tuple[int, int]) -> Image.Image:
        if img.size == size:
            return img.copy()
        if img.mode != "RGBA":
            img = img.convert("RGBA")
        r, g, b, a = img.split()
        r = Image.composite(r, Image.new("L", img.size, 0), a)
        g = Image.composite(g, Image.new("L", img.size, 0), a)
        b = Image.composite(b, Image.new("L", img.size, 0), a)
        r = r.resize(size, resample=Image.Resampling.LANCZOS)
        g = g.resize(size, resample=Image.Resampling.LANCZOS)
        b = b.resize(size, resample=Image.Resampling.LANCZOS)
        a = a.resize(size, resample=Image.Resampling.LANCZOS)
        # Un-premultiply
        a_data = a.load()
        r_data, g_data, b_data = r.load(), g.load(), b.load()
        for y in range(size[1]):
            for x in range(size[0]):
                alpha = a_data[x, y]
                if alpha == 0:
                    r_data[x, y] = 0
                    g_data[x, y] = 0
                    b_data[x, y] = 0
                else:
                    r_data[x, y] = int(min(255, r_data[x, y] * 255 / alpha))
                    g_data[x, y] = int(min(255, g_data[x, y] * 255 / alpha))
                    b_data[x, y] = int(min(255, b_data[x, y] * 255 / alpha))
        return Image.merge("RGBA", (r, g, b, a))

    postcard_scaled = postcard
    if scale_pc < 0.999 or scale_pc > 1.001:
        new_size = (max(1, int(postcard.width * scale_pc)), max(1, int(postcard.height * scale_pc)))
        postcard_scaled = _resize_rgba_premultiplied(postcard, new_size)
    window_mask_scaled = mask_window.resize(postcard_scaled.size, resample=Image.Resampling.NEAREST)
    postcard_scaled.putalpha(window_mask_scaled)
    left = max(0, (postcard_scaled.width - window_w) // 2)
    top = max(0, (postcard_scaled.height - window_h) // 2)
    postcard_cropped = postcard_scaled.crop((left, top, left + window_w, top + window_h))
    px = window_inset_x
    py = window_inset_y
    postcard_full = postcard_cropped.copy()
    card_layer.alpha_composite(postcard_full, dest=(px, py))

    postcard_before_alpha = card_layer.copy()
    card_layer_alpha = ImageChops.multiply(card_layer.split()[-1], mask_card)
    card_layer.putalpha(card_layer_alpha)
    postcard_after_alpha = card_layer

    # Clean fully transparent pixels to avoid halo during resample
    alpha_mask = card_layer.getchannel("A")
    card_layer = Image.composite(card_layer, Image.new("RGBA", card_layer.size, (0, 0, 0, 0)), alpha_mask)

    card_layer_flat = card_layer

    # Persist full postcard (with border/template) to postcard_path for downstream use.
    postcard_full = card_layer_flat
    postcard_full.save(postcard_path)

    # Drop shadow from alpha, padded to avoid clipping; rotate group together
    shadow_blur = max(8, int(0.018 * min(card_layer_flat.size)))
    shadow_dx = int(0.010 * card_layer_flat.width)
    shadow_dy = int(0.022 * card_layer_flat.height)
    shadow_opacity = 220
    pad = shadow_blur * 3 + max(abs(shadow_dx), abs(shadow_dy)) + 4
    group_size = (card_layer_flat.width + pad * 2, card_layer_flat.height + pad * 2)

    card_alpha = card_layer_flat.split()[-1]
    shadow_base_mask = card_alpha.filter(ImageFilter.MaxFilter(5))
    shadow_mask = shadow_base_mask.filter(ImageFilter.GaussianBlur(radius=shadow_blur))
    shadow_alpha = shadow_mask.point(lambda p: min(255, int(p * (shadow_opacity / 255.0))))

    shadow_layer = Image.new("RGBA", group_size, (0, 0, 0, 0))
    shadow_bitmap = Image.new("RGBA", (card_layer_flat.width, card_layer_flat.height), (0, 0, 0, shadow_opacity))
    shadow_bitmap.putalpha(shadow_alpha)
    shadow_layer.paste(shadow_bitmap, (pad + shadow_dx, pad + shadow_dy), shadow_bitmap)

    group = Image.new("RGBA", group_size, (0, 0, 0, 0))
    group = Image.alpha_composite(group, shadow_layer)
    card_padded = Image.new("RGBA", group_size, (0, 0, 0, 0))
    card_padded.paste(card_layer_flat, (pad, pad), card_layer_flat)
    group = Image.alpha_composite(group, card_padded)

    card_layer_tilted = card_layer_flat.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    group_rot = group.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    shadow_rot = shadow_layer.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0))
    rot_w, rot_h = group_rot.size
    scale_card = min(
        (canvas_w * TARGET_FIT_W) / rot_w,
        (canvas_h * TARGET_FIT_H) / rot_h,
        1.0,
    )
    if scale_card < 0.999 or scale_card > 1.001:
        new_size = (max(1, int(group_rot.width * scale_card)), max(1, int(group_rot.height * scale_card)))
        group_rot = group_rot.resize(new_size, resample=Image.Resampling.LANCZOS)
        shadow_rot = shadow_rot.resize(new_size, resample=Image.Resampling.LANCZOS)

    # Composite onto base canvas, centered
    final = base.copy()
    gx = (canvas_w - group_rot.width) // 2
    gy = (canvas_h - group_rot.height) // 2
    temp_shadow = Image.new("RGBA", final.size, (0, 0, 0, 0))
    temp_shadow.paste(shadow_rot, (gx, gy), shadow_rot)
    final = Image.alpha_composite(final, temp_shadow)
    temp = Image.new("RGBA", final.size, (0, 0, 0, 0))
    temp.paste(group_rot, (gx, gy), group_rot)
    final = Image.alpha_composite(final, temp)

    if debug_dir:
        debug_dir.mkdir(parents=True, exist_ok=True)
        postcard.save(debug_dir / "postcard_original.png")
        postcard_scaled.save(debug_dir / "debug_face_window.png")
        texture_source.save(debug_dir / "debug_paper_texture_source.png")
        card_face_base.save(debug_dir / "debug_paper_texture_resized.png")
        card_face.save(debug_dir / "debug_paper_texture_final.png")
        card_face_base.save(debug_dir / "debug_postcard_base_texture.png")
        card_face.save(debug_dir / "debug_postcard_template_only.png")
        postcard_full.save(debug_dir / "debug_postcard_with_border.png")
        mask_card.save(debug_dir / "debug_postcard_alpha.png")
        window_mask_scaled.save(debug_dir / "debug_window_mask.png")
        mask_card.save(debug_dir / "debug_card_mask.png")
        postcard_before_alpha.save(debug_dir / "debug_postcard_before_card_alpha.png")
        postcard_after_alpha.save(debug_dir / "debug_postcard_after_card_alpha.png")
        card_face.save(debug_dir / "debug_postcard_paper_rgba.png")
        postcard_after_alpha.save(debug_dir / "debug_postcard_final.png")
        cutout_mask.save(debug_dir / "debug_cutout_mask.png")
        card_face_cutout.save(debug_dir / "debug_postcard_after_cutout.png")
        overlay = card_face_base.copy()
        draw_overlay = ImageDraw.Draw(overlay)
        draw_overlay.rectangle(
            (window_inset_x, window_inset_y, window_inset_x + window_w, window_inset_y + window_h),
            outline=(255, 0, 0, 255),
            width=4,
        )
        overlay.save(debug_dir / "debug_window_overlay.png")
        crop_meta = {
            "applied_crop": False,
            "window_inset_x": window_inset_x,
            "window_inset_y": window_inset_y,
            "window_size": [window_w, window_h],
            "postcard_scaled": [postcard_scaled.width, postcard_scaled.height],
            "placement": [px, py],
            "saved_postcard_path": str(postcard_path),
            "paper_crop_applied": False,
            "paper_size": [card_size[0], card_size[1]],
            "postcard_mode_before_save": postcard_full.mode,
            "group_size": list(group_size),
            "group_rot_size": [group_rot.width, group_rot.height],
            "shadow_pad": pad,
            "shadow_dx": shadow_dx,
            "shadow_dy": shadow_dy,
            "scale_card": scale_card,
        }
        (debug_dir / "debug_postcard_crop.json").write_text(json.dumps(crop_meta, indent=2))
        card_layer_flat.save(debug_dir / "card_layer_flat.png")
        card_layer_flat.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC, fillcolor=(0, 0, 0, 0)).save(debug_dir / "card_layer_tilted.png")
        shadow_layer.save(debug_dir / "shadow.png")
        gray_bg = Image.new("RGBA", shadow_layer.size, (128, 128, 128, 255))
        gray_bg.paste(shadow_layer, (0, 0), shadow_layer)
        gray_bg.save(debug_dir / "debug_postcard_shadow_only.png")
        Image.merge("RGBA", (Image.new("L", group_size, 128),) * 3 + (shadow_layer.split()[-1],)).save(debug_dir / "debug_postcard_shadow_mask.png")
        group.save(debug_dir / "debug_postcard_group.png")
        final.save(debug_dir / "final_composite.png")
        pipeline = {
            "postcard_original": [postcard.width, postcard.height],
            "postcard_scaled_window": [postcard_scaled.width, postcard_scaled.height],
            "postcard_with_border": [postcard_full.width, postcard_full.height],
            "card_layer_flat": [card_layer_flat.width, card_layer_flat.height],
            "card_layer_tilted": [card_layer_tilted.width, card_layer_tilted.height],
            "final_composite": [final.width, final.height],
        }
        (debug_dir / "debug_pipeline_stage_names.json").write_text(json.dumps(pipeline, indent=2))

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
        media_root_path = Path(media_root).resolve()
        background_image = None
        if background_asset_id and background_asset_id in assets:
            candidate_path = media_root_path / assets[background_asset_id].file_path
            payload["cover_background_asset_id"] = background_asset_id
            if candidate_path.exists():
                background_image = candidate_path
                payload["cover_background_path"] = _to_posix_rel(candidate_path, media_root_path)

        inset_frac = 0.1
        fingerprint_payload = {
            "cover_style": cover_style,
            "title": title,
            "bottom_text": bottom_text,
            "background_asset_id": background_asset_id,
            "background_image": str(background_image) if background_image else None,
            "rotate_deg": -7.0,
            "window_inset_frac": inset_frac,
            "ring_thickness_frac": 0.04,
            "target_fit_w": 0.75,
            "target_fit_h": 0.70,
        }
        fingerprint = hashlib.sha256(json.dumps(fingerprint_payload, sort_keys=True).encode("utf-8")).hexdigest()
        fname_stub = fingerprint[:12]
        abs_output = Path(output_path).resolve()
        media_root_path = Path(media_root).resolve()
        assets_dir = (abs_output.parent / "assets").resolve()
        assets_dir.mkdir(parents=True, exist_ok=True)
        debug_enabled = os.getenv("PHOTOBOOK_DEBUG_ARTIFACTS", "0") == "1"
        force_regen = os.getenv("PHOTOBOOK_DEBUG_FORCE_REGEN", "0") == "1"
        debug_dir = None
        expected_debug = ["temp_face_mask.png", "temp_warped_face_mask.png", "temp_warped_group.png"]
        if debug_enabled:
            debug_dir = assets_dir / "debug" / fname_stub
            debug_dir.mkdir(parents=True, exist_ok=True)
            print(f"[debug-artifacts] enabled=1 debug_dir={debug_dir}")
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
            generate_postcard_cover(spec, debug_dir=debug_dir)

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
                    inset_frac=inset_frac,
                    debug_dir=debug_dir,
                )
                return composite_path
            else:
                return postcard_path

        def ensure_generated(style: str) -> Path:
            target_path = composite_path if style == "enhanced" else postcard_path
            sidecar = target_path.with_suffix(target_path.suffix + ".json")
            existing_fp = _load_fingerprint(sidecar)
            debug_missing = False
            if debug_dir:
                debug_missing = not any((debug_dir / name).exists() for name in expected_debug)
            cache_hit = target_path.exists() and existing_fp == fingerprint_payload
            if cache_hit and debug_missing:
                logger.info("[debug-artifacts] cache_hit=1 but debug missing -> regenerating debug artifacts")
            if cache_hit and not force_regen and not debug_missing:
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

        cover_rel_path = _to_posix_rel(cover_path, media_root_path)
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
