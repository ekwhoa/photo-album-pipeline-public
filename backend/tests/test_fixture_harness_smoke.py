import os
import shutil
import subprocess
import sys
from pathlib import Path

ARTIFACTS_DIR = Path(__file__).resolve().parents[1] / "tests" / "artifacts" / "fixture_run"
MAPS_DIR = Path(__file__).resolve().parents[1] / "data" / "maps"


def _rm_tree(p: Path):
    if p.exists():
        if p.is_file():
            p.unlink()
        else:
            shutil.rmtree(p)


def test_fixture_harness_smoke(tmp_path):
    """Run the fixture harness and assert expected outputs exist and are non-empty."""
    # Clean artifacts and maps to ensure deterministic run
    _rm_tree(ARTIFACTS_DIR)
    _rm_tree(MAPS_DIR)

    env = os.environ.copy()
    env["PYTHONPATH"] = "backend"

    cmd = [sys.executable, "-m", "backend.scripts.render_fixture_book"]
    res = subprocess.run(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=120)
    print(res.stdout.decode(errors="ignore"))
    assert res.returncode == 0

    # Minimal checks
    out_pdf = ARTIFACTS_DIR / "fixture_book.pdf"
    assert out_pdf.exists() and out_pdf.stat().st_size > 50 * 1024

    trip_map = MAPS_DIR / "book_fixture-book_route.png"
    assert trip_map.exists() and trip_map.stat().st_size > 5 * 1024

    day_maps = list(MAPS_DIR.glob("book_fixture-book_day_*_route.png"))
    assert len(day_maps) >= 1 and day_maps[0].stat().st_size > 5 * 1024

    # Thumbnails optional: only assert if present
    pages_dir = ARTIFACTS_DIR / "pages"
    if pages_dir.exists():
        thumbs = list(pages_dir.glob("page_*.png"))
        assert len(thumbs) >= 1
        assert any(t.stat().st_size > 100 for t in thumbs)
