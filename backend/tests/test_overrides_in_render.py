"""
Tests to ensure overrides influence render strings and hidden excludes.
"""
import tempfile
import shutil
from pathlib import Path

from services.place_overrides import PlaceOverridesStore
from services.itinerary import PlaceCandidate, merge_place_candidate_overrides
from services import render_pdf


def make_candidate(stable_id: str, name: str = "Orig", photos: int = 3, day_indices=None):
    return PlaceCandidate(
        center_lat=1.0,
        center_lon=2.0,
        total_duration_hours=1.0,
        total_photos=photos,
        total_distance_km=0.0,
        visit_count=1,
        day_indices=day_indices or [0],
        best_place_name=None,
        raw_name=None,
        display_name=name,
        stable_id=stable_id,
    )


def test_override_name_reflected_in_trip_and_day():
    # Use the default store path so merge_place_candidate_overrides picks it up
    store = PlaceOverridesStore()
    db_path = str(store.db_path)
    try:
        # Create a single candidate
        cand = make_candidate("loc1", name="Original Name", day_indices=[0])
        # Persist override
        store.upsert_override(book_id="book1", stable_id="loc1", custom_name="Custom Place", hidden=False)
        # Merge overrides
        merged = merge_place_candidate_overrides([cand], "book1")[0]
        # Trip names should use override
        trip_line = render_pdf._build_trip_place_names([merged])
        assert "Custom Place" in trip_line
        # Day names should also use override
        day_line = render_pdf._build_day_place_names(0, [merged])
        assert "Custom Place" in day_line
    finally:
        # Clean up the default DB file created for tests
        try:
            Path(db_path).unlink()
        except Exception:
            pass


def test_hidden_removed_from_trip_and_day():
    # Use default store for merge to pick up
    store = PlaceOverridesStore()
    db_path = str(store.db_path)
    try:
        cand = make_candidate("loc2", name="Hidden Place", day_indices=[0])
        store.upsert_override(book_id="book2", stable_id="loc2", hidden=True)
        merged = merge_place_candidate_overrides([cand], "book2")[0]
        trip_line = render_pdf._build_trip_place_names([merged])
        day_line = render_pdf._build_day_place_names(0, [merged])
        assert trip_line == ""
        assert day_line == ""
    finally:
        try:
            Path(db_path).unlink()
        except Exception:
            pass
