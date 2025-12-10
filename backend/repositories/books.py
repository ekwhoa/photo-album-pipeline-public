"""
Book repository backed by SQLAlchemy/SQLite.
"""
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy.orm import Session

from domain.models import Book, BookSize, Page, PageType
from repositories.models import BookORM


def _make_json_safe(value):
    """Recursively convert any datetime/date objects to ISO strings."""
    from datetime import date, datetime

    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, dict):
        return {k: _make_json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_make_json_safe(v) for v in value]
    return value


def _page_from_dict(data: dict) -> Page:
    return Page(
        index=data.get("index", 0),
        page_type=PageType(data.get("page_type")),
        payload=data.get("payload", {}),
    )


def _page_to_dict(page: Page) -> dict:
    return _make_json_safe(page.to_dict())


def _book_from_orm(orm: BookORM) -> Book:
    front_cover = _page_from_dict(orm.front_cover) if orm.front_cover else None
    pages = [_page_from_dict(p) for p in orm.pages] if orm.pages else []
    back_cover = _page_from_dict(orm.back_cover) if orm.back_cover else None

    return Book(
        id=orm.id,
        title=orm.title,
        size=BookSize(orm.size),
        front_cover=front_cover,
        pages=pages,
        back_cover=back_cover,
        created_at=orm.created_at,
        updated_at=orm.updated_at,
        last_generated=orm.last_generated,
        pdf_path=orm.pdf_path,
    )


def _update_orm_from_book(orm: BookORM, book: Book) -> None:
    orm.title = book.title
    orm.size = book.size.value
    orm.updated_at = book.updated_at
    orm.last_generated = book.last_generated
    orm.pdf_path = book.pdf_path
    orm.front_cover = _page_to_dict(book.front_cover) if book.front_cover else None
    orm.pages = [_page_to_dict(p) for p in book.pages] if book.pages else None
    orm.back_cover = _page_to_dict(book.back_cover) if book.back_cover else None


class BooksRepository:
    """CRUD operations for books."""

    def list_books(self, session: Session) -> List[Book]:
        books = session.query(BookORM).all()
        return [_book_from_orm(b) for b in books]

    def get_book(self, session: Session, book_id: str) -> Optional[Book]:
        orm = session.get(BookORM, book_id)
        if not orm:
            return None
        return _book_from_orm(orm)

    def create_book(self, session: Session, book: Book) -> Book:
        now = datetime.utcnow()
        orm = BookORM(
            id=book.id,
            title=book.title,
            size=book.size.value,
            created_at=book.created_at or now,
            updated_at=book.updated_at or now,
            last_generated=book.last_generated,
            pdf_path=book.pdf_path,
        )
        session.add(orm)
        session.commit()
        session.refresh(orm)
        return _book_from_orm(orm)

    def update_book(self, session: Session, book: Book) -> Book:
        orm = session.get(BookORM, book.id)
        if not orm:
            raise ValueError("Book not found")
        _update_orm_from_book(orm, book)
        session.add(orm)
        session.commit()
        session.refresh(orm)
        return _book_from_orm(orm)

    def delete_book(self, session: Session, book_id: str) -> None:
        orm = session.get(BookORM, book_id)
        if orm:
            session.delete(orm)
            session.commit()
