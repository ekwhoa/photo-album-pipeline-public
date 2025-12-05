"""
SQLAlchemy ORM models for persistence.
"""
from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, JSON, String
from sqlalchemy.orm import relationship

from db import Base


class BookORM(Base):
    __tablename__ = "books"

    id = Column(String, primary_key=True, index=True)
    title = Column(String, nullable=False)
    size = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    last_generated = Column(DateTime, nullable=True)
    pdf_path = Column(String, nullable=True)
    front_cover = Column(JSON, nullable=True)
    pages = Column(JSON, nullable=True)
    back_cover = Column(JSON, nullable=True)

    assets = relationship(
        "AssetORM",
        back_populates="book",
        cascade="all, delete-orphan",
    )


class AssetORM(Base):
    __tablename__ = "assets"

    id = Column(String, primary_key=True, index=True)
    book_id = Column(String, ForeignKey("books.id", ondelete="CASCADE"), nullable=False, index=True)
    status = Column(String, nullable=False)
    type = Column(String, nullable=False)
    file_path = Column(String, nullable=False)
    thumbnail_path = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)

    book = relationship("BookORM", back_populates="assets")
