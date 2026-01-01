from datetime import datetime

from domain.models import (
    Asset,
    AssetMetadata,
    AssetStatus,
    AssetType,
    BookSize,
    PageType,
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


def test_trip_summary_right_page_gallery_when_low_geo():
    assets = [
        Asset(
            id="a1",
            book_id="b3",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy1.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 1)),
        ),
        Asset(
            id="a2",
            book_id="b3",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy2.jpg",
            metadata=AssetMetadata(taken_at=datetime(2025, 1, 2)),
        ),
    ]
    entries = [ManifestEntry(asset_id=a.id) for a in assets]
    day = Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=entries)])

    book = plan_book(
        book_id="b3",
        title="Low Geo",
        size=BookSize.SQUARE_8,
        days=[day],
        assets=assets,
    )
    # pages: title_page, trip_summary, right page
    right_page = book.pages[2]
    assert right_page.page_type == PageType.PHOTO_GRID
    assert right_page.payload.get("layout_variant") == "trip_gallery_v1"


def test_trip_summary_right_page_map_when_geo_available(monkeypatch):
    assets = [
        Asset(
            id="a1",
            book_id="b4",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy1.jpg",
            metadata=AssetMetadata(gps_lat=10.0, gps_lon=20.0, taken_at=datetime(2025, 1, 1)),
        ),
        Asset(
            id="a2",
            book_id="b4",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy2.jpg",
            metadata=AssetMetadata(gps_lat=11.0, gps_lon=21.0, taken_at=datetime(2025, 1, 2)),
        ),
    ]
    entries = [ManifestEntry(asset_id=a.id) for a in assets]
    day = Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=entries)])

    # Avoid actual map rendering by monkeypatching render_route_map
    monkeypatch.setattr("services.book_planner.render_route_map", lambda *args, **kwargs: ("rel.png", "abs.png"))

    book = plan_book(
        book_id="b4",
        title="Map",
        size=BookSize.SQUARE_8,
        days=[day],
        assets=assets,
    )
    right_page = book.pages[2]
    assert right_page.page_type == PageType.MAP_ROUTE


def test_trip_summary_map_mode_overrides(monkeypatch):
    assets = [
        Asset(
            id="a1",
            book_id="b5",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy1.jpg",
            metadata=AssetMetadata(gps_lat=10.0, gps_lon=20.0, taken_at=datetime(2025, 1, 1)),
        ),
    ]
    entries = [ManifestEntry(asset_id=a.id) for a in assets]
    day = Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=entries)])

    def spec_never(*args, **kwargs):
        return {
            "geo_coverage": 1.0,
            "map_mode": "NeverMap",
            "chapter_mode": "Off",
            "legend_mode": "Balanced",
            "accent_color": None,
            "picks_source": "auto",
            "trip_highlights": [],
            "trip_gallery_picks": [],
            "stops_for_legend": [],
            "chapter_boundaries": [],
        }

    monkeypatch.setattr("services.book_planner._build_photobook_spec_v1_metadata", spec_never)
    book = plan_book(
        book_id="b5",
        title="Never Map",
        size=BookSize.SQUARE_8,
        days=[day],
        assets=assets,
    )
    assert book.pages[2].page_type == PageType.PHOTO_GRID


def test_trip_summary_map_failure_falls_back(monkeypatch):
    assets = [
        Asset(
            id="a1",
            book_id="b6",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy1.jpg",
            metadata=AssetMetadata(gps_lat=10.0, gps_lon=20.0, taken_at=datetime(2025, 1, 1)),
        ),
        Asset(
            id="a2",
            book_id="b6",
            status=AssetStatus.APPROVED,
            type=AssetType.PHOTO,
            file_path="dummy2.jpg",
            metadata=AssetMetadata(gps_lat=11.0, gps_lon=21.0, taken_at=datetime(2025, 1, 2)),
        ),
    ]
    entries = [ManifestEntry(asset_id=a.id) for a in assets]
    day = Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=entries)])

    def spec_auto(*args, **kwargs):
        return {
            "geo_coverage": 1.0,
            "map_mode": "Auto",
            "chapter_mode": "Off",
            "legend_mode": "Balanced",
            "accent_color": None,
            "picks_source": "auto",
            "trip_highlights": [],
            "trip_gallery_picks": [],
            "stops_for_legend": [],
            "chapter_boundaries": [],
        }

    monkeypatch.setattr("services.book_planner._build_photobook_spec_v1_metadata", spec_auto)
    monkeypatch.setattr("services.book_planner.render_route_map", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("fail")))

    book = plan_book(
        book_id="b6",
        title="MapFail",
        size=BookSize.SQUARE_8,
        days=[day],
        assets=assets,
    )
    assert book.pages[2].page_type == PageType.PHOTO_GRID
