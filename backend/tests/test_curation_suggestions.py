from services.curation_suggestions import _choose_best_in_group


def test_choose_best_prefers_lower_quality_and_higher_resolution():
    # mock metrics with quality_score: lower is better
    class M:
        def __init__(self, photo_id, quality_score, flags=None):
            self.photo_id = photo_id
            self.quality_score = quality_score
            self.flags = flags or []

    metrics = {
        "a": M("a", 0.2, []),
        "b": M("b", 0.1, []),
        "c": M("c", 0.1, []),
    }
    # meta: widths/heights
    meta = {
        "a": {"width": 1000, "height": 800},
        "b": {"width": 800, "height": 600},
        "c": {"width": 1200, "height": 900},
    }

    best = _choose_best_in_group(["a", "b", "c"], metrics, meta, representative="a")
    # b and c have equal quality (0.1); c has higher resolution so should be chosen
    assert best == "c"


def test_route_patching_adds_thumbnail_urls():
    # Simulate payload from compute_curation_suggestions
    payload = {
        "likely_rejects": [{"photo_id": "p1", "file_path": "photos/p1.jpg"}],
        "duplicate_groups": [
            {
                "representative_id": "r1",
                "members": [{"photo_id": "p2"}, {"photo_id": "p3"}],
            }
        ],
    }

    # Simulate assets from repository
    class A:
        def __init__(self, id, file_path, thumbnail_path=None):
            self.id = id
            self.file_path = file_path
            self.thumbnail_path = thumbnail_path

    assets = [A("p1", "photos/p1.jpg", "thumbs/p1.jpg"), A("p2", "photos/p2.jpg"), A("p3", "photos/p3.jpg", "thumbs/p3.jpg")]
    asset_lookup = {a.id: a for a in assets}

    # Patch payload same as route does
    for lr in payload.get("likely_rejects", []):
        a = asset_lookup.get(lr.get("photo_id"))
        rel = a.thumbnail_path if a and a.thumbnail_path else (a.file_path if a else None)
        lr["thumbnail_url"] = f"/media/{rel}" if rel else None

    for dg in payload.get("duplicate_groups", []):
        for member in dg.get("members", []):
            a = asset_lookup.get(member.get("photo_id"))
            rel = a.thumbnail_path if a and a.thumbnail_path else (a.file_path if a else None)
            member["thumbnail_url"] = f"/media/{rel}" if rel else None

    # Assertions
    assert payload["likely_rejects"][0]["thumbnail_url"] == "/media/thumbs/p1.jpg"
    assert payload["duplicate_groups"][0]["members"][0]["thumbnail_url"] == "/media/photos/p2.jpg"
    assert payload["duplicate_groups"][0]["members"][1]["thumbnail_url"] == "/media/thumbs/p3.jpg"


def test_duplicate_member_thumbnail_not_empty():
    payload = {
        "duplicate_groups": [
            {
                "representative_id": "r1",
                "members": [{"photo_id": "p2"}, {"photo_id": "p3"}],
            }
        ]
    }

    class A:
        def __init__(self, id, file_path, thumbnail_path=None):
            self.id = id
            self.file_path = file_path
            self.thumbnail_path = thumbnail_path

    assets = [A("p2", "photos/p2.jpg"), A("p3", "photos/p3.jpg", "thumbs/p3.jpg")]
    asset_lookup = {a.id: a for a in assets}

    for dg in payload.get("duplicate_groups", []):
        for member in dg.get("members", []):
            a = asset_lookup.get(member.get("photo_id"))
            rel = a.thumbnail_path if a and a.thumbnail_path else (a.file_path if a else None)
            member["thumbnail_url"] = f"/media/{rel}" if rel else None

    for dg in payload.get("duplicate_groups", []):
        for member in dg.get("members", []):
            assert member.get("thumbnail_url") is not None
            assert member.get("thumbnail_url") != member.get("photo_id")
