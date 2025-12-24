import dataclasses
from typing import List, Optional

from PIL import Image

from . import defaults, engine


@dataclasses.dataclass
class PostcardConfig:
    text: str = defaults.TEXT
    script_top_text: str = defaults.SCRIPT_TOP_TEXT
    script_bottom_text: str = defaults.SCRIPT_BOTTOM_TEXT
    font_path: Optional[str] = None
    impact_font_path: str = str(defaults.FONT_PATH)
    script_font_path: str = str(defaults.SCRIPT_FONT_PATH)
    scenery_image: str = str(defaults.SCENERY_IMAGE)
    background_image: str = str(defaults.BACKGROUND_IMAGE)
    output_filename: str = defaults.OUTPUT_FILENAME
    letter_image_fallback: str = defaults.LETTER_IMAGE_FALLBACK

    def __post_init__(self) -> None:
        if self.font_path:
            self.impact_font_path = self.font_path
        self.font_path = self.impact_font_path


def render_postcard(
    config: PostcardConfig,
    letter_images: Optional[List[Image.Image]] = None,
) -> Image.Image:
    """
    Render the postcard using the existing pipeline while allowing configurable text/images.
    """
    return engine.render_postcard_image(
        cfg=config,
        letter_images=letter_images if letter_images else None,
    )
