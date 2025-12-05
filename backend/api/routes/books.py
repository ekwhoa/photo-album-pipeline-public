"""
Books API routes.
"""
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from db import SessionLocal
from domain.models import Book, BookSize
from repositories import BooksRepository, AssetsRepository

router = APIRouter()
books_repo = BooksRepository()
assets_repo = AssetsRepository()


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
        # TODO: Delete files from storage
        return {"status": "deleted"}
