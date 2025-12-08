from services.blurb_engine import TripSummaryContext, build_trip_summary_blurb


def test_basic_trip_summary_blurb_includes_days_and_photos():
    ctx = TripSummaryContext(num_days=4, num_photos=185)
    line = build_trip_summary_blurb(ctx)
    assert "4-day" in line
    assert "185 photos" in line


def test_trip_summary_blurb_includes_events():
    ctx = TripSummaryContext(num_days=3, num_photos=120, num_events=5)
    line = build_trip_summary_blurb(ctx)
    assert "5 key moment" in line or "5 key moments" in line


def test_trip_summary_blurb_includes_locations():
    ctx = TripSummaryContext(num_days=5, num_photos=240, num_locations=30)
    line = build_trip_summary_blurb(ctx)
    assert "30 places" in line or "30 spots" in line
