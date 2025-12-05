"""
File storage abstraction.

Provides a simple interface for storing and retrieving files.
Currently uses local filesystem, can be extended to S3 or other backends.
"""
import os
import shutil
from pathlib import Path
from typing import BinaryIO, Optional
import uuid


class FileStorage:
    """
    Local file storage implementation.
    
    Files are organized as:
    - media/books/{book_id}/photos/  - Uploaded photos
    - media/books/{book_id}/thumbnails/  - Generated thumbnails
    - media/books/{book_id}/exports/  - Generated PDFs
    """
    
    def __init__(self, media_root: str = "media"):
        self.media_root = Path(media_root)
        self.media_root.mkdir(parents=True, exist_ok=True)
    
    def get_book_photos_dir(self, book_id: str) -> Path:
        """Get the photos directory for a book."""
        path = self.media_root / "books" / book_id / "photos"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_book_thumbnails_dir(self, book_id: str) -> Path:
        """Get the thumbnails directory for a book."""
        path = self.media_root / "books" / book_id / "thumbnails"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def get_book_exports_dir(self, book_id: str) -> Path:
        """Get the exports directory for a book."""
        path = self.media_root / "books" / book_id / "exports"
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def save_photo(
        self, 
        book_id: str, 
        file: BinaryIO, 
        filename: str,
        asset_id: Optional[str] = None,
    ) -> str:
        """
        Save a photo to storage.
        
        Args:
            book_id: ID of the book
            file: File-like object with the photo data
            filename: Original filename
            asset_id: Optional asset ID (used for naming)
        
        Returns:
            Relative path to the saved file
        """
        # Generate unique filename
        ext = Path(filename).suffix.lower() or ".jpg"
        new_filename = f"{asset_id or uuid.uuid4()}{ext}"
        
        # Save file
        photos_dir = self.get_book_photos_dir(book_id)
        file_path = photos_dir / new_filename
        
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file, f)
        
        # Return relative path
        return str(file_path.relative_to(self.media_root))
    
    def save_thumbnail(
        self,
        book_id: str,
        file: BinaryIO,
        asset_id: str,
    ) -> str:
        """
        Save a thumbnail to storage.
        
        Returns:
            Relative path to the saved thumbnail
        """
        thumbnails_dir = self.get_book_thumbnails_dir(book_id)
        file_path = thumbnails_dir / f"{asset_id}_thumb.jpg"
        
        with open(file_path, "wb") as f:
            shutil.copyfileobj(file, f)
        
        return str(file_path.relative_to(self.media_root))
    
    def get_pdf_path(self, book_id: str) -> str:
        """
        Get the path for a book's PDF export.
        
        Returns:
            Relative path where PDF should be saved
        """
        exports_dir = self.get_book_exports_dir(book_id)
        return str((exports_dir / "book.pdf").relative_to(self.media_root))
    
    def get_absolute_path(self, relative_path: str) -> Path:
        """Convert a relative path to absolute."""
        return self.media_root / relative_path
    
    def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists."""
        return (self.media_root / relative_path).exists()
    
    def delete_file(self, relative_path: str) -> bool:
        """Delete a file. Returns True if deleted."""
        path = self.media_root / relative_path
        if path.exists():
            path.unlink()
            return True
        return False
    
    def delete_book_files(self, book_id: str) -> bool:
        """Delete all files for a book."""
        book_dir = self.media_root / "books" / book_id
        if book_dir.exists():
            shutil.rmtree(book_dir)
            return True
        return False


# ============================================
# Future: S3 storage implementation
# ============================================

class S3Storage:
    """
    Placeholder for S3 storage implementation.
    
    Would implement the same interface as FileStorage
    but store files in AWS S3.
    """
    
    def __init__(self, bucket: str, prefix: str = ""):
        self.bucket = bucket
        self.prefix = prefix
        # TODO: Initialize boto3 client
    
    def save_photo(self, book_id: str, file: BinaryIO, filename: str, asset_id: Optional[str] = None) -> str:
        raise NotImplementedError("S3 storage not yet implemented")
    
    # ... other methods would follow same pattern
