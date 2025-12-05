"""
Books API routes.
"""
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from api.database import books_db, assets_db
from domain.models import Book, BookSize

router = APIRouter()


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


def book_to_response(book: Book) -> BookResponse:
    """Convert domain Book to API response."""
    book_assets = [a for a in assets_db.values() if a.book_id == book.id]
    approved = [a for a in book_assets if a.status.value == "approved"]
    
    return BookResponse(
        id=book.id,
        title=book.title,
        size=book.size.value,
        created_at=book.created_at.isoformat(),
        updated_at=book.updated_at.isoformat(),
        asset_count=len(book_assets),
        approved_count=len(approved),
        last_generated=book.last_generated.isoformat() if book.last_generated else None,
        pdf_path=book.pdf_path,
    )


@router.get("", response_model=List[BookResponse])
async def list_books():
    """List all books."""
    return [book_to_response(book) for book in books_db.values()]


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
    books_db[book.id] = book
    return book_to_response(book)


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str):
    """Get a book by ID."""
    book = books_db.get(book_id)
    if not book:
        raise HTTPException(status_code=404, detail="Book not found")
    return book_to_response(book)


@router.delete("/{book_id}")
async def delete_book(book_id: str):
    """Delete a book and all its assets."""
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    
    # Delete assets
    asset_ids_to_delete = [a.id for a in assets_db.values() if a.book_id == book_id]
    for asset_id in asset_ids_to_delete:
        del assets_db[asset_id]
    
    # Delete book
    del books_db[book_id]
    
    # TODO: Delete files from storage
    
    return {"status": "deleted"}
