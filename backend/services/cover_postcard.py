from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from PIL import Image, ImageOps, ImageFilter, ImageDraw

from vendor.postcard_renderer.renderer import PostcardConfig, render_postcard


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

    # Shadow based on card alpha
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
    shadow_rot = shadow_offset_canvas.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC)
    card_rot = card_layer.rotate(rotate_deg, expand=True, resample=Image.Resampling.BICUBIC)

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
