import argparse
import sys
from typing import Optional

from . import defaults
from .engine import load_letter_images_from_args
from .renderer import PostcardConfig, render_postcard


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Generate vintage postcard graphic.")
    parser.add_argument("--text", default=defaults.TEXT, help="Main block text.")
    parser.add_argument("--script-top", default=defaults.SCRIPT_TOP_TEXT, help="Top script text.")
    parser.add_argument("--script-bottom", default=defaults.SCRIPT_BOTTOM_TEXT, help="Bottom script text.")
    parser.add_argument("--font-path", default=str(defaults.FONT_PATH), help="Path to block font.")
    parser.add_argument("--scenery-image", default=str(defaults.SCENERY_IMAGE), help="Path to scenery image.")
    parser.add_argument("--background-image", default=str(defaults.BACKGROUND_IMAGE), help="Path to optional background image.")
    parser.add_argument("--out", default=defaults.OUTPUT_FILENAME, help="Output filename.")
    parser.add_argument("--letter-images", nargs="+", help="List of per-letter images, left-to-right.")
    parser.add_argument("--letter-image-dir", help="Directory of per-letter images (sorted).")
    parser.add_argument(
        "--letter-image-fallback",
        choices=["cycle", "random", "single"],
        default=defaults.LETTER_IMAGE_FALLBACK,
        help="Fallback strategy if fewer images than letters.",
    )
    return parser


def main(argv: Optional[list[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    letter_imgs = load_letter_images_from_args(args)

    config = PostcardConfig(
        text=args.text,
        script_top_text=args.script_top,
        script_bottom_text=args.script_bottom,
        font_path=args.font_path,
        impact_font_path=args.font_path,
        scenery_image=args.scenery_image,
        background_image=args.background_image,
        output_filename=args.out,
        letter_image_fallback=args.letter_image_fallback,
    )

    render_postcard(config, letter_images=letter_imgs if letter_imgs else None)
    print(f"Wrote {config.output_filename}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
