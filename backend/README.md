# PhotoBook Studio - Python Backend

A Python/FastAPI backend for generating print-ready photo books.

## Quick Start

1. **Create a virtual environment:**
   ```bash
   cd backend
   python -m venv venv
   
   # Windows
   venv\Scripts\activate
   
   # macOS/Linux
   source venv/bin/activate
   ```

2. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

3. **Run the server:**
   ```bash
   uvicorn api.main:app --reload --port 8000
   ```

4. **Access the API:**
   - API: http://localhost:8000
   - Docs: http://localhost:8000/docs

## Project Structure

```
backend/
├── api/                    # FastAPI application
│   ├── main.py            # App entry point
│   ├── database.py        # In-memory database (replace for production)
│   └── routes/            # API endpoints
│       ├── books.py       # Book CRUD
│       ├── assets.py      # Photo upload & curation
│       └── pipeline.py    # Book generation
│
├── domain/                # Core domain models
│   └── models.py          # Book, Asset, Page, etc.
│
├── services/              # Business logic
│   ├── curation.py        # Photo approval workflow
│   ├── manifest.py        # Timeline building
│   ├── timeline.py        # Day/event grouping
│   ├── book_planner.py    # Book structure planning
│   ├── layout_engine.py   # Page layout computation
│   └── render_pdf.py      # PDF generation
│
├── storage/               # File storage abstraction
│   └── file_storage.py    # Local filesystem storage
│
└── requirements.txt       # Python dependencies
```

## API Endpoints

### Books
- `GET /books` - List all books
- `POST /books` - Create a new book
- `GET /books/{id}` - Get book details
- `DELETE /books/{id}` - Delete a book

### Assets
- `GET /books/{id}/assets` - List assets (optionally filter by status)
- `POST /books/{id}/assets/upload` - Upload photos
- `PATCH /books/{id}/assets/{asset_id}/status` - Approve/reject a photo
- `PATCH /books/{id}/assets/bulk-status` - Bulk status update

### Pipeline
- `POST /books/{id}/generate` - Generate the photo book PDF
- `GET /books/{id}/pages` - Get page previews
- `GET /books/{id}/pdf` - Download the PDF

## Pipeline Stages

1. **Curation** - Approve/reject photos (manual for now)
2. **Manifest** - Build timeline from approved photos
3. **Timeline** - Group photos into days/events
4. **Book Planning** - Create book structure (cover + pages)
5. **Layout** - Compute visual layout for each page
6. **Render** - Generate print-ready PDF

## Page Types

Currently implemented:
- `front_cover` - Hero image with title
- `photo_grid` - Grid of photos (2x2, 2x3, 3x3)
- `back_cover` - Simple text back cover

Future page types (structure defined, not implemented):
- `map_route` - Map with trip polyline
- `spotlight` - Single featured photo
- `postcard_cover` - Vintage postcard style
- `photobooth_strip` - Photo booth strip layout
- `trip_summary` - Text summary page
- `itinerary` - Day-by-day itinerary

## Configuration

Set these environment variables:
- `MEDIA_ROOT` - Path for media files (default: `./media`)

## PDF Rendering

The app uses WeasyPrint for PDF generation. On Windows, you may need to install GTK:

1. Download GTK from: https://github.com/nickvergessen/gtk-win64
2. Add GTK bin folder to your PATH

Alternative: Install reportlab for simpler PDF output (uncomment in requirements.txt).

## Extending

### Adding a new page type:

1. Add the type to `PageType` enum in `domain/models.py`
2. Register a layout function in `services/layout_engine.py`:
   ```python
   @register_layout(PageType.MY_NEW_TYPE)
   def layout_my_new_type(page: Page, context: RenderContext) -> PageLayout:
       # Compute layout
       return PageLayout(...)
   ```
3. Update book planner to create pages of this type when appropriate

### Adding themes:

1. Extend the `Theme` class in `domain/models.py`
2. Pass different themes to `RenderContext`
3. Layout functions use `context.theme` for colors/fonts

### Switching to S3 storage:

1. Implement `S3Storage` class in `storage/file_storage.py`
2. Update API routes to use the new storage backend

## Fixture PDF regression harness

This repository includes a small regression harness that renders a deterministic
fixture "golden" book and produces per-page thumbnails for quick visual
inspection.

Run it locally from the repo root:

```bash
cd backend
python -m backend.scripts.render_fixture_book
```

Outputs are written to `backend/tests/artifacts/fixture_run/` (ignored by git).
If you want tighter regression checks later, you can commit small PNG
baselines and compare with a pixel tolerance.

Thumbnails: If you want the harness to generate per-page PNG thumbnails, install
PyMuPDF first:

```bash
pip install pymupdf
```

On Windows, install into your backend virtualenv and then run the harness as
shown above. The harness will still produce the PDF without PyMuPDF, but
thumbnail generation will be skipped.
