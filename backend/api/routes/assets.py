"""
Assets API routes.
"""
from io import BytesIO
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel
from PIL import Image, ImageOps

from db import SessionLocal
from domain.models import Asset, AssetMetadata, AssetStatus, AssetType
from repositories import BooksRepository, AssetsRepository
from services.curation import set_asset_status
from services.metadata_extractor import (
    extract_exif_metadata,
    is_heic_file,
    convert_heic_to_jpeg,
)
from storage.file_storage import FileStorage

router = APIRouter()
storage = FileStorage()
books_repo = BooksRepository()
assets_repo = AssetsRepository()


class AssetResponse(BaseModel):
    id: str
    book_id: str
    status: str
    type: str
    file_path: str
    thumbnail_path: Optional[str] = None
    metadata: dict


class StatusUpdate(BaseModel):
    status: str  # "approved" or "rejected"


class BulkStatusUpdate(BaseModel):
    asset_ids: List[str]
    status: str


def asset_to_response(asset: Asset) -> AssetResponse:
    """Convert domain Asset to API response."""
    return AssetResponse(
        id=asset.id,
        book_id=asset.book_id,
        status=asset.status.value,
        type=asset.type.value,
        file_path=asset.file_path,
        thumbnail_path=asset.thumbnail_path,
        metadata={
            "width": asset.metadata.width,
            "height": asset.metadata.height,
            "orientation": asset.metadata.orientation,
            "taken_at": asset.metadata.taken_at.isoformat() if asset.metadata.taken_at else None,
            "camera": asset.metadata.camera,
            "gps_lat": asset.metadata.gps_lat,
            "gps_lon": asset.metadata.gps_lon,
            "gps_altitude": asset.metadata.gps_altitude,
            "location": asset.metadata.location,
        },
    )


@router.get("", response_model=List[AssetResponse])
async def list_assets(book_id: str, status: Optional[str] = None):
    """List assets for a book, optionally filtered by status."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        status_enum = None
        if status:
            try:
                status_enum = AssetStatus(status)
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid status: {status}")

        book_assets = assets_repo.list_assets(session, book_id, status_enum)
        return [asset_to_response(a) for a in book_assets]


@router.post("/upload", response_model=List[AssetResponse])
async def upload_assets(book_id: str, files: List[UploadFile] = File(...)):
    """Upload one or more photos to a book."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        uploaded = []

        for file in files:
            # Generate asset ID
            asset_id = Asset.generate_id()
            original_filename = file.filename or "photo.jpg"
            
            # Read file content
            file_content = await file.read()
            
            # Extract EXIF metadata from original bytes (works for HEIC too)
            try:
                metadata = extract_exif_metadata(file_content)
            except Exception:
                metadata = AssetMetadata()
            
            # Determine if this is a HEIC file and needs conversion
            is_heic = is_heic_file(original_filename, file.content_type)
            
            # Prepare bytes and filename for storage
            if is_heic:
                try:
                    # Convert HEIC to JPEG
                    storage_bytes = convert_heic_to_jpeg(file_content)
                    # Change extension to .jpg
                    storage_filename = _change_extension(original_filename, ".jpg")
                except Exception:
                    # HEIC conversion failed - try to save original anyway
                    storage_bytes = file_content
                    storage_filename = original_filename
            else:
                storage_bytes = file_content
                storage_filename = original_filename
            
            # Save file to storage
            file_path = storage.save_photo(
                book_id=book_id,
                file=BytesIO(storage_bytes),
                filename=storage_filename,
                asset_id=asset_id,
            )
            
            # Ensure we have dimensions (may need to re-read after conversion), using EXIF-aware orientation
            if metadata.width is None or metadata.height is None or metadata.orientation is None:
                try:
                    img = Image.open(BytesIO(storage_bytes))
                    img = ImageOps.exif_transpose(img)
                    metadata.width = img.width
                    metadata.height = img.height
                    if img.width > img.height:
                        metadata.orientation = "landscape"
                    elif img.width < img.height:
                        metadata.orientation = "portrait"
                    else:
                        metadata.orientation = "square"
                except Exception:
                    pass
            
            # Generate thumbnail
            thumbnail_path = None
            try:
                thumb_bytes = _generate_thumbnail(storage_bytes, max_size=512)
                thumbnail_path = storage.save_thumbnail(
                    book_id=book_id,
                    file=BytesIO(thumb_bytes),
                    asset_id=asset_id,
                )
            except Exception as e:
                print(f"[thumbnail] Failed to generate thumbnail for asset {asset_id}: {e}")
            
            # Create asset
            asset = Asset(
                id=asset_id,
                book_id=book_id,
                status=AssetStatus.IMPORTED,
                type=AssetType.PHOTO,
                file_path=file_path,
                thumbnail_path=thumbnail_path,
                metadata=metadata,
            )
            saved = assets_repo.create_asset(session, asset)
            uploaded.append(saved)
        
        return [asset_to_response(a) for a in uploaded]


def _change_extension(filename: str, new_ext: str) -> str:
    """Change the file extension."""
    if "." in filename:
        base = filename.rsplit(".", 1)[0]
    else:
        base = filename
    return base + new_ext


def _generate_thumbnail(image_bytes: bytes, max_size: int = 512) -> bytes:
    """
    Generate a JPEG thumbnail from image bytes.
    
    Args:
        image_bytes: Source image data (after any conversions)
        max_size: Max dimension (width or height)
    
    Returns:
        JPEG bytes of the thumbnail.
    """
    with Image.open(BytesIO(image_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        img = img.convert("RGB")
        img.thumbnail((max_size, max_size))
        output = BytesIO()
        img.save(output, format="JPEG", quality=85, optimize=True)
        output.seek(0)
        return output.read()


@router.patch("/{asset_id}/status", response_model=AssetResponse)
async def update_asset_status(book_id: str, asset_id: str, data: StatusUpdate):
    """Update the status of an asset (approve/reject)."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        asset = assets_repo.get_asset(session, asset_id, book_id)
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        try:
            new_status = AssetStatus(data.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
        
        asset = set_asset_status(asset, new_status)
        updated = assets_repo.update_status(session, asset_id, book_id, asset.status)
        if not updated:
            raise HTTPException(status_code=404, detail="Asset not found")
        
        return asset_to_response(updated)


@router.patch("/bulk-status", response_model=List[AssetResponse])
async def bulk_update_status(book_id: str, data: BulkStatusUpdate):
    """Update the status of multiple assets at once."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        
        try:
            new_status = AssetStatus(data.status)
        except ValueError:
            raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
        
        updated = assets_repo.bulk_update_status(
            session, data.asset_ids, book_id, new_status
        )
        
        return [asset_to_response(a) for a in updated]
