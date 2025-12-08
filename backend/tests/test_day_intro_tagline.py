import pytest

from services.render_pdf import build_day_intro_tagline


@pytest.mark.parametrize(
    "segment_count,hours,km,expected_substr",
    [
        (3, 8.4, 1492.6, "Big travel day"),
        (2, 6.0, 20.0, "Out and about"),
        (1, 9.0, 50.0, "Full-day exploring"),
        (0, 0.1, 0.2, "Chill day nearby"),
    ],
)
def test_day_intro_tagline_categories(segment_count, hours, km, expected_substr):
    line = build_day_intro_tagline(segment_count, hours, km)
    assert expected_substr in line


def test_day_intro_tagline_omits_zero_values():
    line = build_day_intro_tagline(0, 0.0, 0.0)
    assert line == ""


def test_day_intro_tagline_formats_numbers():
    line = build_day_intro_tagline(2, 1.0, 2.0)
    assert "0.0" not in line
    assert "1.0 h" in line or "1.0" in line
