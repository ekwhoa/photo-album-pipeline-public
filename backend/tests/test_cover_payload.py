from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter

from domain.models import Asset, AssetStatus, AssetType, Book, BookSize, LayoutRect, PageLayout, PageType, RenderContext
from services.cover_postcard import ensure_cover_asset, generate_composited_cover


def _make_img(path: Path, color: tuple[int, int, int] = (200, 200, 200)) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (400, 400), color).save(path, format="PNG")


def _luminance_mean(img: Image.Image) -> float:
    rgb = img.convert("RGB")
    pixels = list(rgb.getdata())
    total = 0.0
    for r, g, b in pixels:
        total += 0.2126 * r + 0.7152 * g + 0.0722 * b
    return total / len(pixels)


def test_ensure_cover_asset_enhanced_wires_layout(monkeypatch, tmp_path):
    def fake_generate_postcard_cover(spec, debug_dir=None):
        _make_img(Path(spec.out_path), (50, 150, 200))

    def fake_generate_composited_cover(postcard_path, out_path, **_):
        _make_img(Path(out_path), (20, 20, 20))

    monkeypatch.setattr("services.cover_postcard.generate_postcard_cover", fake_generate_postcard_cover)
    monkeypatch.setattr("services.cover_postcard.generate_composited_cover", fake_generate_composited_cover)

    book = Book(id="b1", title="Book Title", size=BookSize.SQUARE_8)
    layouts = [PageLayout(page_index=0, page_type=PageType.FRONT_COVER, elements=[], payload={"title": "Book Title", "date_range": "2024"})]
    assets: dict[str, Asset] = {}
    context = RenderContext(book_size=BookSize.SQUARE_8)

    output_path = tmp_path / "book.pdf"
    media_root = str(tmp_path)

    asset_id = ensure_cover_asset(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root=media_root,
        output_path=str(output_path),
        cover_style_env="enhanced",
    )

    assert asset_id.startswith("cover_front_composite_")
    assert asset_id in assets
    assert "cover_front_composite" in assets[asset_id].file_path
    front_cover = layouts[0]
    assert len(front_cover.elements) == 1
    assert isinstance(front_cover.elements[0], LayoutRect)
    assert front_cover.elements[0].asset_id == asset_id
    assert front_cover.payload.get("cover_style") == "enhanced"
    assert Path(tmp_path / assets[asset_id].file_path).exists()


def test_ensure_cover_asset_fallbacks_to_classic(monkeypatch, tmp_path):
    def fake_generate_postcard_cover(spec, debug_dir=None):
        _make_img(Path(spec.out_path), (120, 120, 120))

    def fake_generate_composited_cover(*_, **__):
        raise RuntimeError("boom")

    monkeypatch.setattr("services.cover_postcard.generate_postcard_cover", fake_generate_postcard_cover)
    monkeypatch.setattr("services.cover_postcard.generate_composited_cover", fake_generate_composited_cover)

    book = Book(id="b2", title="Book Title", size=BookSize.SQUARE_8)
    layouts = [PageLayout(page_index=0, page_type=PageType.FRONT_COVER, elements=[], payload={"title": "Book Title", "date_range": "2024"})]
    assets: dict[str, Asset] = {}
    context = RenderContext(book_size=BookSize.SQUARE_8)

    output_path = tmp_path / "book.pdf"
    media_root = str(tmp_path)

    asset_id = ensure_cover_asset(
        book=book,
        layouts=layouts,
        assets=assets,
        context=context,
        media_root=media_root,
        output_path=str(output_path),
        cover_style_env="enhanced",
    )

    assert asset_id.startswith("cover_postcard")
    assert asset_id in assets
    assert layouts[0].payload.get("cover_style") == "classic"
    assert Path(tmp_path / assets[asset_id].file_path).exists()


def test_generate_composited_cover_smoke(tmp_path):
    base = tmp_path / "cover_postcard.png"
    composite = tmp_path / "cover_front_composite.png"
    texture = tmp_path / "texture.jpg"
    Image.new("RGB", (1800, 1200), (230, 225, 210)).save(texture, format="JPEG")
    Image.new("RGBA", (2000, 1400), (240, 240, 240, 255)).save(base, format="PNG")

    generate_composited_cover(
        postcard_path=base,
        out_path=composite,
        texture_path=texture,
        rotate_deg=-7.0,
        inset_frac=0.1,
    )

    assert composite.exists()
    assert composite.stat().st_size > 1000


def test_composite_preserves_shadow(tmp_path):
    base = tmp_path / "cover_postcard.png"
    composite = tmp_path / "cover_front_composite.png"
    texture = tmp_path / "texture.jpg"
    debug_dir = tmp_path / "debug"

    # Build a postcard with a dark drop shadow on opaque background
    postcard = Image.new("RGBA", (400, 300), (245, 245, 245, 255))
    shadow = Image.new("RGBA", postcard.size, (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rectangle((120, 120, 280, 180), fill=(0, 0, 0, 200))
    shadow = shadow.filter(ImageFilter.GaussianBlur(radius=6))
    postcard = Image.alpha_composite(postcard, shadow)
    ImageDraw.Draw(postcard).rectangle((130, 125, 270, 175), fill=(40, 60, 120, 255))
    postcard.save(base, format="PNG")
    Image.new("RGB", (1800, 1200), (230, 225, 210)).save(texture, format="JPEG")

    generate_composited_cover(
        postcard_path=base,
        out_path=composite,
        texture_path=texture,
        rotate_deg=0.0,  # keep geometry simple for comparison
        inset_frac=0.1,
        debug_dir=debug_dir,
    )

    assert (debug_dir / "card_layer_flat.png").exists()
    flat = Image.open(debug_dir / "card_layer_flat.png")

    # Reconstruct expected postcard window crop (matches generate_composited_cover math with rotate=0)
    card_w = int(postcard.width * 0.75)
    card_h = int(card_w * (postcard.height / postcard.width))
    window_inset = int(card_w * 0.1)
    window_w = card_w - 2 * window_inset
    window_h = card_h - 2 * window_inset
    scale_pc = max(window_w / postcard.width, window_h / postcard.height)
    scaled = postcard.resize((int(postcard.width * scale_pc), int(postcard.height * scale_pc)), resample=Image.Resampling.LANCZOS)
    left = max(0, (scaled.width - window_w) // 2)
    top = max(0, (scaled.height - window_h) // 2)
    expected_window = scaled.crop((left, top, left + window_w, top + window_h))

    # Locate the window region inside the flat card (rotate_deg=0 so no offset changes)
    window_region = flat.crop((window_inset, window_inset, window_inset + window_w, window_inset + window_h))

    expected_mean = _luminance_mean(expected_window)
    observed_mean = _luminance_mean(window_region)
    # The composite should not brighten the postcard shadow region
    assert observed_mean <= expected_mean + 1.5


def test_cover_helper_preview_pdf_consistency(monkeypatch, tmp_path):
    def fake_generate_postcard_cover(spec, debug_dir=None):
        _make_img(Path(spec.out_path), (80, 80, 200))
        if debug_dir:
            _make_img(debug_dir / "temp_face_mask.png", (1, 2, 3))

    def fake_generate_composited_cover(postcard_path, out_path, **_):
        _make_img(Path(out_path), (30, 30, 30))

    monkeypatch.setattr("services.cover_postcard.generate_postcard_cover", fake_generate_postcard_cover)
    monkeypatch.setattr("services.cover_postcard.generate_composited_cover", fake_generate_composited_cover)

    book = Book(id="b3", title="PreviewPdf", size=BookSize.SQUARE_8)
    layouts1 = [PageLayout(page_index=0, page_type=PageType.FRONT_COVER, elements=[], payload={"title": "PreviewPdf", "date_range": "2024"})]
    layouts2 = [PageLayout(page_index=0, page_type=PageType.FRONT_COVER, elements=[], payload={"title": "PreviewPdf", "date_range": "2024"})]
    assets1: dict[str, Asset] = {
        "a1": Asset(id="a1", book_id=book.id, status=AssetStatus.APPROVED, type=AssetType.PHOTO, file_path="a1.jpg"),
        "a2": Asset(id="a2", book_id=book.id, status=AssetStatus.APPROVED, type=AssetType.PHOTO, file_path="a2.jpg"),
    }
    assets2: dict[str, Asset] = {
        "a1": Asset(id="a1", book_id=book.id, status=AssetStatus.APPROVED, type=AssetType.PHOTO, file_path="a1.jpg"),
        "a2": Asset(id="a2", book_id=book.id, status=AssetStatus.APPROVED, type=AssetType.PHOTO, file_path="a2.jpg"),
    }
    context = RenderContext(book_size=BookSize.SQUARE_8)

    output_path = tmp_path / "book.pdf"
    media_root = str(tmp_path)

    monkeypatch.setenv("PHOTOBOOK_DEBUG_ARTIFACTS", "1")
    id1 = ensure_cover_asset(book, layouts1, assets1, context, media_root, str(output_path), cover_style_env="enhanced", mode_label="preview")
    # remove debug to simulate cache hit without debug files
    debug_dir = Path(media_root) / "assets" / "debug" / id1.split("_")[-1]
    if debug_dir.exists():
        for f in debug_dir.glob("*"):
            f.unlink()
    id2 = ensure_cover_asset(book, layouts2, assets2, context, media_root, str(output_path), cover_style_env="enhanced", mode_label="pdf")

    assert id1 == id2
    assert assets1[id1].file_path == assets2[id2].file_path
    assert layouts1[0].payload["cover_image_path"] == layouts2[0].payload["cover_image_path"]
    full_path = Path(media_root) / assets1[id1].file_path
    assert full_path.exists()
    assert layouts1[0].payload.get("cover_background_asset_id") == "a1"
    assert layouts2[0].payload.get("cover_background_asset_id") == "a1"
    assert any(debug_dir.glob("temp*.png"))
