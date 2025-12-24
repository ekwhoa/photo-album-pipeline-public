from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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
