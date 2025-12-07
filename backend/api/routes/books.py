"""
Books API routes.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import SessionLocal
from domain.models import Book, BookSize, PageType
from repositories import BooksRepository, AssetsRepository
from storage.file_storage import FileStorage
from services.book_planner import plan_book
from services.timeline import TimelineService

router = APIRouter()
books_repo = BooksRepository()
assets_repo = AssetsRepository()
storage = FileStorage()


class BookCreate(BaseModel):
    title: str
    size: str = "8x8"


class BookResponse(BaseModel):
    id: str
    title: str
    size: str
    created_at: str
    updated_at: str
    asset_count: int
    approved_count: int
    last_generated: Optional[str] = None
    pdf_path: Optional[str] = None


def book_to_response(book: Book, asset_count: int, approved_count: int) -> BookResponse:
    """Convert domain Book to API response."""
    return BookResponse(
        id=book.id,
        title=book.title,
        size=book.size.value,
        created_at=book.created_at.isoformat(),
        updated_at=book.updated_at.isoformat(),
        asset_count=asset_count,
        approved_count=approved_count,
        last_generated=book.last_generated.isoformat() if book.last_generated else None,
        pdf_path=book.pdf_path,
    )


class DedupeDebugResponse(BaseModel):
    book_id: str
    approved_count: int
    used_count: int
    auto_hidden_duplicates_count: int
    auto_hidden_duplicate_clusters: List[dict]
    unused_approved_count: int
    unused_approved_asset_ids: List[str]


@router.get("/{book_id}/dedupe_debug", response_model=DedupeDebugResponse)
async def dedupe_debug(book_id: str):
    """Return dedupe metadata for a book without altering existing endpoints."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        planned = plan_book(
            book_id=book.id,
            title=book.title,
            size=book.size,
            days=days,
            assets=approved_assets,
        )

        total, approved_count = assets_repo.count_by_book(session, book.id)
        used_count = sum(
            len(page.payload.get("asset_ids", []))
            for page in planned.pages
            if page.page_type == PageType.PHOTO_GRID
        )
        return DedupeDebugResponse(
            book_id=book.id,
            approved_count=approved_count,
            used_count=used_count,
            auto_hidden_duplicates_count=len(planned.auto_hidden_duplicate_clusters),
            auto_hidden_duplicate_clusters=planned.auto_hidden_duplicate_clusters,
            unused_approved_count=len(planned.unused_approved_asset_ids),
            unused_approved_asset_ids=planned.unused_approved_asset_ids,
        )


@router.get("", response_model=List[BookResponse])
async def list_books():
    """List all books."""
    with SessionLocal() as session:
        books = books_repo.list_books(session)
        responses = []
        for book in books:
            total, approved = assets_repo.count_by_book(session, book.id)
            responses.append(book_to_response(book, total, approved))
        return responses


@router.post("", response_model=BookResponse)
async def create_book(data: BookCreate):
    """Create a new book."""
    try:
        size = BookSize(data.size)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid size: {data.size}")
    
    book = Book(
        id=Book.generate_id(),
        title=data.title,
        size=size,
    )
    with SessionLocal() as session:
        saved = books_repo.create_book(session, book)
        total, approved = assets_repo.count_by_book(session, saved.id)
        return book_to_response(saved, total, approved)


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str):
    """Get a book by ID."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        total, approved = assets_repo.count_by_book(session, book.id)
        return book_to_response(book, total, approved)


@router.delete("/{book_id}")
async def delete_book(book_id: str):
    """Delete a book and all its assets."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        books_repo.delete_book(session, book_id)
        # Best-effort file cleanup
        try:
            storage.delete_book_files(book_id)
        except Exception as e:
            print(f"[delete_book] Failed to delete media for book {book_id}: {e}")
        return {"status": "deleted"}
