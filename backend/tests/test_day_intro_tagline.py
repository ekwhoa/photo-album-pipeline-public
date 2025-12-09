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


def test_day_intro_tagline_travel_vs_local():
    travel_ctx = DayIntroContext(
        photos_count=5,
        segment_count=2,
        segments_total_distance_km=120.0,
        travel_segments_count=2,
        local_segments_count=0,
    )
    local_ctx = DayIntroContext(
        photos_count=5,
        segment_count=2,
        segments_total_distance_km=5.0,
        travel_segments_count=0,
        local_segments_count=2,
    )
    travel_line = build_day_intro_tagline(travel_ctx) or ""
    local_line = build_day_intro_tagline(local_ctx) or ""
    assert "Travel" in travel_line or "travel" in travel_line
    assert "Exploring" in local_line or "exploring" in local_line
