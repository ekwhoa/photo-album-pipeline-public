Fixture images for the PDF regression harness

This folder contains small placeholder images used by the fixture regression
harness. Images are generated on-demand by `backend/scripts/render_fixture_book.py`
when you run the harness. If you prefer, you can replace the generated JPEGs
with real photos (for better face-detection behavior) — keep filenames the
same.

Files (auto-generated if missing):
- `face_1.jpg`, `face_2.jpg` — simple drawn face-like images
- `landscape.jpg` — landscape placeholder
- `portrait.jpg` — portrait placeholder
- `no_face.jpg` — scene without faces
- `spread_hero.jpg` — large hero image for spreads
- `map_stub.jpg` — simple map polyline stub

Run the fixture harness:

```bash
cd backend
python -m backend.scripts.render_fixture_book
```

Outputs are written to `backend/tests/artifacts/fixture_run/`.
