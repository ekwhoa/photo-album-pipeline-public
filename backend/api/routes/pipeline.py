"""
Pipeline API routes.

Handles book generation and PDF output.
"""
from datetime import datetime
from typing import List
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from api.database import books_db, assets_db
from domain.models import AssetStatus, BookSize, RenderContext, Theme
from services.curation import filter_approved
from services.manifest import build_manifest
from services.timeline import build_days_and_events
from services.book_planner import plan_book
from services.layout_engine import compute_all_layouts
from services.render_pdf import render_book_to_pdf
from storage.file_storage import FileStorage

router = APIRouter()
storage = FileStorage()


class PagePreviewResponse(BaseModel):
    index: int
    page_type: str
    summary: str


class GenerateResponse(BaseModel):
    success: bool
    page_count: int
    pdf_path: str
    warnings: List[str]


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
    book = books_db.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    warnings = []
    
    # Get approved assets
    book_assets = [a for a in assets_db.values() if a.book_id == book_id]
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
    books_db[book_id] = book
    
    return GenerateResponse(
        success=True,
        page_count=len(all_pages),
        pdf_path=pdf_relative_path,
        warnings=warnings,
    )


@router.get("/pages", response_model=List[PagePreviewResponse])
async def get_pages(book_id: str):
    """Get a list of pages in the generated book."""
    book = books_db.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    
    all_pages = book.get_all_pages()
    
    previews = []
    for page in all_pages:
        # Generate summary based on page type
        if page.page_type.value == "front_cover":
            summary = f"Title: {page.payload.get('title', 'Untitled')}"
        elif page.page_type.value == "photo_grid":
            asset_ids = page.payload.get("asset_ids", [])
            summary = f"{len(asset_ids)} photos"
        elif page.page_type.value == "back_cover":
            summary = page.payload.get("text", "Back cover")
        elif page.page_type.value == "trip_summary":
            day_count = page.payload.get("day_count", 0)
            photo_count = page.payload.get("photo_count", 0)
            summary = f"Trip overview: {day_count} days, {photo_count} photos"
        else:
            summary = page.page_type.value
        
        previews.append(PagePreviewResponse(
            index=page.index,
            page_type=page.page_type.value,
            summary=summary,
        ))
    
    return previews


@router.get("/pdf")
async def download_pdf(book_id: str):
    """Download the generated PDF."""
    book = books_db.get(book_id)
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
