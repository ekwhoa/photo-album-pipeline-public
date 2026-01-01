from datetime import datetime

from domain.models import (
    Asset,
    AssetMetadata,
    AssetStatus,
    AssetType,
    BookSize,
    Day,
    Event,
    ManifestEntry,
)
from services.book_planner import plan_book


def test_plan_includes_photobook_spec_defaults():
    assets = [
        Asset(
            id="a1",
            book_id="b1",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy1.jpg",
            metadata=AssetMetadata(gps_lat=37.0, gps_lon=-122.0, taken_at=datetime(2025, 1, 1)),
        ),
        Asset(
            id="a2",
            book_id="b1",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy2.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 2)),
        ),
    ]
    entries = [ManifestEntry(asset_id=a.id) for a in assets]
    day = Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=entries)])

    book = plan_book(
        book_id="b1",
        title="Spec Test",
        size=BookSize.SQUARE_8,
        days=[day],
        assets=assets,
    )

    spec = book.photobook_spec_v1
    assert isinstance(spec, dict)
    expected_keys = {
        "geo_coverage",
        "map_mode",
        "chapter_mode",
        "legend_mode",
        "accent_color",
        "picks_source",
        "trip_highlights",
        "trip_gallery_picks",
        "stops_for_legend",
        "chapter_boundaries",
    }
    assert expected_keys.issubset(set(spec.keys()))
    assert spec["map_mode"] == "Auto"
    assert spec["chapter_mode"] == "Off"
    assert spec["legend_mode"] == "Balanced"
    assert spec["picks_source"] == "auto"
    assert spec["trip_highlights"] == []
    assert spec["trip_gallery_picks"] == []
    assert spec["chapter_boundaries"] == []
    # One of two assets has GPS coords -> coverage 0.5
    assert spec["geo_coverage"] == 0.5
    assert isinstance(spec["stops_for_legend"], list)
    assert len(spec["stops_for_legend"]) >= 1
    first_stop = spec["stops_for_legend"][0]
    assert "label" in first_stop and "lat" in first_stop and "lon" in first_stop and "photo_count" in first_stop
    # Deterministic ordering ensures photo_count is descending
    assert first_stop["photo_count"] >= spec["stops_for_legend"][-1]["photo_count"]


def test_plan_geo_coverage_none_when_no_photos():
    book = plan_book(
        book_id="b2",
        title="Empty",
        size=BookSize.SQUARE_8,
        days=[],
        assets=[],
    )
    spec = book.photobook_spec_v1
    assert spec["geo_coverage"] is None
    assert spec["stops_for_legend"] == []
