"""
In-memory database for development.

Replace with SQLAlchemy or another ORM for production.
"""
from typing import Dict
from domain.models import Asset, Book

# In-memory storage
books_db: Dict[str, Book] = {}
assets_db: Dict[str, Asset] = {}
