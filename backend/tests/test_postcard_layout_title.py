from vendor.postcard_renderer import defaults
from vendor.postcard_renderer import engine


def test_long_title_respects_safe_box():
    long_title = "SAN FRANCISCO AND THE PACIFIC COAST HIGHWAY"
    layout = engine.layout_title_text(
        long_title,
        str(defaults.FONT_PATH),
        (engine.TEMP_TEXT_WIDTH, engine.TEMP_TEXT_HEIGHT),
    )
    mask = engine.render_title_mask(layout)
    bbox = mask.getbbox()
    assert bbox is not None

    safe = layout.safe_box
    pad = engine.TITLE_SAFE_PADDING
    assert bbox[0] >= safe[0] + pad
    assert bbox[1] >= safe[1] + pad
    assert bbox[2] <= safe[2] - pad
    assert bbox[3] <= safe[3] - pad

    w, h = mask.size
    edge = max(1, int(4 * engine.RENDER_SCALE))
    assert mask.crop((0, 0, w, edge)).getextrema()[1] == 0
    assert mask.crop((0, h - edge, w, h)).getextrema()[1] == 0
    assert mask.crop((0, 0, edge, h)).getextrema()[1] == 0
    assert mask.crop((w - edge, 0, w, h)).getextrema()[1] == 0


def test_short_title_keeps_default_scale():
    layout = engine.layout_title_text(
        "CHICAGO",
        str(defaults.FONT_PATH),
        (engine.TEMP_TEXT_WIDTH, engine.TEMP_TEXT_HEIGHT),
    )
    assert len(layout.lines) == 1
    assert layout.mode == "single"
    assert 0.98 <= layout.scale <= 1.02


def test_long_multi_word_title_prefers_two_lines_for_height():
    layout = engine.layout_title_text(
        "SAN FRANCISCO AND THE PACIFIC COAST HIGHWAY",
        str(defaults.FONT_PATH),
        (engine.TEMP_TEXT_WIDTH, engine.TEMP_TEXT_HEIGHT),
    )
    assert layout.height_ratio_single < engine.MIN_TITLE_HEIGHT_RATIO_SINGLE_LINE
    assert layout.mode == "two_line"
    assert len(layout.lines) == 2
    assert layout.height_ratio >= layout.height_ratio_single * (1.0 + engine.TITLE_TWO_LINE_IMPROVE_THRESHOLD)
    assert layout.chosen_split_index != 1


def test_no_orphan_for_four_plus_words():
    layout = engine.layout_title_text(
        "ONE TWO THREE FOUR FIVE",
        str(defaults.FONT_PATH),
        (engine.TEMP_TEXT_WIDTH, engine.TEMP_TEXT_HEIGHT),
    )
    if layout.mode == "two_line":
        word_counts = [len(line.split()) for line in layout.lines]
        assert min(word_counts) > 1
