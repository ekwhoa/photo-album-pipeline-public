import math
import os
import io
import random
import argparse
import sys
import sys
from typing import TYPE_CHECKING
import numpy as np
from pathlib import Path
import tempfile
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter, ImageEnhance, ImageOps
from wand.image import Image as WandImage
from wand.color import Color as WandColor
import sys

if TYPE_CHECKING:
    from .renderer import PostcardConfig

# --- CONFIGURATION ---
# Run (venv): .venv/bin/python vintage_card_final.py
# Alt (venv): source .venv/bin/activate && python vintage_card_final.py
# Debug toggle: DEBUG=1 .venv/bin/python vintage_card_final.py
TEXT = "NARNIA"
FONT_PATH = "Impact.ttf" # Ensure this file exists
SCENERY_IMAGE = "scenery.jpg" # Ensure this file exists
OUTPUT_FILENAME = "vintage_postcard_final.png"
BACKGROUND_IMAGE = "background.jpg" # Optional scenic background
DEBUG = os.getenv("DEBUG", "0") == "1"
SCRIPT_TOP_TEXT = "Greetings from"
SCRIPT_BOTTOM_TEXT = "Kingdom of Aslan"
SCRIPT_FONT_PATH = "Pacifico-Regular.ttf"  # Prefer a script font if available
SCRIPT_COLOR = (245, 245, 240, 230)
SCRIPT_STROKE_COLOR = (15, 15, 15, 160)
SCRIPT_STROKE_WIDTH = 2
SCRIPT_SHADOW = {"dx": 3, "dy": 3, "opacity": 110}

# Canvas Settings
BASE_FINAL_WIDTH = 2000
BASE_FINAL_HEIGHT = 1400
BASE_TEMP_TEXT_WIDTH = 2400 
BASE_TEMP_TEXT_HEIGHT = 1400
RENDER_SCALE = 2.0
FINAL_WIDTH = int(BASE_FINAL_WIDTH * RENDER_SCALE)
FINAL_HEIGHT = int(BASE_FINAL_HEIGHT * RENDER_SCALE)
# Temporary canvas wider to accommodate arc distortion
TEMP_TEXT_WIDTH = int(BASE_TEMP_TEXT_WIDTH * RENDER_SCALE)
TEMP_TEXT_HEIGHT = int(BASE_TEMP_TEXT_HEIGHT * RENDER_SCALE)
# Transform tuning
ROTATION_DEGREES = -8
PERSPECTIVE_TOP_INSET_RATIO = 0.06
PERSPECTIVE_VERTICAL_LIFT_RATIO = 0.035
APPLY_ROTATION = False
EXTRUSION_DEPTH = int(40 * RENDER_SCALE)
SIDE_FACE_COLOR = (20, 45, 95, 255)
SIDE_FACE_TEXTURE_INTENSITY = 0.08  # 0..1 scalar for subtle noise on side face
NAVY_OUTLINE = (15, 35, 85, 230)
DEPTH_DX = 1
DEPTH_DY = 1
EXTRUSION_FACE_THICKNESS_RATIO = 0.60
EXTRUSION_THICKEN_KERNEL = int(11 * RENDER_SCALE)
KEYLINE_INNER_KERNEL = int(25 * RENDER_SCALE)
KEYLINE_OUTER_KERNEL = int(33 * RENDER_SCALE)
USE_RISE_WARP = True
RISE_BEND_PCT = 30  # Illustrator-like Bend %
RISE_AMPLITUDE_FACTOR = 0.25  # scales bend strength vs image height
RISE_SLOPE_PX = int(0.40 * TEMP_TEXT_HEIGHT)  # baseline ramp left->right (stronger, flipped)
RISE_TOP_M = 0.65
RISE_BOTTOM_M = 0.35
RISE_TOP_GAMMA = 1.35
RISE_BOTTOM_GAMMA = 1.15
RISE_TOP_PHASE = 0.0
RISE_BOTTOM_PHASE = 0.0
RISE_H1 = 1.0
RISE_H2 = 0.35
RISE_H3 = -0.20
RISE_GAMMA = 1.35
RISE_STRENGTH_PX = int(120 * RENDER_SCALE)
RISE_COLS = 11
RISE_ROWS = 5
SHADOW_OFFSET = (int(14 * RENDER_SCALE), int(12 * RENDER_SCALE))
SHADOW_BLUR = int(10 * RENDER_SCALE)
SHADOW_COLOR = (0, 0, 0, 110)
WHITE_STROKE_PX = int(10 * RENDER_SCALE)
BLACK_STROKE_PX = int(16 * RENDER_SCALE)
EDGE_THICKNESS_PX = max(1, int(EXTRUSION_DEPTH * 0.06))
SWEEP_STEP = max(2, EDGE_THICKNESS_PX // 2)
BOTTOM_LIP_DEPTH = int(16 * RENDER_SCALE)
BOTTOM_LIP_EXTRA_DILATE = int(3 * RENDER_SCALE)
BOTTOM_LIP_BAND_PX = int(18 * RENDER_SCALE)
OUTER_STROKE_PX = int(8 * RENDER_SCALE)
OCCLUDE_PX = max(2, int(4 * RENDER_SCALE))
SCRIPT_SAFE_PAD = int(40 * RENDER_SCALE)
SCRIPT_BACK_ALPHA = 250
SCRIPT_BACK_STROKE_EXTRA = 1
SCRIPT_DESCENDER_PAD = int(14 * RENDER_SCALE)
SCRIPT_ROTATE_SAFE_PAD = int(32 * RENDER_SCALE)
SCRIPT_TOP_LEFT_MARGIN_X = int(120 * RENDER_SCALE)
SCRIPT_TOP_LEFT_MARGIN_Y = int(80 * RENDER_SCALE)
GUARD_PX = max(2, int(4 * RENDER_SCALE))
ORANGE_GRADIENT_STRENGTH = 0.65
ORANGE_DOT_ALPHA_MAX = 220
ORANGE_DOT_ALPHA_MIN = 40
ORANGE_DOT_PITCH = int(12 * RENDER_SCALE)
ORANGE_DOT_RADIUS_MIN = max(1, int(2 * RENDER_SCALE))
ORANGE_DOT_RADIUS_MAX = max(2, int(4 * RENDER_SCALE))
ORANGE_DOT_SHADE_GAMMA = 1.6
ORANGE_DOT_ROTATE_TO_DEPTH = True
LETTER_IMAGE_FALLBACK = "cycle"  # options: cycle, random, single
USE_SOFT_FACE_ALPHA = True
USE_SOFT_STROKES = False
USE_BOTTOM_BAND_CLAMP = False
BOTTOM_BAND_CLAMP_PX = int(18 * RENDER_SCALE)


# Pipeline overview (warp happens in Wand on the full text group: extrusion + stroke + face).
# Steps:
# 1) Build text group layers (extrusion, stroke, face) and save 01_text_group_prewarp.png when DEBUG.
# 2) Warp full text group in Wand: arc -> trim -> pad -> rotate -> perspective -> trim.
#    Rotation occurs before perspective; debug outputs include 02_after_arc.png, 04_after_rotation.png, 03_after_perspective.png (filenames match requested labels).
# 3) Composite warped text over background; apply paper noise. Debug output: 05_final_composited.png.
# Masks saved when DEBUG: mask_text_fill.png, mask_extrusion.png.
# Future note: warping currently applies to the combined text group; if multi-face extrusion is added later, consider warping the face mask first and rebuilding extrusion post-warp for cleaner 3D geometry.

# --- HELPERS ---

def fit_font_to_box(text, font_path, max_width, max_height):
    """
    Binary search for optimal font size.
    Safeguarded against returning None.
    """
    min_size = 50
    max_size = 800
    optimal_font = None
    last_working_font = None
    
    # Create dummy for measurements
    dummy = Image.new("L", (100, 100))
    draw = ImageDraw.Draw(dummy)

    # Attempt to load default first to ensure we have a fallback
    try:
        last_working_font = ImageFont.truetype(font_path, min_size)
    except OSError:
        print(f"Error: Font '{font_path}' not found. Using default.")
        return ImageFont.load_default()

    for _ in range(15): # 15 iterations is plenty for pixel precision
        current_size = (min_size + max_size) // 2
        try:
            font = ImageFont.truetype(font_path, current_size)
            bbox = draw.textbbox((0, 0), text, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            
            if w < max_width and h < max_height:
                last_working_font = font # Cache the last one that fit
                min_size = current_size + 1
            else:
                max_size = current_size - 1
        except OSError:
            break
            
    return last_working_font

def create_seamless_pattern(width, height, dot_color, bg_color, density=12):
    """
    Generates a seamless halftone pattern.
    Fixed: Uses correct tiling loop and avoids 'paste() returns None' bug.
    Fixed: Draws on slightly larger tile then crops to avoid edge antialias clipping.
    """
    # 1. Create a slightly larger tile to draw dots cleanly
    padding = 2
    tile_size = density * 2
    draw_size = tile_size + (padding * 2)
    
    tile = Image.new("RGBA", (draw_size, draw_size), bg_color)
    draw = ImageDraw.Draw(tile)
    dot_radius = density // 2 - 1
    
    # Helper to draw centered circle
    def draw_circle(cx, cy):
        draw.ellipse([cx - dot_radius, cy - dot_radius, 
                      cx + dot_radius, cy + dot_radius], fill=dot_color)

    # Center dot (offset by padding)
    center = tile_size / 2 + padding
    draw_circle(center, center)
    
    # Corner dots (centered on the logical corners, offset by padding)
    corners = [(padding, padding), 
               (padding + tile_size, padding), 
               (padding, padding + tile_size), 
               (padding + tile_size, padding + tile_size)]
    
    for cx, cy in corners:
        draw_circle(cx, cy)

    # Crop back to the seamless tile size
    seamless_tile = tile.crop((padding, padding, padding + tile_size, padding + tile_size))

    # 2. Tile it across the full dimensions
    # Create the full image
    full_pattern = Image.new("RGBA", (width, height))
    
    # Loop and paste
    for x in range(0, width, tile_size):
        for y in range(0, height, tile_size):
            full_pattern.paste(seamless_tile, (x, y))
            
    return full_pattern

def add_noise_and_texture(image):
    """
    Adds subtle vintage paper grain.
    Fixed: Uses blended overlay rather than raw alpha replacement.
    """
    # Generate Noise
    noise = Image.effect_noise(image.size, 20).convert("L")
    
    # Soften the noise so it's not harsh static
    noise = noise.filter(ImageFilter.GaussianBlur(radius=0.5))
    
    # Create a grain layer (Dark brown/grey)
    grain_layer = Image.new("RGBA", image.size, (100, 90, 80, 0))
    
    # Use noise as a mask, but scale intensity down
    # We want max opacity of grain to be low (e.g. 30/255)
    # So we map 0-255 noise to 0-30 opacity
    mask = noise.point(lambda p: p * 0.12) 
    
    grain_layer.putalpha(mask)
    
    # Composite over the image
    return Image.alpha_composite(image, grain_layer)

def cover_fit(image, target_width, target_height):
    """
    Resize/crop to cover the target box while retaining aspect ratio.
    """
    scale = max(target_width / image.width, target_height / image.height)
    new_size = (int(image.width * scale), int(image.height * scale))
    resized = _resize_rgba_premultiplied(image, new_size)
    
    left = (resized.width - target_width) // 2
    top = (resized.height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height))


def _resize_rgba_premultiplied(img: Image.Image, size: tuple[int, int]) -> Image.Image:
    """
    Alpha-safe resize to avoid dark halos on semi-transparent edges.
    Keeps RGB zeroed where alpha is zero to prevent matte bleed.
    """
    if img.size == size:
        return img.copy()
    if img.mode != "RGBA":
        return img.resize(size, Image.Resampling.LANCZOS)

    r, g, b, a = img.split()
    zero = Image.new("L", img.size, 0)
    r = Image.composite(r, zero, a)
    g = Image.composite(g, zero, a)
    b = Image.composite(b, zero, a)

    r = r.resize(size, Image.Resampling.LANCZOS)
    g = g.resize(size, Image.Resampling.LANCZOS)
    b = b.resize(size, Image.Resampling.LANCZOS)
    a = a.resize(size, Image.Resampling.LANCZOS)

    # Un-premultiply
    r_data, g_data, b_data, a_data = r.load(), g.load(), b.load(), a.load()
    w, h = size
    for y in range(h):
        for x in range(w):
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

def create_vignette_mask(size, strength=0.18):
    """
    Returns an 'L' mask with darker edges for a subtle vignette.
    """
    width, height = size
    mask = Image.new("L", (width, height), 0)
    pixels = mask.load()
    cx, cy = width / 2, height / 2
    max_dist = math.hypot(cx, cy)
    
    for y in range(height):
        for x in range(width):
            dist = math.hypot(x - cx, y - cy)
            factor = min(1.0, dist / max_dist)
            pixels[x, y] = int(255 * (factor ** 1.5) * strength)
    return mask

def apply_aged_treatment(background):
    """
    Mildly desaturate, lift blacks, and add a subtle vignette.
    """
    desaturated = ImageEnhance.Color(background).enhance(0.9)
    r, g, b, a = desaturated.split()

    def lift(channel):
        return channel.point(lambda p: min(255, int(p * 0.97 + 8)))

    lifted = Image.merge("RGBA", (lift(r), lift(g), lift(b), a))
    
    vignette_mask = create_vignette_mask(background.size, strength=0.16)
    vignette_overlay = Image.new("RGBA", background.size, (0, 0, 0, 70))
    vignette_overlay.putalpha(vignette_mask)
    
    return Image.alpha_composite(lifted, vignette_overlay)

def build_background_canvas(width, height, background_image):
    """
    Creates the postcard background, using an optional scenic image with aging.
    """
    base_paper = Image.new("RGBA", (width, height), (250, 248, 235, 255))

    if os.path.exists(background_image):
        try:
            bg = Image.open(background_image).convert("RGBA")
            bg = cover_fit(bg, width, height)
            return apply_aged_treatment(bg)
        except OSError:
            print(f"Warning: Could not load background '{background_image}'. Using paper fill.")

    return base_paper

def load_letter_images_from_args(args):
    """
    Loads per-letter images based on CLI options.
    """
    paths = []
    if getattr(args, "letter_images", None):
        paths.extend(args.letter_images)
    elif getattr(args, "letter_image_dir", None):
        if os.path.isdir(args.letter_image_dir):
            for name in sorted(os.listdir(args.letter_image_dir)):
                full = os.path.join(args.letter_image_dir, name)
                if os.path.isfile(full):
                    paths.append(full)

    images = []
    for p in paths:
        try:
            images.append(Image.open(p).convert("RGBA"))
        except OSError:
            print(f"Warning: could not load letter image '{p}'")
    return images

def build_perspective_arguments(width, height):
    """
    Builds perspective distortion arguments with a mild taper.
    """
    inset = int(width * PERSPECTIVE_TOP_INSET_RATIO)
    lift = int(height * PERSPECTIVE_VERTICAL_LIFT_RATIO)
    lower_lift = max(1, lift // 2)
    return (
        0, 0, inset, lift,
        width, 0, width - inset, lift,
        width, height, width, height - lower_lift,
        0, height, 0, height - lower_lift,
    )

def save_debug_image(image_path):
    """
    Keep intermediates only when debugging.
    """
    if not DEBUG and os.path.exists(image_path):
        os.remove(image_path)

def render_side_face(side_mask_only):
    """
    Builds the side face layer with optional subtle noise to avoid flat shading.
    """
    side_layer = Image.new("RGBA", side_mask_only.size, SIDE_FACE_COLOR)
    side_layer.putalpha(side_mask_only)

    if SIDE_FACE_TEXTURE_INTENSITY > 0:
        noise = Image.effect_noise(side_mask_only.size, 12).convert("L")
        noise = noise.filter(ImageFilter.GaussianBlur(radius=0.6))
        # Limit noise to the side mask so it doesn't bleed
        noise_mask = ImageChops.multiply(
            noise.point(lambda p: p * SIDE_FACE_TEXTURE_INTENSITY),
            side_mask_only
        )
        texture_overlay = Image.new("RGBA", side_mask_only.size, SIDE_FACE_COLOR)
        texture_overlay.putalpha(noise_mask)
        side_layer = Image.alpha_composite(side_layer, texture_overlay)

    return side_layer

def build_per_letter_face_layer(text, font, origin_xy, letter_images, canvas_size, fallback_mode="cycle"):
    """
    Builds a pre-warp face layer and mask using per-letter images with kerning-aware placement.
    """
    if not letter_images:
        return None, None

    origin_x, origin_y = origin_xy
    # Start with a light fill so RGB is defined anywhere the mask is present; tiles will overlay.
    face_layer = Image.new("RGBA", canvas_size, (245, 245, 245, 0))
    face_mask = Image.new("L", canvas_size, 0)
    draw_dummy = ImageDraw.Draw(Image.new("L", (1, 1), 0))

    advance = 0.0
    imgs = letter_images
    imgs_len = len(imgs)

    for idx, ch in enumerate(text):
        # Advance for kerning-aware positioning
        prefix = advance
        advance += font.getlength(ch)

        bbox = draw_dummy.textbbox((0, 0), ch, font=font)
        if not bbox:
            continue
        bw = bbox[2] - bbox[0]
        bh = bbox[3] - bbox[1]
        if bw <= 0 or bh <= 0:
            continue

        if fallback_mode == "random":
            img = random.choice(imgs)
        elif fallback_mode == "single":
            img = imgs[0]
        else:  # cycle
            img = imgs[idx % imgs_len]

        fitted = cover_fit(img.convert("RGBA"), bw, bh)

        char_mask = Image.new("L", (bw, bh), 0)
        char_draw = ImageDraw.Draw(char_mask)
        char_draw.text((-bbox[0], -bbox[1]), ch, font=font, fill=255)

        px = int(origin_x + prefix + bbox[0])
        py = int(origin_y + bbox[1])

        letter_tile = fitted.copy()
        char_mask_dilated = char_mask.filter(ImageFilter.MaxFilter(3))  # 1px-ish dilation to cover antialias edge
        letter_tile.putalpha(char_mask_dilated)
        face_layer.alpha_composite(letter_tile, dest=(px, py))
        face_mask.paste(char_mask, (px, py), char_mask)

    if DEBUG:
        try:
            face_layer.save("letter_texture_raw.png")
        except Exception:
            pass

    # Ensure the assembled face layer shares the exact mask edges used by scenery mode
    fill_mask = face_mask.filter(ImageFilter.MaxFilter(3))
    face_layer.putalpha(fill_mask)

    if DEBUG:
        try:
            face_layer.save("fill_layer_before_outline.png")
        except Exception:
            pass

    # Alpha-bleed to avoid dark seams: propagate neighboring RGB into the edge band while keeping alpha intact.
    if face_layer.getchannel("A").getextrema()[1] > 0:
        r, g, b, a = face_layer.split()
        band = ImageChops.subtract(a.filter(ImageFilter.MaxFilter(3)), a.filter(ImageFilter.MinFilter(3)))
        # Premultiply
        r_p = ImageChops.multiply(r, a)
        g_p = ImageChops.multiply(g, a)
        b_p = ImageChops.multiply(b, a)
        r_p_d = r_p.filter(ImageFilter.MaxFilter(3))
        g_p_d = g_p.filter(ImageFilter.MaxFilter(3))
        b_p_d = b_p.filter(ImageFilter.MaxFilter(3))

        def _blend_premul(orig: Image.Image, dilated: Image.Image) -> Image.Image:
            return Image.composite(dilated, orig, band)

        r_p_b = _blend_premul(r_p, r_p_d)
        g_p_b = _blend_premul(g_p, g_p_d)
        b_p_b = _blend_premul(b_p, b_p_d)

        # Un-premultiply (avoid divide by zero)
        a_data = a.load()
        r_data, g_data, b_data = r_p_b.load(), g_p_b.load(), b_p_b.load()
        w, h = face_layer.size
        r_out = Image.new("L", face_layer.size, 0)
        g_out = Image.new("L", face_layer.size, 0)
        b_out = Image.new("L", face_layer.size, 0)
        r_out_d, g_out_d, b_out_d = r_out.load(), g_out.load(), b_out.load()
        for y in range(h):
            for x in range(w):
                alpha = a_data[x, y]
                if alpha == 0:
                    r_out_d[x, y] = 0
                    g_out_d[x, y] = 0
                    b_out_d[x, y] = 0
                else:
                    r_out_d[x, y] = min(255, int(r_data[x, y] * 255 / alpha))
                    g_out_d[x, y] = min(255, int(g_data[x, y] * 255 / alpha))
                    b_out_d[x, y] = min(255, int(b_data[x, y] * 255 / alpha))

        face_layer = Image.merge("RGBA", (r_out, g_out, b_out, a))
    return face_layer, face_mask


def build_letter_texture(text, font, origin_xy, letter_images, canvas_size, fallback_mode="cycle"):
    """
    Build a single RGB texture for the whole word by placing per-letter images into their slots (cover fill).
    Masking is applied later by the shared text mask so outlines/shadows match scenery mode.
    """
    if not letter_images:
        return None
    origin_x, origin_y = origin_xy
    texture = Image.new("RGB", canvas_size, (255, 255, 255))
    draw_dummy = ImageDraw.Draw(Image.new("L", (1, 1), 0))
    advances = []
    total_adv = 0.0
    for ch in text:
        adv = max(1.0, font.getlength(ch))
        advances.append(adv)
        total_adv += adv
    if total_adv <= 0:
        return None
    imgs = letter_images
    imgs_len = len(imgs)
    offset_x = 0
    remaining_px = canvas_size[0]
    for idx, adv in enumerate(advances):
        remaining_letters = len(advances) - idx
        if idx == len(advances) - 1:
            slice_w = remaining_px
        else:
            slice_w = int(round(adv / total_adv * canvas_size[0]))
            slice_w = max(1, min(slice_w, remaining_px - (remaining_letters - 1)))
        slice_h = canvas_size[1]

        if fallback_mode == "random":
            img = random.choice(imgs)
        elif fallback_mode == "single":
            img = imgs[0]
        else:
            img = imgs[idx % imgs_len]

        img_rgb = ImageOps.exif_transpose(img).convert("RGB")
        src_w, src_h = img_rgb.size
        target_ar = slice_w / float(slice_h)
        src_ar = src_w / float(src_h)
        if src_ar > target_ar:
            new_w = int(src_h * target_ar)
            left = (src_w - new_w) // 2
            box = (left, 0, left + new_w, src_h)
        else:
            new_h = int(src_w / target_ar)
            top = (src_h - new_h) // 2
            box = (0, top, src_w, top + new_h)
        cropped = img_rgb.crop(box)
        fitted = cropped.resize((slice_w, slice_h), Image.Resampling.LANCZOS)

        texture.paste(fitted, (offset_x, origin_y))
        offset_x += slice_w
        remaining_px = max(0, canvas_size[0] - offset_x)
    if DEBUG:
        try:
            texture.save("letter_word_texture.png")
        except Exception:
            pass
    return texture


def build_letter_strip_texture(text, font, origin_xy, letter_images, bbox_size, fallback_mode="cycle"):
    """
    Build a continuous strip of letter images sized to the word bounding box.
    Each letter gets a horizontal slice proportional to its advance; slices fill the bbox with no gaps.
    """
    if not letter_images:
        return None
    text_w, text_h = bbox_size
    if text_w <= 0 or text_h <= 0:
        return None
    origin_x, origin_y = origin_xy
    strip = Image.new("RGBA", (text_w, text_h), (0, 0, 0, 0))
    advances = []
    total = 0.0
    for ch in text:
        adv = max(1.0, font.getlength(ch))
        advances.append(adv)
        total += adv
    if total <= 0:
        return None

    offset = 0
    imgs = letter_images
    imgs_len = len(imgs)
    remaining_px = text_w
    for idx, (ch, adv) in enumerate(zip(text, advances)):
        remaining_letters = len(advances) - idx
        if idx == len(advances) - 1:
            slice_w = remaining_px
        else:
            slice_w = int(round(adv / total * text_w))
            slice_w = max(1, min(slice_w, remaining_px - (remaining_letters - 1)))
        img = imgs[idx % imgs_len] if fallback_mode != "random" else random.choice(imgs)
        fitted = cover_fit(img.convert("RGBA"), slice_w, text_h)
        strip.paste(fitted, (offset, 0))
        offset += slice_w
        remaining_px = max(0, text_w - offset)
    return strip

def gradient_alpha_mask(size, top_alpha, bottom_alpha, gamma=1.3):
    """
    Returns an 'L' mask with a vertical alpha gradient (top->bottom).
    """
    w, h = size
    y = np.linspace(0.0, 1.0, num=h, dtype=np.float32)
    t = np.power(y, gamma)
    alpha = top_alpha + (bottom_alpha - top_alpha) * t
    alpha = np.clip(alpha, 0, 255).astype(np.uint8)
    mask = np.tile(alpha[:, None], (1, w))
    return Image.fromarray(mask, mode="L")

def create_halftone_gradient(width, height, mask_for_debug=None):
    """
    Builds a halftone gradient texture for the orange extrusion face.
    Darker at top/back, lighter at bottom/front, with dot size/alpha variation.
    """
    tex_size = (width, height)
    # Directional gradient following extrusion depth vector
    vx, vy = float(DEPTH_DX), float(DEPTH_DY)
    x = np.arange(width, dtype=np.float32)
    y = np.arange(height, dtype=np.float32)[:, None]
    denom = max(1.0, vx * max(1, width - 1) + vy * max(1, height - 1))
    t_dir = (x * vx + y * vy) / denom
    t_dir = np.clip(t_dir, 0.0, 1.0)
    t_dir = np.power(t_dir, ORANGE_DOT_SHADE_GAMMA)

    # Base gradient (use t_dir averaged per-row to keep base primarily vertical-ish)
    y_norm = np.linspace(0.0, 1.0, num=height, dtype=np.float32)
    y_gamma = np.power(y_norm, 1.2)

    # Base gradient
    base_top = np.array([190, 70, 40, 255], dtype=np.float32)
    base_bottom = np.array([235, 120, 65, 255], dtype=np.float32)
    lerp = y_gamma[:, None]
    base_arr = (base_top * (1 - lerp) + base_bottom * lerp).astype(np.uint8)
    base = Image.fromarray(np.tile(base_arr[None, ...], (width, 1, 1)).swapaxes(0, 1), mode="RGBA")

    # Halftone dots with varying radius/alpha, lattice rotated to extrusion direction
    dots = Image.new("RGBA", tex_size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(dots)
    pitch = max(2, ORANGE_DOT_PITCH)
    if ORANGE_DOT_ROTATE_TO_DEPTH:
        theta = math.atan2(DEPTH_DY, DEPTH_DX)
        cos_t = math.cos(theta)
        sin_t = math.sin(theta)
        cx = width * 0.5
        cy = height * 0.5
        # choose bounds for u/v large enough to cover image after rotation
        u_min = -max(width, height)
        u_max = max(width, height) + pitch
        v_min = -max(width, height)
        v_max = max(width, height) + pitch
        u_range = np.arange(u_min, u_max, pitch, dtype=np.float32)
        v_range = np.arange(v_min, v_max, pitch, dtype=np.float32)
        for v in v_range:
            for u in u_range:
                x = u * cos_t - v * sin_t
                y = u * sin_t + v * cos_t
                px = x + cx
                py = y + cy
                if px < 0 or px >= width or py < 0 or py >= height:
                    continue
                ix = int(px)
                iy = int(py)
                t = float(t_dir[iy, ix])
                radius = ORANGE_DOT_RADIUS_MAX * (1 - t) + ORANGE_DOT_RADIUS_MIN * t
                alpha = int(ORANGE_DOT_ALPHA_MAX * (1 - t) + ORANGE_DOT_ALPHA_MIN * t)
                fill = (180, 50, 30, alpha)
                draw.ellipse(
                    (
                        px - radius,
                        py - radius,
                        px + radius,
                        py + radius,
                    ),
                    fill=fill,
                )
    else:
        for yy in range(0, height + pitch, pitch):
            for xx in range(0, width + pitch, pitch):
                t = float(t_dir[min(yy, height - 1), min(xx, width - 1)])
                radius = ORANGE_DOT_RADIUS_MAX * (1 - t) + ORANGE_DOT_RADIUS_MIN * t
                alpha = int(ORANGE_DOT_ALPHA_MAX * (1 - t) + ORANGE_DOT_ALPHA_MIN * t)
                fill = (180, 50, 30, alpha)
                draw.ellipse(
                    (
                        xx - radius,
                        yy - radius,
                        xx + radius,
                        yy + radius,
                    ),
                    fill=fill,
                )

    # Slight soften to avoid harsh pixels
    dots = dots.filter(ImageFilter.GaussianBlur(radius=0.3))

    orange_texture = Image.alpha_composite(base, dots)

    if DEBUG:
        # visualize direction gradient
        grad_img = (np.clip(t_dir, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(grad_img, mode="L").save("debug_orange_gradient_t.png")
        dots.getchannel("A").save("debug_orange_dotmask_raw.png")
        base.save("debug_orange_base.png")
        dots.save("debug_orange_dotmask_modulated.png")
        orange_texture.save("debug_orange_texture.png")
        if mask_for_debug is not None:
            bbox = mask_for_debug.getbbox()
            if bbox:
                cropped = orange_texture.crop(bbox)
                cropped.save("debug_orange_face_cropped.png")

    return orange_texture

def load_script_font(size, font_path):
    try:
        return ImageFont.truetype(font_path, size)
    except OSError:
        print(f"Warning: Script font '{font_path}' not found. Using default.")
        return ImageFont.load_default()

def render_script_label(text, font_size, angle, color, stroke_color, stroke_width, shadow, script_font_path):
    """
    Renders a script label with a subtle duplicate/back layer and a front layer, rotated once.
    """
    font = load_script_font(font_size, script_font_path)
    dummy = Image.new("RGBA", (10, 10), (0, 0, 0, 0))
    draw = ImageDraw.Draw(dummy)
    bbox = draw.textbbox((0, 0), text, font=font, stroke_width=stroke_width)
    w = bbox[2] - bbox[0]
    h = bbox[3] - bbox[1]
    back_offset = max(1, int(4 * RENDER_SCALE))
    shadow_dx = abs(shadow.get("dx", 0))
    shadow_dy = abs(shadow.get("dy", 0))
    pad = stroke_width + back_offset + shadow_dx + shadow_dy + SCRIPT_SAFE_PAD + SCRIPT_DESCENDER_PAD
    img = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
    draw_img = ImageDraw.Draw(img)

    back_color = (250, 250, 245, SCRIPT_BACK_ALPHA)
    front_color = (NAVY_OUTLINE[0], NAVY_OUTLINE[1], NAVY_OUTLINE[2], 255)

    # Back/duplicate layer
    draw_img.text(
        (pad + back_offset, pad + back_offset),
        text,
        font=font,
        fill=back_color,
        stroke_width=stroke_width + SCRIPT_BACK_STROKE_EXTRA,
        stroke_fill=back_color,
    )

    # Front layer
    draw_img.text(
        (pad, pad),
        text,
        font=font,
        fill=front_color,
        stroke_width=max(1, stroke_width - 1),
        stroke_fill=stroke_color,
    )

    rotated = img.rotate(angle, expand=True)

    safe_border = max(
        SCRIPT_ROTATE_SAFE_PAD,
        int((stroke_width + back_offset + 12) * RENDER_SCALE),
    )
    out = ImageOps.expand(rotated, border=safe_border, fill=(0, 0, 0, 0))

    bbox = out.getbbox()
    if bbox:
        pad_trim = int(10 * RENDER_SCALE)
        x0 = max(0, bbox[0] - pad_trim)
        y0 = max(0, bbox[1] - pad_trim)
        x1 = min(out.width, bbox[2] + pad_trim)
        y1 = min(out.height, bbox[3] + pad_trim)
        out = out.crop((x0, y0, x1, y1))

    return out

def build_script_layer(canvas_size, placement, script_top_text, script_bottom_text, script_font_path):
    """
    Renders top/bottom script labels relative to warped text placement.
    """
    layer = Image.new("RGBA", canvas_size, (0, 0, 0, 0))
    place_x, place_y, wx, wy = placement

    top_size = int(FINAL_WIDTH * 0.065)
    bottom_size = int(FINAL_WIDTH * 0.055)

    top_angle = 0
    bottom_angle = 0

    top_img = render_script_label(
        script_top_text,
        top_size,
        top_angle,
        SCRIPT_COLOR,
        (SCRIPT_STROKE_COLOR[0], SCRIPT_STROKE_COLOR[1], SCRIPT_STROKE_COLOR[2], 255),
        max(1, SCRIPT_STROKE_WIDTH - 1),
        SCRIPT_SHADOW,
        script_font_path,
    )
    bottom_img = render_script_label(
        script_bottom_text,
        bottom_size,
        bottom_angle,
        SCRIPT_COLOR,
        (SCRIPT_STROKE_COLOR[0], SCRIPT_STROKE_COLOR[1], SCRIPT_STROKE_COLOR[2], 255),
        max(1, SCRIPT_STROKE_WIDTH - 1),
        SCRIPT_SHADOW,
        script_font_path,
    )

    # Positions (top anchored relative to block, pulled closer)
    top_pos = (
        place_x - int(wx * 0.05),
        place_y - int(wy * 0.10),
    )
    bottom_pos = (
        place_x + int(wx * 0.50),
        place_y + int(wy * 0.78),
    )

    def clamp(pos, img):
        x, y = pos
        x = max(0, min(x, canvas_size[0] - img.width))
        y = max(0, min(y, canvas_size[1] - img.height))
        return x, y

    top_pos = clamp(top_pos, top_img)
    bottom_pos = clamp(bottom_pos, bottom_img)

    layer.paste(top_img, top_pos, top_img)
    layer.paste(bottom_img, bottom_pos, bottom_img)
    if DEBUG:
        top_img.save("script_top.png")
        bottom_img.save("script_bottom.png")
    return layer

def warp_mask_only(input_path, output_path, debug_prefix=None):
    """
    Applies the configured warp (Rise-only or arc/perspective) to a single mask (RGBA/L) and outputs L.
    """
    with WandImage(filename=input_path) as img:
        img.background_color = WandColor('transparent')
        img.virtual_pixel = 'transparent'
        img.alpha_channel = 'set'

        use_rise = globals().get("USE_RISE_WARP", False)

        if use_rise:
            img = apply_rise_warp_wand(img, debug_prefix=debug_prefix, is_mask=True)

            if DEBUG and debug_prefix:
                pre_alpha = Image.open(input_path).convert("RGBA").split()[-1]
                warped_pil_alpha = Image.open(io.BytesIO(img.make_blob(format="PNG"))).convert("RGBA").split()[-1]
                warped_pil_alpha.save(f"02_after_rise_{debug_prefix}_pre_rotate.png")
                diff = ImageChops.difference(pre_alpha, warped_pil_alpha)
                diff.save(f"diff_pre_vs_post_rise_{debug_prefix}.png")

            img.trim(color=WandColor('transparent'))
            pad_dynamic = int(max(img.width, img.height) * 0.16)
            pad = max(50, pad_dynamic, EXTRUSION_DEPTH * 3 + 120)
            img.border(WandColor('transparent'), pad, pad)

            if APPLY_ROTATION:
                img.rotate(ROTATION_DEGREES)
                if DEBUG and debug_prefix:
                    img.save(filename=f"04_after_rotation_{debug_prefix}.png")
        else:
            # Arc (slightly adaptive for wide/short text)
            arc_angle = 60 if img.width <= 1800 else 55
            img.distort('arc', (arc_angle,))
            if DEBUG and debug_prefix:
                img.save(filename=f"02_after_arc_{debug_prefix}.png")

            # Trim then pad before subsequent warps
            img.trim(color=WandColor('transparent'))
            pad_dynamic = int(max(img.width, img.height) * 0.16)
            pad = max(50, pad_dynamic, EXTRUSION_DEPTH * 3 + 120)
            img.border(WandColor('transparent'), pad, pad)

            # Rotation
            img.rotate(ROTATION_DEGREES)
            if DEBUG and debug_prefix:
                img.save(filename=f"04_after_rotation_{debug_prefix}.png")

            # Perspective taper
            perspective_args = build_perspective_arguments(img.width, img.height)
            img.distort('perspective', perspective_args)
            if DEBUG and debug_prefix:
                img.save(filename=f"03_after_perspective_{debug_prefix}.png")

        # Final trim after warps
        img.trim(color=WandColor('transparent'))

        # Safety border to avoid post-warp clipping (large enough for extrusion + strokes)
        pad = EXTRUSION_DEPTH * 2 + 60
        img.border(WandColor('transparent'), pad, pad)

        img.save(filename=output_path)
        return (img.width, img.height)

def warp_rgba_only(input_path, output_path, debug_prefix=None):
    """
    Applies the configured warp (Rise-only or arc/perspective) to an RGBA image and outputs RGBA.
    """
    with WandImage(filename=input_path) as img:
        img.background_color = WandColor('transparent')
        img.virtual_pixel = 'transparent'
        img.alpha_channel = 'set'

        use_rise = globals().get("USE_RISE_WARP", False)

        if use_rise:
            img = apply_rise_warp_wand(img, debug_prefix=debug_prefix, is_mask=False)
            if DEBUG and debug_prefix:
                img.save(filename=f"02_after_rise_{debug_prefix}.png")

            img.trim(color=WandColor('transparent'))
            pad_dynamic = int(max(img.width, img.height) * 0.16)
            pad = max(50, pad_dynamic, EXTRUSION_DEPTH * 3 + 120)
            img.border(WandColor('transparent'), pad, pad)

            if APPLY_ROTATION:
                img.rotate(ROTATION_DEGREES)
                if DEBUG and debug_prefix:
                    img.save(filename=f"04_after_rotation_{debug_prefix}.png")
        else:
            arc_angle = 60 if img.width <= 1800 else 55
            img.distort('arc', (arc_angle,))
            if DEBUG and debug_prefix:
                img.save(filename=f"02_after_arc_{debug_prefix}.png")

            img.trim(color=WandColor('transparent'))
            pad_dynamic = int(max(img.width, img.height) * 0.16)
            pad = max(50, pad_dynamic, EXTRUSION_DEPTH * 3 + 120)
            img.border(WandColor('transparent'), pad, pad)

            img.rotate(ROTATION_DEGREES)
            if DEBUG and debug_prefix:
                img.save(filename=f"04_after_rotation_{debug_prefix}.png")

            perspective_args = build_perspective_arguments(img.width, img.height)
            img.distort('perspective', perspective_args)
            if DEBUG and debug_prefix:
                img.save(filename=f"03_after_perspective_{debug_prefix}.png")

        img.trim(color=WandColor('transparent'))

        pad = EXTRUSION_DEPTH * 2 + 60
        img.border(WandColor('transparent'), pad, pad)

        img.save(filename=output_path)
        return (img.width, img.height)

def shift_mask_no_wrap(mask, dx, dy):
    """
    Translate mask by (dx, dy) with zero fill (no wraparound).
    """
    width, height = mask.size
    shifted = Image.new("L", (width, height), 0)

    src_x0 = max(0, -dx)
    src_y0 = max(0, -dy)
    src_x1 = min(width, width - dx)  # exclusive
    src_y1 = min(height, height - dy)

    if src_x0 >= src_x1 or src_y0 >= src_y1:
        return shifted

    crop = mask.crop((src_x0, src_y0, src_x1, src_y1))
    shifted.paste(crop, (src_x0 + dx, src_y0 + dy))
    return shifted

def dilate_mask(mask, radius_px):
    ksize = radius_px * 2 + 1
    if ksize < 1:
        ksize = 1
    if ksize % 2 == 0:
        ksize += 1
    return mask.filter(ImageFilter.MaxFilter(ksize))

def close_mask(mask, radius_px):
    """
    Morphological closing: dilate then erode to fill small pinholes/stripes.
    """
    ksize = radius_px * 2 + 1
    if ksize < 1:
        ksize = 1
    if ksize % 2 == 0:
        ksize += 1
    dilated = mask.filter(ImageFilter.MaxFilter(ksize))
    closed = dilated.filter(ImageFilter.MinFilter(ksize))
    return closed.point(lambda p: 255 if p > 0 else 0)

def wand_dilate_mask(pil_mask, radius):
    """
    Uses Wand/ImageMagick disk dilation for isotropic stroke expansion.
    """
    if radius <= 0:
        return pil_mask.copy()
    buf = io.BytesIO()
    pil_mask.save(buf, format="PNG")
    buf.seek(0)
    with WandImage(blob=buf.getvalue()) as img:
        img.morphology(method='dilate', kernel=f'Disk:{int(radius)}')
        out = Image.open(io.BytesIO(img.make_blob(format='PNG'))).convert("L")
    return out

def apply_rise_remap_numpy(pil_img, is_mask=False):
    """
    Deprecated: replaced by apply_rise_envelope_pil displacement warp.
    """
    return apply_rise_envelope_pil(pil_img, is_mask=is_mask)

def apply_rise_envelope_pil(pil_img, is_mask=False):
    """
    Smooth Rise warp using per-column vertical displacement (translation), no mesh seams.
    Uses separate top/bottom curves to emulate an Illustrator-like envelope with shoulders.
    """
    w0, h0 = pil_img.size
    if w0 <= 1 or h0 <= 1:
        return pil_img

    bend_pct = globals().get("RISE_BEND_PCT", 0) or 0
    if bend_pct == 0:
        return pil_img

    amp_factor = globals().get("RISE_AMPLITUDE_FACTOR", 0.25)
    amplitude = (bend_pct / 100.0) * amp_factor * h0
    if amplitude == 0:
        return pil_img

    pad = int(abs(amplitude) + 4)
    fill = 0 if pil_img.mode in ("L", "1") else (0, 0, 0, 0)
    pil_img = ImageOps.expand(pil_img, border=pad, fill=fill)
    w, h = pil_img.size

    x = np.linspace(0.0, 1.0, num=w, dtype=np.float32)
    def make_curve(xn, m, phase, gamma):
        base = np.sin(np.pi * xn + phase)
        shoulder = 1.0 + m * np.cos(2.0 * np.pi * xn + phase)
        shape = base * shoulder
        shape = np.clip(shape, 0.0, None)
        maxv = np.max(shape)
        if maxv < 1e-6:
            t = np.zeros_like(shape)
        else:
            t = shape / maxv
        t = np.clip(t, 0.0, 1.0)
        t = np.power(t, gamma, dtype=np.float32)
        return np.nan_to_num(t, nan=0.0, posinf=0.0, neginf=0.0)

    t_top = make_curve(
        x,
        globals().get("RISE_TOP_M", 0.45),
        globals().get("RISE_TOP_PHASE", 0.0),
        globals().get("RISE_TOP_GAMMA", 1.35),
    )
    t_bottom = make_curve(
        x,
        globals().get("RISE_BOTTOM_M", 0.25),
        globals().get("RISE_BOTTOM_PHASE", 0.0),
        globals().get("RISE_BOTTOM_GAMMA", 1.15),
    )

    baseline = (0.5 - x) * float(RISE_SLOPE_PX)
    dy_top = baseline + (-amplitude * t_top)
    dy_bottom = baseline + (-amplitude * 0.8 * t_bottom)  # slightly gentler on bottom

    y = np.arange(h, dtype=np.float32)[:, None]
    ty = y / max(1.0, (h - 1))
    dy_row = (1.0 - ty) * dy_top[None, :] + ty * dy_bottom[None, :]
    y_src = y - dy_row
    y_src = np.clip(y_src, 0.0, h - 1.0)

    y0 = np.floor(y_src).astype(np.int32)
    y1 = np.clip(y0 + 1, 0, h - 1)
    t_y = (y_src - y0).astype(np.float32)

    cols = np.arange(w, dtype=np.int32)

    if is_mask:
        src = np.array(pil_img, dtype=np.float32)
        src0 = src[y0, cols]
        src1 = src[y1, cols]
        out = (1.0 - t_y) * src0 + t_y * src1
        out = np.clip(out, 0, 255).astype(np.uint8)
        warped = Image.fromarray(out, mode="L")
    else:
        src = np.array(pil_img, dtype=np.float32)
        src0 = src[y0, cols]
        src1 = src[y1, cols]
        t_exp = t_y[..., None]
        out = (1.0 - t_exp) * src0 + t_exp * src1
        out = np.clip(out, 0, 255).astype(np.uint8)
        warped = Image.fromarray(out, mode="RGBA")

    if DEBUG and is_mask:
        dy_top_norm = (np.clip(t_top, 0, 1) * 255).astype(np.uint8)
        dy_bottom_norm = (np.clip(t_bottom, 0, 1) * 255).astype(np.uint8)
        Image.fromarray(np.tile(dy_top_norm, (40, 1)), mode="L").save("debug_dy_top.png")
        Image.fromarray(np.tile(dy_bottom_norm, (40, 1)), mode="L").save("debug_dy_bottom.png")
        warped.save("debug_warped_alpha_prebin.png")

    return warped

def apply_rise_warp_wand(img, debug_prefix=None, is_mask=False):
    """
    Applies a shepards-based 'Rise' warp similar to Illustrator's Envelope Distort.
    Uses existing global rise controls if present, otherwise skips.
    """
    use_rise = globals().get("USE_RISE_WARP", False)
    if not use_rise:
        return img

    # Convert to PIL for smooth envelope warp, then back to Wand
    pil_img = Image.open(io.BytesIO(img.make_blob(format="PNG"))).convert("RGBA")
    if is_mask:
        pil_a = pil_img.split()[-1]
        warped_a = apply_rise_envelope_pil(pil_a, is_mask=True)
        warped_pil = Image.merge("RGBA", (warped_a, warped_a, warped_a, warped_a))
    else:
        warped_pil = apply_rise_envelope_pil(pil_img, is_mask=False)

    if DEBUG and debug_prefix:
        warped_pil.save(f"02_after_rise_{debug_prefix}.png")

    buf = io.BytesIO()
    warped_pil.save(buf, format="PNG")
    buf.seek(0)
    out = WandImage(blob=buf.getvalue())
    out.background_color = WandColor('transparent')
    out.virtual_pixel = 'transparent'
    out.alpha_channel = 'set'
    return out

# --- PIPELINE ---

def render_postcard_image(cfg: "PostcardConfig", letter_images=None) -> Image.Image:
    """
    Entry point that renders a postcard using provided configuration values.
    """
    return generate_postcard(
        letter_images=letter_images,
        letter_fallback=getattr(cfg, "letter_image_fallback", None),
        text=getattr(cfg, "text", TEXT),
        script_top_text=getattr(cfg, "script_top_text", SCRIPT_TOP_TEXT),
        script_bottom_text=getattr(cfg, "script_bottom_text", SCRIPT_BOTTOM_TEXT),
        impact_font_path=str(getattr(cfg, "impact_font_path", FONT_PATH)),
        script_font_path=str(getattr(cfg, "script_font_path", SCRIPT_FONT_PATH)),
        scenery_image=str(getattr(cfg, "scenery_image", SCENERY_IMAGE)),
        background_image=str(getattr(cfg, "background_image", BACKGROUND_IMAGE)),
        output_filename=getattr(cfg, "output_filename", OUTPUT_FILENAME),
    )

def generate_postcard(
    letter_images=None,
    letter_fallback=None,
    *,
    text=TEXT,
    script_top_text=SCRIPT_TOP_TEXT,
    script_bottom_text=SCRIPT_BOTTOM_TEXT,
    impact_font_path=FONT_PATH,
    script_font_path=SCRIPT_FONT_PATH,
    scenery_image=SCENERY_IMAGE,
    background_image=BACKGROUND_IMAGE,
    output_filename=OUTPUT_FILENAME,
):
    print("1. Generating Text Component...")
    
    # Setup Text Asset Canvas (Transparent)
    txt_canvas = Image.new("RGBA", (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT), (0,0,0,0))
    
    # Font Loading
    font = fit_font_to_box(text, impact_font_path, TEMP_TEXT_WIDTH * 0.85, TEMP_TEXT_HEIGHT * 0.6)
    
    # Get Metrics
    draw_temp = ImageDraw.Draw(txt_canvas)
    bbox = draw_temp.textbbox((0, 0), text, font=font)
    text_w, text_h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    
    # Center Coordinates
    x = (TEMP_TEXT_WIDTH - text_w) // 2
    y = (TEMP_TEXT_HEIGHT - text_h) // 2

    # Prepare face mask once
    text_mask = Image.new("L", (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT), 0)
    draw_tm = ImageDraw.Draw(text_mask)
    draw_tm.text((x, y), text, font=font, fill=255)

    # --- A. The Main Face (Scenery Fill or Per-letter fill) ---
    use_letter_images = letter_images is not None and len(letter_images) > 0
    fallback_mode = letter_fallback or LETTER_IMAGE_FALLBACK

    if use_letter_images:
        face_layer, face_mask_custom = build_per_letter_face_layer(
            text,
            font,
            (x, y),
            letter_images,
            (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT),
            fallback_mode,
        )
        if face_layer is not None and face_mask_custom is not None:
            text_mask = face_mask_custom
            face_layer.save("temp_face_texture.png")
    else:
        face_layer = None

    if face_layer is None:
        print("   - Rendering Scenery Fill...")
        try:
            scenery = Image.open(scenery_image).convert("RGBA")
            sc_aspect = scenery.width / scenery.height
            tx_aspect = text_w / text_h
            
            if sc_aspect > tx_aspect:
                new_h = int(text_h * 1.1)
                new_w = int(new_h * sc_aspect)
            else:
                new_w = int(text_w * 1.1)
                new_h = int(new_w / sc_aspect)
                
            scenery = scenery.resize((new_w, new_h), Image.Resampling.LANCZOS)
            
            scenery_layer = Image.new("RGBA", (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT), (0,0,0,0))
            paste_x = x - (new_w - text_w) // 2
            paste_y = y - (new_h - text_h) // 2
            scenery_layer.paste(scenery, (paste_x, paste_y))
            
        except FileNotFoundError:
            print("Warning: Scenery image not found. Using blue fill.")
            scenery_layer = Image.new("RGBA", (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT), (50,100,200,255))

        face_layer = Image.new("RGBA", (TEMP_TEXT_WIDTH, TEMP_TEXT_HEIGHT), (0,0,0,0))
        face_layer.paste(scenery_layer, (0,0), mask=text_mask)

    # Pre-warp mask
    mask_rgba = Image.merge("RGBA", (text_mask, text_mask, text_mask, text_mask))
    mask_rgba.save("temp_face_mask.png")
    if DEBUG:
        text_mask.save("mask_text_fill.png")

    # --- Step 2: Warp mask only (Wand) ---
    print("2. Warping Mask...")
    try:
        warp_mask_only("temp_face_mask.png", "temp_warped_face_mask.png", debug_prefix="mask")
    except Exception as e:
        print(f"Error Wand/ImageMagick: {e}")
        return

    warped_face_mask = Image.open("temp_warped_face_mask.png").convert("RGBA").split()[-1]
    pad_left = BLACK_STROKE_PX + 30
    pad_top = BLACK_STROKE_PX + 30
    pad_right = EXTRUSION_DEPTH * DEPTH_DX + BLACK_STROKE_PX + 30
    pad_bottom = EXTRUSION_DEPTH * DEPTH_DY + BLACK_STROKE_PX + 30
    warped_mask_padded = ImageOps.expand(warped_face_mask, border=(pad_left, pad_top, pad_right, pad_bottom), fill=0)
    face_binary = warped_mask_padded.filter(ImageFilter.GaussianBlur(0.4)).point(lambda p: 255 if p > 16 else 0)
    face_binary = face_binary.filter(ImageFilter.MaxFilter(3))
    if DEBUG:
        warped_mask_padded.save("warped_mask_L_padded.png")
        face_binary.save("face_binary_padded.png")
        face_binary.save("warped_face_mask_bin.png")

    # Rebuild face layer from warped mask
    if use_letter_images and face_layer is not None:
        warp_rgba_only("temp_face_texture.png", "temp_warped_face_texture.png", debug_prefix="face_tex")
        warped_texture = Image.open("temp_warped_face_texture.png").convert("RGBA")
        warped_texture = ImageOps.expand(
            warped_texture,
            border=(pad_left, pad_top, pad_right, pad_bottom),
            fill=(0, 0, 0, 0),
        )
        if warped_texture.size != face_binary.size:
            tex_canvas = Image.new("RGBA", face_binary.size, (0, 0, 0, 0))
            offset = ((face_binary.size[0] - warped_texture.size[0]) // 2,
                      (face_binary.size[1] - warped_texture.size[1]) // 2)
            tex_canvas.paste(warped_texture, offset)
            warped_texture = tex_canvas
        face_layer = Image.new("RGBA", face_binary.size, (0, 0, 0, 0))
        face_layer.paste(warped_texture, (0, 0), mask=face_binary)
        if DEBUG:
            warped_texture.save("temp_warped_face_texture.png")
    else:
        try:
            scenery = Image.open(scenery_image).convert("RGBA")
            scenery = cover_fit(scenery, face_binary.size[0], face_binary.size[1])
        except FileNotFoundError:
            scenery = Image.new("RGBA", face_binary.size, (50,100,200,255))
        face_layer = Image.new("RGBA", face_binary.size, (0,0,0,0))
        face_layer.paste(scenery, (0,0), mask=face_binary)
        if DEBUG:
            face_layer.save("layer_face.png")

    # Rebuild strokes from warped mask (isotropic disk dilation via Wand)
    d1 = wand_dilate_mask(face_binary, WHITE_STROKE_PX)
    d2 = wand_dilate_mask(face_binary, BLACK_STROKE_PX)
    white_ring = ImageChops.subtract(d1, face_binary).point(lambda p: 255 if p > 0 else 0)
    black_ring = ImageChops.subtract(d2, d1).point(lambda p: 255 if p > 0 else 0)

    white_stroke_layer = Image.new("RGBA", face_binary.size, (255,255,255,0))
    white_stroke_layer.putalpha(white_ring)
    black_stroke_layer = Image.new("RGBA", face_binary.size, NAVY_OUTLINE)
    black_stroke_layer.putalpha(black_ring)

    top_group = Image.new("RGBA", face_binary.size, (0,0,0,0))
    top_group = Image.alpha_composite(top_group, black_stroke_layer)
    top_group = Image.alpha_composite(top_group, white_stroke_layer)
    top_group = Image.alpha_composite(top_group, face_layer)
    top_alpha = top_group.split()[-1]
    top_alpha_bin = top_alpha.point(lambda p: 255 if p > 16 else 0)

    if DEBUG:
        white_ring.save("mask_white_ring.png")
        black_ring.save("mask_black_ring.png")
        white_stroke_layer.save("layer_white_stroke.png")
        black_stroke_layer.save("layer_black_stroke.png")

    # --- C. Build extrusion faces from volume rims ---
    extrusion_depth = EXTRUSION_DEPTH

    # Build volume by sweeping the face mask down-right
    volume = Image.new("L", face_binary.size, 0)
    for i in range(0, extrusion_depth + 1):
        volume = ImageChops.lighter(volume, shift_mask_no_wrap(face_binary, DEPTH_DX * i, DEPTH_DY * i))
    volume = volume.point(lambda p: 255 if p > 0 else 0)
    volume_only = ImageChops.subtract(volume, face_binary).point(lambda p: 255 if p > 0 else 0)

    # Rims of the volume
    bottom_rim = ImageChops.subtract(volume, shift_mask_no_wrap(volume, 0, -1)).point(lambda p: 255 if p > 0 else 0)
    right_rim = ImageChops.subtract(volume, shift_mask_no_wrap(volume, -1, 0)).point(lambda p: 255 if p > 0 else 0)

    # Sweep rims back toward the face
    bottom_surface = Image.new("L", face_binary.size, 0)
    side_surface = Image.new("L", face_binary.size, 0)
    for i in range(0, extrusion_depth + 1):
        dx = -DEPTH_DX * i
        dy = -DEPTH_DY * i
        bottom_surface = ImageChops.lighter(bottom_surface, shift_mask_no_wrap(bottom_rim, dx, dy))
        side_surface = ImageChops.lighter(side_surface, shift_mask_no_wrap(right_rim, dx, dy))

    # Clamp to extrusion volume only
    bottom_surface = ImageChops.multiply(bottom_surface.point(lambda p: 255 if p > 0 else 0), volume_only).point(lambda p: 255 if p > 0 else 0)
    side_surface = ImageChops.multiply(side_surface.point(lambda p: 255 if p > 0 else 0), volume_only).point(lambda p: 255 if p > 0 else 0)

    # Resolve overlap: bottom wins
    side_surface = ImageChops.subtract(side_surface, bottom_surface).point(lambda p: 255 if p > 0 else 0)

    # Light cleanup
    bottom_only = close_mask(bottom_surface, 2)
    side_only = close_mask(side_surface, 2)

    guard = wand_dilate_mask(face_binary, GUARD_PX).point(lambda p: 255 if p > 0 else 0)
    bottom_only = ImageChops.subtract(bottom_only, guard).point(lambda p: 255 if p > 0 else 0)
    side_only = ImageChops.subtract(side_only, guard).point(lambda p: 255 if p > 0 else 0)

    occluder = wand_dilate_mask(top_alpha_bin, OCCLUDE_PX).point(lambda p: 255 if p > 0 else 0)

    bottom_only = ImageChops.subtract(bottom_only, occluder).point(lambda p: 255 if p > 0 else 0)
    side_only = ImageChops.subtract(side_only, occluder).point(lambda p: 255 if p > 0 else 0)

    # Ensure bottom (orange) never intrudes where side face exists
    side_guard = wand_dilate_mask(side_only, max(3, int(2 * RENDER_SCALE))).point(lambda p: 255 if p > 0 else 0)
    bottom_only = ImageChops.subtract(bottom_only, side_guard).point(lambda p: 255 if p > 0 else 0)
    bottom_only = close_mask(bottom_only, 1)

    extrusion_mask = ImageChops.lighter(bottom_only, side_only).point(lambda p: 255 if p > 0 else 0)
    seam_px = max(2, int(3 * RENDER_SCALE))
    extr_dil = wand_dilate_mask(extrusion_mask, seam_px).point(lambda p: 255 if p > 0 else 0)
    extr_ring = ImageChops.subtract(extr_dil, extrusion_mask).point(lambda p: 255 if p > 0 else 0)
    extr_ring = ImageChops.multiply(extr_ring, top_alpha_bin).point(lambda p: 255 if p > 0 else 0)

    navy_seam_layer = Image.new("RGBA", face_binary.size, NAVY_OUTLINE)
    navy_seam_layer.putalpha(extr_ring)

    if DEBUG:
        volume.save("mask_volume.png")
        volume_only.save("mask_volume_only.png")
        bottom_rim.save("mask_bottom_rim.png")
        right_rim.save("mask_right_rim.png")
        bottom_surface.save("mask_bottom_surface.png")
        side_surface.save("mask_side_surface.png")
        bottom_only.save("mask_bottom_only.png")
        side_only.save("mask_side_only.png")
        top_alpha_bin.save("top_alpha_bin.png")
        occluder.save("occluder.png")
        bottom_only.save("bottom_only_after_occlusion.png")
        side_only.save("side_only_after_occlusion.png")

    # --- D. Render extrusion faces ---
    tex_size = face_layer.size
    orange_texture = create_halftone_gradient(tex_size[0], tex_size[1], mask_for_debug=bottom_only if DEBUG else None)

    bottom_face_layer = Image.new("RGBA", tex_size, (0,0,0,0))
    bottom_face_layer.paste(orange_texture, (0,0), mask=bottom_only)

    side_face_layer = render_side_face(side_only)

    if DEBUG:
        side_face_layer.save("layer_side_face.png")
        bottom_face_layer.save("layer_bottom_face.png")

    # --- E. Keyline and stack warped components ---
    text_group = Image.new("RGBA", face_binary.size, (0,0,0,0))
    text_group = Image.alpha_composite(text_group, bottom_face_layer)
    text_group = Image.alpha_composite(text_group, side_face_layer)
    text_group = Image.alpha_composite(text_group, navy_seam_layer)
    text_group = Image.alpha_composite(text_group, top_group)
    
    # Outer navy stroke around full text group (before shadow)
    group_alpha = text_group.split()[-1]
    group_alpha_bin = group_alpha.point(lambda p: 255 if p > 128 else 0)
    outer_dilated = wand_dilate_mask(group_alpha_bin, OUTER_STROKE_PX).point(lambda p: 255 if p > 0 else 0)
    outer_ring_mask = ImageChops.subtract(outer_dilated, group_alpha_bin).point(lambda p: 255 if p > 0 else 0)
    outer_ring_layer = Image.new("RGBA", text_group.size, NAVY_OUTLINE)
    outer_ring_layer.putalpha(outer_ring_mask)
    text_group = Image.alpha_composite(outer_ring_layer, text_group)
    if DEBUG:
        outer_ring_mask.save("outer_ring_mask.png")
        outer_ring_layer.save("outer_ring_layer.png")
    
    # Soft shadow
    shadow_mask = text_group.split()[-1].filter(ImageFilter.GaussianBlur(SHADOW_BLUR))
    shadow_layer = Image.new("RGBA", text_group.size, SHADOW_COLOR)
    shadow_layer.putalpha(shadow_mask)
    shadow_canvas = Image.new("RGBA", text_group.size, (0,0,0,0))
    shadow_canvas.paste(shadow_layer, SHADOW_OFFSET)
    text_group = Image.alpha_composite(shadow_canvas, text_group)
    
    margin = max(40, int(EXTRUSION_DEPTH * 1.2))
    text_group = ImageOps.expand(text_group, border=margin, fill=(0,0,0,0))
    
    text_group.save("temp_warped_group.png")

    # --- Step 3: Final Composition ---
    print("3. Composing Final Postcard...")
    
    final_bg = build_background_canvas(FINAL_WIDTH, FINAL_HEIGHT, background_image)
    warped_text = Image.open("temp_warped_group.png").convert("RGBA")
    
    # Center on Final Canvas
    wx, wy = warped_text.size
    place_x = (FINAL_WIDTH - wx) // 2
    place_y = (FINAL_HEIGHT - wy) // 2
    placement = (place_x, place_y, wx, wy)

    # Script layer (under block text)
    script_layer = build_script_layer(
        (FINAL_WIDTH, FINAL_HEIGHT),
        placement,
        script_top_text,
        script_bottom_text,
        script_font_path,
    )
    if DEBUG:
        script_layer.save("script_layer.png")

    final_bg = Image.alpha_composite(final_bg, script_layer)

    # Paste warped text over scripts
    final_bg.paste(warped_text, (place_x, place_y), warped_text)
    
    # --- Step 4: Finishing Touches ---
    print("4. Applying Vintage Textures...")
    final_result = add_noise_and_texture(final_bg)
    final_result_down = final_result.resize((BASE_FINAL_WIDTH, BASE_FINAL_HEIGHT), Image.Resampling.LANCZOS)
    
    final_result_down.save(output_filename)
    if DEBUG:
        final_result_down.save("final_with_script.png")
        final_result_down.save("05_final_composited.png")
    print(f"Done! Saved to {output_filename}")
    return final_result_down
    
    # Cleanup
    debug_artifacts = os.getenv("PHOTOBOOK_DEBUG_ARTIFACTS", "0") == "1"
    if not DEBUG and not debug_artifacts:
        for path in [
            "temp_warped_group.png",
            "02_after_arc.png",
            "03_after_perspective.png",
            "04_after_rotation.png",
            "02_after_arc_face.png",
            "03_after_perspective_face.png",
            "04_after_rotation_face.png",
            "temp_face_layer.png",
            "temp_stroke_layer.png",
            "temp_face_mask.png",
            "temp_warped_face_mask.png",
            "01_text_group_prewarp.png",
            "layer_side_face.png",
            "layer_bottom_face.png",
            "mask_text_fill.png",
            "mask_bottom_only.png",
            "mask_side_only.png",
            "mask_volume.png",
            "mask_volume_only.png",
            "mask_bottom_rim.png",
            "mask_right_rim.png",
            "mask_bottom_surface.png",
            "mask_side_surface.png",
            "outer_ring_mask.png",
            "outer_ring_layer.png",
            "bottom_slab_thin.png",
            "side_slab_thin.png",
            "slab_bottom.png",
            "slab_side.png",
            "mask_bottom_only.png",
            "mask_side_only.png",
            "warped_mask_L_padded.png",
            "face_binary_padded.png",
            "corner_seed.png",
            "corner_slab.png",
            "05_final_composited.png",
            "script_layer.png",
            "final_with_script.png",
        ]:
            save_debug_image(path)

if __name__ == "__main__":
    from postcard_renderer.cli import main

    main()
