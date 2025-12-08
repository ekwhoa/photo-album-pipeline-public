import pytest

from services.blurb_engine import DayIntroContext, build_day_intro_tagline


@pytest.mark.parametrize(
    "segment_count,hours,km,expected_substr",
    [
        (3, 8.4, 500.0, "Big travel day"),
        (2, 6.0, 20.0, "Covering some ground"),
        (1, 9.0, 50.0, "Covering some ground"),
        (0, 0.1, 0.2, "relaxed day"),
    ],
)
def test_day_intro_tagline_categories(segment_count, hours, km, expected_substr):
    ctx = DayIntroContext(photos_count=10, segment_count=segment_count, segments_total_distance_km=km)
    line = build_day_intro_tagline(ctx) or ""
    assert expected_substr in line


def test_day_intro_tagline_omits_zero_values():
    ctx = DayIntroContext(photos_count=0, segment_count=0, segments_total_distance_km=0.0)
    line = build_day_intro_tagline(ctx)
    assert line is None


def test_day_intro_tagline_formats_numbers():
    ctx = DayIntroContext(photos_count=2, segment_count=2, segments_total_distance_km=12.0)
    line = build_day_intro_tagline(ctx) or ""
    assert "0.0" not in line
