"""
Assets API routes.
"""
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional
from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from api.database import books_db, assets_db
from domain.models import Asset, AssetMetadata, AssetStatus, AssetType
from services.curation import set_asset_status
from services.metadata_extractor import (
    extract_exif_metadata,
    is_heic_file,
    convert_heic_to_jpeg,
)
from storage.file_storage import FileStorage

router = APIRouter()
storage = FileStorage()


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
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    
    book_assets = [a for a in assets_db.values() if a.book_id == book_id]
    
    if status:
        book_assets = [a for a in book_assets if a.status.value == status]
    
    # Sort by creation time, newest first
    book_assets.sort(key=lambda a: a.created_at, reverse=True)
    
    return [asset_to_response(a) for a in book_assets]


@router.post("/upload", response_model=List[AssetResponse])
async def upload_assets(book_id: str, files: List[UploadFile] = File(...)):
    """Upload one or more photos to a book."""
    if book_id not in books_db:
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
        
        # Ensure we have dimensions (may need to re-read after conversion)
        if metadata.width is None or metadata.height is None:
            try:
                from PIL import Image
                img = Image.open(BytesIO(storage_bytes))
                metadata.width = img.width
                metadata.height = img.height
                if metadata.orientation is None:
                    if img.width > img.height:
                        metadata.orientation = "landscape"
                    elif img.width < img.height:
                        metadata.orientation = "portrait"
                    else:
                        metadata.orientation = "square"
            except Exception:
                pass
        
        # Create asset
        asset = Asset(
            id=asset_id,
            book_id=book_id,
            status=AssetStatus.IMPORTED,
            type=AssetType.PHOTO,
            file_path=file_path,
            metadata=metadata,
        )
        assets_db[asset.id] = asset
        uploaded.append(asset)
    
    return [asset_to_response(a) for a in uploaded]


def _change_extension(filename: str, new_ext: str) -> str:
    """Change the file extension."""
    if "." in filename:
        base = filename.rsplit(".", 1)[0]
    else:
        base = filename
    return base + new_ext


@router.patch("/{asset_id}/status", response_model=AssetResponse)
async def update_asset_status(book_id: str, asset_id: str, data: StatusUpdate):
    """Update the status of an asset (approve/reject)."""
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    
    asset = assets_db.get(asset_id)
    if not asset or asset.book_id != book_id:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    try:
        new_status = AssetStatus(data.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
    
    asset = set_asset_status(asset, new_status)
    assets_db[asset.id] = asset
    
    return asset_to_response(asset)


@router.patch("/bulk-status", response_model=List[AssetResponse])
async def bulk_update_status(book_id: str, data: BulkStatusUpdate):
    """Update the status of multiple assets at once."""
    if book_id not in books_db:
        raise HTTPException(status_code=404, detail="Book not found")
    
    try:
        new_status = AssetStatus(data.status)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid status: {data.status}")
    
    updated = []
    for asset_id in data.asset_ids:
        asset = assets_db.get(asset_id)
        if asset and asset.book_id == book_id:
            asset = set_asset_status(asset, new_status)
            assets_db[asset.id] = asset
            updated.append(asset)
    
    return [asset_to_response(a) for a in updated]
