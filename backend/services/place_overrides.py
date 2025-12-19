"""
Place overrides store.

Provides a simple SQLite-based persistence layer for user-customized place names and visibility.
"""

import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Dict


@dataclass
class PlaceOverride:
    """User override for a place."""
    book_id: str
    stable_id: str
    custom_name: Optional[str] = None
    hidden: bool = False


class PlaceOverridesStore:
    """SQLite store for place overrides, keyed by (book_id, stable_id).

    By default the DB is placed under the package-local `backend/data/`
    directory (not relative to the current working directory). This avoids
    creating duplicate DB files when processes are started from different
    working directories.
    """

    DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "place_overrides.sqlite"

    def __init__(self, db_path: Optional[str] = None):
        # If db_path is provided, honor it (useful for tests). Otherwise use
        # the package-local default under backend/data.
        self.db_path = Path(db_path) if db_path else self.DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _get_connection(self) -> sqlite3.Connection:
        """Get a database connection."""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        return conn

    def _init_schema(self) -> None:
        """Initialize the database schema."""
        conn = self._get_connection()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS place_overrides (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    book_id TEXT NOT NULL,
                    stable_id TEXT NOT NULL,
                    custom_name TEXT,
                    hidden INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(book_id, stable_id)
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def get_overrides_for_book(self, book_id: str) -> Dict[str, PlaceOverride]:
        """
        Get all overrides for a book, keyed by stable_id.

        Args:
            book_id: The book ID.

        Returns:
            A dict mapping stable_id to PlaceOverride.
        """
        conn = self._get_connection()
        try:
            cursor = conn.execute(
                "SELECT * FROM place_overrides WHERE book_id = ?",
                (book_id,),
            )
            rows = cursor.fetchall()
            result = {}
            for row in rows:
                override = PlaceOverride(
                    book_id=row["book_id"],
                    stable_id=row["stable_id"],
                    custom_name=row["custom_name"],
                    hidden=bool(row["hidden"]),
                )
                result[override.stable_id] = override
            return result
        finally:
            conn.close()

    def upsert_override(
        self,
        book_id: str,
        stable_id: str,
        *,
        custom_name: Optional[str] = None,
        hidden: Optional[bool] = None,
    ) -> PlaceOverride:
        """
        Insert or update an override for a place in a book.

        Only provided fields are updated; omitted fields are not changed
        (unless this is the first insert, in which defaults are used).

        Args:
            book_id: The book ID.
            stable_id: The stable place ID.
            custom_name: Optional custom name to set (None means no change or clear if not set).
            hidden: Optional hidden flag to set (None means no change).

        Returns:
            The updated PlaceOverride.
        """
        conn = self._get_connection()
        try:
            # Fetch existing override or create default
            cursor = conn.execute(
                "SELECT * FROM place_overrides WHERE book_id = ? AND stable_id = ?",
                (book_id, stable_id),
            )
            row = cursor.fetchone()

            if row:
                # Update existing
                new_custom_name = custom_name if custom_name is not None else row["custom_name"]
                new_hidden = hidden if hidden is not None else bool(row["hidden"])
                conn.execute(
                    """
                    UPDATE place_overrides
                    SET custom_name = ?, hidden = ?
                    WHERE book_id = ? AND stable_id = ?
                    """,
                    (new_custom_name, int(new_hidden), book_id, stable_id),
                )
            else:
                # Insert new (only if at least one field is being set)
                if custom_name is not None or hidden is not None:
                    new_custom_name = custom_name
                    new_hidden = hidden if hidden is not None else False
                    conn.execute(
                        """
                        INSERT INTO place_overrides (book_id, stable_id, custom_name, hidden)
                        VALUES (?, ?, ?, ?)
                        """,
                        (book_id, stable_id, new_custom_name, int(new_hidden)),
                    )

            conn.commit()

            # Fetch and return the result
            cursor = conn.execute(
                "SELECT * FROM place_overrides WHERE book_id = ? AND stable_id = ?",
                (book_id, stable_id),
            )
            result_row = cursor.fetchone()
            if result_row:
                return PlaceOverride(
                    book_id=result_row["book_id"],
                    stable_id=result_row["stable_id"],
                    custom_name=result_row["custom_name"],
                    hidden=bool(result_row["hidden"]),
                )
            # Fallback: return the provided values
            return PlaceOverride(
                book_id=book_id,
                stable_id=stable_id,
                custom_name=custom_name,
                hidden=hidden if hidden is not None else False,
            )
        finally:
            conn.close()
