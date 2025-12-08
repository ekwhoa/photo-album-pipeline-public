"""
Pipeline API routes.

Handles book generation and PDF output.
"""
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

from db import SessionLocal
from domain.models import AssetStatus, RenderContext, Theme
from repositories import BooksRepository, AssetsRepository
from services.curation import filter_approved
from services.manifest import build_manifest
from services.timeline import build_days_and_events
from services.book_planner import plan_book
from services.layout_engine import compute_all_layouts
from services.render_pdf import render_book_to_pdf, render_book_to_html
from storage.file_storage import FileStorage

router = APIRouter()
storage = FileStorage()
books_repo = BooksRepository()
assets_repo = AssetsRepository()


class PagePreviewResponse(BaseModel):
    index: int
    page_type: str
    summary: str
    asset_ids: List[str] | None = None
    hero_asset_id: str | None = None
    layout_variant: str | None = None
    segment_count: int | None = None
    segments_total_distance_km: float | None = None
    segments_total_duration_hours: float | None = None
    segments: List[dict] | None = None


class GenerateResponse(BaseModel):
    success: bool
    page_count: int
    pdf_path: str
    warnings: List[str]


class PreviewHtmlResponse(BaseModel):
    html: str

class PagePreviewHtmlResponse(BaseModel):
    html: str

@router.post("/generate", response_model=GenerateResponse)
async def generate_book(book_id: str):
    """
    Run the full pipeline to generate a book PDF.
    
    Pipeline stages:
    1. Filter approved assets
    2. Build manifest/timeline
    3. Group into days/events
    4. Plan book structure
    5. Compute layouts
    6. Render PDF
    """
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        warnings = []
        
        # Get approved assets
        book_assets = assets_repo.list_assets(session, book_id)
        approved_assets = filter_approved(book_assets)
        
        if not approved_assets:
            raise HTTPException(
                status_code=400, 
                detail="No approved assets. Approve some photos first."
            )
        
        if len(approved_assets) < 3:
            warnings.append(f"Only {len(approved_assets)} photos - book may be sparse")
        
        # Build manifest
        manifest = build_manifest(book_id, approved_assets)
        
        # Group into days/events
        days = build_days_and_events(manifest)
        
        # Plan book
        planned_book = plan_book(
            book_id=book_id,
            title=book.title,
            size=book.size,
            days=days,
            assets=approved_assets,
        )
        
        # Update book with planned structure
        book.front_cover = planned_book.front_cover
        book.pages = planned_book.pages
        book.back_cover = planned_book.back_cover
        
        # Compute layouts
        context = RenderContext(
            book_size=book.size,
            theme=Theme(),
        )
        all_pages = book.get_all_pages()
        layouts = compute_all_layouts(all_pages, context)
        
        # Render PDF
        pdf_relative_path = storage.get_pdf_path(book_id)
        pdf_absolute_path = str(storage.get_absolute_path(pdf_relative_path))
        
        assets_dict = {a.id: a for a in approved_assets}
        
        render_book_to_pdf(
            book=book,
            layouts=layouts,
            assets=assets_dict,
            context=context,
            output_path=pdf_absolute_path,
            media_root=str(storage.media_root),
        )
        
        # Update book metadata
        book.pdf_path = pdf_relative_path
        book.last_generated = datetime.utcnow()
        book.updated_at = datetime.utcnow()
        books_repo.update_book(session, book)
        
        return GenerateResponse(
            success=True,
            page_count=len(all_pages),
            pdf_path=pdf_relative_path,
            warnings=warnings,
        )


@router.get("/pages", response_model=List[PagePreviewResponse])
async def get_pages(book_id: str):
    """Get a list of pages in the generated book."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        all_pages = book.get_all_pages()
        
        previews = []
        for page in all_pages:
            # Generate summary based on page type
            asset_ids = None
            hero_asset_id = None
            layout_variant = None
            segment_count = None
            segments_total_distance_km = None
            segments_total_duration_hours = None
            segments = None
            if page.page_type.value == "front_cover":
                summary = f"Title: {page.payload.get('title', 'Untitled')}"
                hero_asset_id = page.payload.get("hero_asset_id")
            elif page.page_type.value == "photo_grid":
                asset_ids = page.payload.get("asset_ids", [])
                layout_variant = page.payload.get("layout_variant")
                if layout_variant is None:
                    layout_variant = "default"
                summary = f"{len(asset_ids)} photos"
            elif page.page_type.value == "back_cover":
                summary = page.payload.get("text", "Back cover")
            elif page.page_type.value == "trip_summary":
                day_count = page.payload.get("day_count", 0)
                photo_count = page.payload.get("photo_count", 0)
                summary = f"Trip overview: {day_count} days, {photo_count} photos"
            elif page.page_type.value == "map_route":
                gps_photo_count = page.payload.get("gps_photo_count")
                distinct_locations = page.payload.get("distinct_locations")
                segments = page.payload.get("segments")
                if gps_photo_count is not None and distinct_locations is not None:
                    summary = f"Map route: {gps_photo_count} photos with location across ~{distinct_locations} spots"
                else:
                    summary = "Map route (no GPS data)"
            elif page.page_type.value in ("photo_full", "full_page_photo"):
                asset_ids = page.payload.get("asset_ids", [])
                hero_asset_id = page.payload.get("hero_asset_id")
                summary = "Full-page photo"
            elif page.page_type.value == "day_intro":
                day_index = page.payload.get("day_index")
                display_date = page.payload.get("display_date") or page.payload.get("day_date") or "Day"
                photo_count = page.payload.get("day_photo_count")
                segment_count = page.payload.get("segment_count")
                segments_total_distance_km = page.payload.get("segments_total_distance_km")
                segments_total_duration_hours = page.payload.get("segments_total_duration_hours")
                segments = page.payload.get("segments")
                summary = f"Day {day_index}: {display_date}"
                if photo_count is not None:
                    summary += f" • {photo_count} photos"
            elif page.page_type.value == "photo_spread":
                hero_asset_id = page.payload.get("hero_asset_id") or (page.payload.get("asset_ids") or [None])[0]
                summary = "Photo spread"
                asset_ids = page.payload.get("asset_ids", [])
                if not asset_ids and hero_asset_id:
                    asset_ids = [hero_asset_id]
                hero_asset_id = hero_asset_id
            else:
                summary = page.page_type.value
            
            previews.append(PagePreviewResponse(
                index=page.index,
                page_type=page.page_type.value,
                summary=summary,
                asset_ids=asset_ids,
                hero_asset_id=hero_asset_id,
                layout_variant=layout_variant,
                segment_count=segment_count,
                segments_total_distance_km=segments_total_distance_km,
                segments_total_duration_hours=segments_total_duration_hours,
                segments=segments,
            ))
        
        return previews


@router.get("/pdf")
async def download_pdf(book_id: str):
    """Download the generated PDF."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        if not book.pdf_path:
            raise HTTPException(status_code=404, detail="PDF not generated yet")
        
        pdf_path = storage.get_absolute_path(book.pdf_path)
        if not pdf_path.exists():
            raise HTTPException(status_code=404, detail="PDF file not found")
        
    return FileResponse(
        path=str(pdf_path),
        filename=f"{book.title}.pdf",
        media_type="application/pdf",
    )


@router.get("/preview-html", response_model=PreviewHtmlResponse)
async def get_preview_html(book_id: str, request: Request):
    """
    Return the generated HTML for a book for live preview.
    Does not write to disk.
    """
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        all_pages = book.get_all_pages()
        if not all_pages:
            raise HTTPException(status_code=404, detail="Book has not been generated yet")

        # Use approved assets only
        approved_assets = assets_repo.list_assets(session, book_id, AssetStatus.APPROVED)
        if not approved_assets:
            raise HTTPException(status_code=400, detail="No approved assets found")

        context = RenderContext(
            book_size=book.size,
            theme=Theme(),
        )
        try:
            layouts = compute_all_layouts(all_pages, context)
            assets_dict = {a.id: a for a in approved_assets}
            base_media_url = f"{str(request.base_url).rstrip('/')}/media"
            html_content = render_book_to_html(
                book=book,
                layouts=layouts,
                assets=assets_dict,
                context=context,
                media_root=str(storage.media_root),
                mode="web",
                media_base_url=base_media_url,
            )
        except Exception as e:
            print(f"[preview-html] Failed to generate preview HTML for book {book_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate preview HTML")

        return PreviewHtmlResponse(html=html_content)


@router.get("/preview/pages/{page_index}/html", response_model=PagePreviewHtmlResponse)
async def get_page_preview_html(book_id: str, page_index: int, request: Request):
    """
    Return HTML for a single page for thumbnail previews.
    """
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        all_pages = book.get_all_pages()
        if not all_pages or page_index < 0 or page_index >= len(all_pages):
            raise HTTPException(status_code=404, detail="Page not found")

        approved_assets = assets_repo.list_assets(session, book_id, AssetStatus.APPROVED)
        if not approved_assets:
            raise HTTPException(status_code=400, detail="No approved assets found")

        context = RenderContext(
            book_size=book.size,
            theme=Theme(),
        )

        try:
            layouts = compute_all_layouts(all_pages, context)
            layout = next((l for l in layouts if l.page_index == page_index), None)
            if layout is None:
                raise HTTPException(status_code=404, detail="Page not found")
            assets_dict = {a.id: a for a in approved_assets}
            base_media_url = f"{str(request.base_url).rstrip('/')}/media"
            html_content = render_book_to_html(
                book=book,
                layouts=[layout],
                assets=assets_dict,
                context=context,
                media_root=str(storage.media_root),
                mode="web",
                media_base_url=base_media_url,
            )
        except HTTPException:
            raise
        except Exception as e:
            print(f"[preview-page-html] Failed to generate page {page_index} HTML for book {book_id}: {e}")
            raise HTTPException(status_code=500, detail="Failed to generate page preview HTML")

        return PagePreviewHtmlResponse(html=html_content)
