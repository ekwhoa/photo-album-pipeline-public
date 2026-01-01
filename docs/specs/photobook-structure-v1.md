# Photobook Structure v1: Trip Summary, Chapters, Map/Gallery Fallbacks

Status: Draft  
Owner: Ekow  
Last updated: 2025-12-31

## Visual references
- [Photobook gallery example](assets/photobook-structure-v1/photobook_gallery_example.png)
- [Photobook gallery example 2](assets/photobook-structure-v1/photobook_gallery_example2.png)
- [Photobook trip summary](assets/photobook-structure-v1/photobook_trip_summary.png)
- [Photobook day intro](assets/photobook-structure-v1/photobook_day_intro.png)

Reference-only; not normative.

## Goals

Produce a consistent, print-friendly photobook structure that:

- Works for single-city and multi-city trips.
- Handles missing/sparse geotags gracefully.
- Is deterministic (preview and PDF match; reruns are stable).
- Requires minimal user input (opinionated default).

## Non-goals (v1)

- User-driven stop-by-stop editing or extensive customization flows.
- “Top attractions” from external POI datasets (we infer hotspots from photos/geotags instead).
- Cute narrative copy (“Back to Chicago!”) beyond deterministic labeling.
- Multiple maps per spread or repeated map pages for every sub-region.

## Definitions

- Geo coverage: geotagged_photos / total_photos where geotagged photos have usable lat/lon.
- Stop / Hotspot: A clustered region of geotag points (trip-level or chapter-level).
- Highlight: A selected photo + label used in summary pages (best-of picks).
- City Chapter: A chronological block of days that belong to the same city cluster (or location label). If you return later, that creates a new chapter.
- Master Summary: The first Trip Summary spread for the whole book. In a single-city book it functions like a city intro.

## High-level page order

### Always present (front matter)

- Front Cover (postcard-style cover)
- Title Page (book title + date range; optional future: letters-only “temp_warped_group” art)
- Trip Summary spread
  - Left page: trip summary + highlights + (optional) “mini map” locator
  - Right page: Map page or Trip Gallery fallback (see thresholds)

### Body (chronological)

- Chapters (if enabled / multi-city conditions met)
- Days (day intro + photo pages) in chronological order

### Back matter

- Back Cover (simple; v1 can match front cover background style)

## Book title and cover title rules

### Library display

- Primary: BookTitle
- Secondary: DateRange (always visible)
- If collision (same title + same date range): append (2), (3) etc deterministically.

### Book title (default)

- Single-city trip: use City name (derived from clustering/geocoding).
- Multi-city trip: prefer user-provided title if present; else:
  - City 1 → City N (e.g., “Chicago → New Orleans”)
  - If too long, truncate with (+N) (e.g., “Chicago → New Orleans (+3)”)

### Cover postcard main word

- Single-city: City
- Multi-city: user title if present, else City 1 (start city)
- Cover bottom script: date range (e.g., “Jul–Aug 2025”) or “YYYY” if space constrained.

## Map vs Gallery behavior (thresholds)

Compute geo_coverage.

### Geo coverage ≥ 0.25

- Show normal Trip Map page on the right side of the Trip Summary spread.
- Day maps allowed (existing behavior or the canonical-points approach already implemented).

### 0.05 ≤ Geo coverage < 0.25

- Show “coarse map” behavior:
  - Map page still exists, but stops/legend should be city-level (fewer markers).
  - Consider disabling day maps in this mode (optional; v1 can keep day maps if stable).

### Geo coverage < 0.05

- Replace Trip Map page with Trip Gallery page (best photos).

### Map failure fallback (always)

- If map rendering fails (tiles unavailable, exceptions, etc.):
  - Fall back to Trip Gallery for that book render.
  - Log warning with book_id and error.

## Trip Summary spread (content slots)

### Left page: Trip Summary

Required elements:

- Title (book title)
- Date range
- “Highlights” section (see selection rules)

Optional: mini locator “dot map” (world or country-level) with a single marker:

- Marker = centroid of all geotags (if available); else omit.

Notes:

- Avoid showing “distance traveled” in v1 unless location data is dense and reliable.
- Avoid stats that feel meaningless with photo-only GPS (e.g., percent geotagged).

### Right page: Map page OR Trip Gallery

- Map page: main route map with legend for stops/hotspots (see caps).
- Trip Gallery: a best-of layout (deterministic selection):
  - Default layout: 1 hero + 4 grid (1 large + 4 small)
  - Alternative (allowed): 2×3 grid (6 photos)

## City chapters (multi-city behavior)

### When to create chapters

- If the trip resolves to more than one “city cluster” across the timeline:
  - Create a new City Chapter whenever the dominant city label changes.
  - Returning to a city later creates a new chapter (chronological preserved).

### Chapter intro page (v1)

- Title: City Name (deterministic)
- Optional subtitle: date range for that chapter
- Chapter map behavior:
  - If geo coverage sufficient, chapter/day maps can use the same canonical polyline with a chapter/day viewport.
  - (Visual design is separate; this spec defines structure and required data only.)

## Stops and legend rules (caps + overflow)

### Caps (print-safe defaults for 8×8)

- Max stops shown in any legend: 8
- Max highlights shown on summary page: 6
- Max cities shown on master list (if you add it later): 8

### Stop selection (default: Balanced)

When there are more than 8 candidate stops:

- Always include first and last stop (chronological).
- Fill remaining slots by descending photo_count (or time-spent proxy if available).
- If still overflowing: show a + N more line.

## “Best photos” selection (deterministic + overrideable)

### Determinism requirements

- Selection must be stable given the same inputs.
- Any randomness must be seeded by book_id (or a stable derived seed).
- Preview and PDF must use the same selected asset IDs.

### Baseline selection (always-on, no ML required)

For highlights and Trip Gallery:

- Filter out low-resolution assets (configurable threshold).
- Filter blurred photos (use existing blur score / Laplacian variance if available).
- Remove near-duplicates using existing dedupe/cluster logic.
- Enforce diversity:
  - Prefer spread across days/segments.
  - Avoid picking more than 2 from the same time cluster.
- Rank remaining by a stable score (weights adjustable):
  - sharpness
  - uniqueness
  - exposure sanity (optional)
  - “representativeness” of a day/segment (optional)

### Enhanced selection (optional toggle; v1 can be stubbed)

- If “Enhanced” is enabled:
  - Use CLIP/Ollama embeddings for diversity bucketing (people/food/landmark/etc.) and/or similarity suppression.
- Must remain deterministic by:
  - caching computed embeddings and chosen results
  - caching chosen picks in the book plan output

### Override behavior

- Store picks_source = auto | enhanced | user.
- If a user edits picks, set to user and do not auto-recompute unless explicitly reset.

## Hotspots / “Attractions” (v1 approach)

### v1 definition

- “Attractions” are inferred hotspots from geotag clusters, not a curated POI dataset.

### Candidate scoring

- photo_count within cluster
- time span / dwell proxy (if available from timestamps)
- optionally: unique days represented

### Cluster labeling

- reverse geocode cluster centroid (Nominatim already in use)
- choose best label field available:
  - attraction/poi name > neighborhood > city
- If label missing: fallback to City or Lat,Lon short format

## Toggles (strict default + limited controls)

Required toggles:

- MapMode: Auto | AlwaysMap | NeverMap
  - Auto uses geo_coverage thresholds + map-failure fallback.
- LegendMode: Balanced | Chronological | MostPhotographed
- ChapterMode: Off | ByCity
- AccentColor: used consistently in icons/lines/markers (visual spec)

## Data that must be produced by planning (contract)

Planner output must include (or be derivable without re-computation at render time):

- Book title + date range
- Geo coverage
- Selected highlights (asset IDs + labels)
- Trip Gallery picks (asset IDs)
- Stop list for legend (with stable ordering)
- Chapter boundaries (if enabled)
- Cached/canonical route polyline reference (if used) so day maps don’t re-simplify differently

## Acceptance criteria (v1)

### Determinism

- Preview HTML and PDF show the same picks, same legend ordering, same cover asset IDs, same map/gallery choice.

### Geo fallback

- If geo_coverage < 0.05, Trip Summary right page is Trip Gallery (no map).

### Map failure fallback

- If map rendering throws, Trip Gallery is rendered instead; book generation succeeds.

### Caps

- No legend shows more than 8 stops; overflow shows + N more.

### Chapters

- If ChapterMode=ByCity and multiple city clusters exist, chapter intro pages appear in chronological order; returning to a city later creates another chapter.

### Library differentiation

- Two books with same computed title but different dates are distinguishable by their date range in the library list.

## Open questions (allowed to defer)

- Exact clustering method for “city chapters” (can start simple and refine).
- Whether coarse-map mode disables day maps or uses zoomed viewports.
- Whether to add an “itinerary” legend on the map page (future layout spec).
