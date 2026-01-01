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


def _make_asset(aid, lat=None, lon=None, taken_at=None):
    return Asset(
        id=aid,
        book_id="b-plan",
        status=AssetStatus.APPROVED,
        type=AssetType.PHOTO,
        file_path=f"{aid}.jpg",
        metadata=AssetMetadata(
            gps_lat=lat,
            gps_lon=lon,
            width=800,
            height=800,
            taken_at=taken_at or datetime(2025, 1, 1),
        ),
    )


def test_plan_highlights_and_stops_deterministic():
    assets = [
        _make_asset("a1", lat=0.0, lon=0.0, taken_at=datetime(2025, 1, 1, 10)),
        _make_asset("a2", lat=0.01, lon=0.0, taken_at=datetime(2025, 1, 1, 11)),
        _make_asset("a3", lat=0.02, lon=0.0, taken_at=datetime(2025, 1, 2, 9)),
        _make_asset("a4", lat=0.04, lon=0.0, taken_at=datetime(2025, 1, 3, 9)),
        _make_asset("a5", lat=None, lon=None, taken_at=datetime(2025, 1, 3, 10)),
        _make_asset("a6", lat=None, lon=None, taken_at=datetime(2025, 1, 4, 10)),
    ]
    # Two days: first contains a1,a2; second contains a3,a4,a5,a6
    day1_entries = [ManifestEntry(asset_id="a1"), ManifestEntry(asset_id="a2")]
    day2_entries = [ManifestEntry(asset_id="a3"), ManifestEntry(asset_id="a4"), ManifestEntry(asset_id="a5"), ManifestEntry(asset_id="a6")]
    days = [
        Day(index=0, date=datetime(2025, 1, 1), events=[Event(index=0, entries=day1_entries)]),
        Day(index=1, date=datetime(2025, 1, 2), events=[Event(index=0, entries=day2_entries)]),
    ]

    book1 = plan_book(
        book_id="b-plan",
        title="Plan Test",
        size=BookSize.SQUARE_8,
        days=days,
        assets=assets,
    )
    book2 = plan_book(
        book_id="b-plan",
        title="Plan Test",
        size=BookSize.SQUARE_8,
        days=days,
        assets=assets,
    )

    for b in (book1, book2):
        spec = b.photobook_spec_v1
        assert "trip_highlights" in spec and isinstance(spec["trip_highlights"], list)
        assert "stops_for_legend" in spec and isinstance(spec["stops_for_legend"], list)
        assert len(spec["trip_highlights"]) <= 6
        assert len(spec["stops_for_legend"]) <= 8
        # Highlights asset ids are from the approved set
        asset_ids = {a.id for a in assets}
        for h in spec["trip_highlights"]:
            assert h["asset_id"] in asset_ids
        # Stops have required keys
        for s in spec["stops_for_legend"]:
            assert {"label", "lat", "lon", "photo_count"} <= set(s.keys())

    # Determinism: highlights and stops identical across runs
    assert book1.photobook_spec_v1["trip_highlights"] == book2.photobook_spec_v1["trip_highlights"]
    assert book1.photobook_spec_v1["stops_for_legend"] == book2.photobook_spec_v1["stops_for_legend"]

    stops = book1.photobook_spec_v1["stops_for_legend"]
    if len(stops) >= 2:
        # Ensure first and last chronological clusters are present
        first_label = stops[0]["label"]
        last_label = stops[-1]["label"]
        assert first_label.startswith("Stop")
        assert last_label.startswith("Stop")
