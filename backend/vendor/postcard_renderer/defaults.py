from pathlib import Path

# Base asset locations within the package
PACKAGE_DIR = Path(__file__).resolve().parent
ASSETS_DIR = PACKAGE_DIR / "assets"
FONTS_DIR = ASSETS_DIR / "fonts"
IMAGES_DIR = ASSETS_DIR / "images"

# Default postcard content
TEXT = "NARNIA"
SCRIPT_TOP_TEXT = "Greetings from"
SCRIPT_BOTTOM_TEXT = "Kingdom of Aslan"
OUTPUT_FILENAME = "vintage_postcard_final.png"
LETTER_IMAGE_FALLBACK = "cycle"  # options: cycle, random, single

# Default asset paths
FONT_PATH = FONTS_DIR / "Impact.ttf"
SCRIPT_FONT_PATH = FONTS_DIR / "Pacifico-Regular.ttf"
SCENERY_IMAGE = IMAGES_DIR / "scenery.jpg"
BACKGROUND_IMAGE = IMAGES_DIR / "background.jpg"
