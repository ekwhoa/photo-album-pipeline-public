# Architecture

## Backend (FastAPI, services, storage)
- Stack: FastAPI app in `backend/api/main.py` with in-memory database helpers under `backend/api/database.py`.
- Domain models: `backend/domain/models.py` defines `Book`, `Asset`, `Page`, `PageType`, `Manifest`, `Day`, `Event`, `Theme`, `RenderContext`, and layout primitives (`LayoutRect`, `PageLayout`).
- Services (core pipeline logic):
  - `services/metadata_extractor.py` — EXIF/HEIC-friendly metadata extraction (`taken_at`, GPS, orientation, raw EXIF) from uploaded bytes.
  - `services/curation.py` — asset status updates and filtering for approved assets.
  - `services/manifest.py` — builds a `Manifest` from approved assets.
  - `services/timeline.py` — groups manifest entries into days/events.
  - `services/book_planner.py` — assembles the book structure (front cover, `photo_grid` pages, back cover; future hooks for `trip_summary`, etc.).
  - `services/layout_engine.py` — registry mapping each `PageType` to a layout function that produces `PageLayout`.
  - `services/render_pdf.py` — renders the planned book + layouts to HTML and then to PDF (WeasyPrint).
- Storage: `storage/file_storage.py` saves originals/thumbnails to `media/books/<book_id>/...`; `MEDIA_ROOT` env controls the root.

## Photo pipeline (end-to-end)
- Upload: `POST /books/{id}/assets/upload` saves files and extracts EXIF (JPEG/PNG/HEIC) into `AssetMetadata`.
- Curation: assets start as `imported`; approve/reject via `services/curation` (bulk or single) to produce the approved set.
- Manifest: approved assets → `services/manifest` builds ordered `Manifest` entries (tracks timestamps for sequencing).
- Timeline: `services/timeline` groups manifest entries into `Day`/`Event` buckets for trip structure.
- Book planning: `services/book_planner` creates `Book` with a front cover, interior `photo_grid` pages, and a back cover (extensible for other page types).
- Layout: `services/layout_engine` computes `PageLayout` rectangles per page type using `RenderContext` (size, theme).
- PDF render: `services/render_pdf` converts layouts + book data to HTML and emits a print-ready PDF path; stored under `media/` and referenced on the `Book`.

## API surface (FastAPI routes)
- Books: `GET /books`, `POST /books` (create), `GET /books/{id}`, `DELETE /books/{id}`.
- Assets: `GET /books/{id}/assets[?status=...]`, `POST /books/{id}/assets/upload`, `PATCH /books/{id}/assets/{asset_id}/status`, `PATCH /books/{id}/assets/bulk-status`.
- Pipeline: `POST /books/{id}/generate` (runs manifest → timeline → plan → layout → PDF), `GET /books/{id}/pages` (page summaries/previews), `GET /books/{id}/pdf` (download).
- Media: served from `/media/{path}` for originals/thumbnails and generated PDF assets.

## Frontend (React + TypeScript, Vite)
- Routing: `src/App.tsx` sets up `/` (books list) and `/books/:id` (book workspace).
- Books list: `src/pages/BooksPage.tsx` lists books via `booksApi`, shows creation dialog (`CreateBookDialog`), and uses `BookCard`.
- Book detail: `src/pages/BookDetailPage.tsx` drives four tabs:
  - Upload: `UploadZone` for uploads, shows recent imported photos.
  - Curate: `AssetGrid` for approve/reject with bulk selection/filtering.
  - Generate: triggers pipeline, shows counts/last run.
  - Preview: shows generated pages via `PagePreviewCard` + `PageDetailModal`, and offers PDF download.
- API client: `src/lib/api.ts` (`booksApi`, `assetsApi`, `pipelineApi`, `getThumbnailUrl`) targeting `VITE_API_URL` or `http://127.0.0.1:8000`.

## Extending with new page types
- Backend:
  - Add the type to `PageType` in `backend/domain/models.py`.
  - Teach `services/book_planner.py` to produce pages of the new type.
  - Register a layout function in `services/layout_engine.py` for the new `PageType` returning a `PageLayout`.
  - Update `services/render_pdf.py` if the HTML/PDF rendering needs new styling or assets.
- Frontend:
  - Surface new page summaries/previews in `PagePreviewCard` / `PageDetailModal` (in `src/components`) when the API returns them.
  - Optionally add new stats or actions in `BookDetailPage.tsx` (Generate/Preview tabs) to reflect the new page type’s data.
