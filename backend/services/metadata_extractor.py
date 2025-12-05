"""
EXIF metadata extraction service.

Extracts rich metadata from images including GPS coordinates,
capture time, camera info, and raw EXIF data.
"""
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, Optional, Tuple

from domain.models import AssetMetadata


def extract_exif_metadata(file_bytes: bytes) -> AssetMetadata:
    """
    Extract EXIF metadata from image bytes.
    
    Args:
        file_bytes: Raw image file bytes (JPEG, PNG, HEIC, etc.)
        
    Returns:
        AssetMetadata with populated fields. Missing/unparseable fields are None.
        Never raises - returns partial metadata on errors.
    """
    metadata = AssetMetadata()
    
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS, GPSTAGS
        
        img = Image.open(BytesIO(file_bytes))
        
        # Get dimensions
        metadata.width = img.width
        metadata.height = img.height
        metadata.orientation = _compute_orientation(img.width, img.height)
        
        # Try to get EXIF data
        exif_data = _get_exif_dict(img)
        if exif_data:
            metadata.raw_exif = exif_data
            
            # Parse capture datetime
            metadata.taken_at = _parse_datetime(exif_data)
            
            # Parse camera info
            metadata.camera = _parse_camera(exif_data)
            
            # Parse GPS
            gps_info = exif_data.get("GPSInfo")
            if gps_info:
                lat, lon = _parse_gps_coordinates(gps_info)
                metadata.gps_lat = lat
                metadata.gps_lon = lon
                metadata.gps_altitude = _parse_gps_altitude(gps_info)
                
                # Also populate legacy location field
                if lat is not None and lon is not None:
                    metadata.location = {"lat": lat, "lng": lon}
        
    except ImportError:
        pass  # PIL not available
    except Exception:
        pass  # Image parsing failed - return whatever we have
    
    return metadata


def _compute_orientation(width: int, height: int) -> str:
    """Compute orientation from dimensions."""
    if width > height:
        return "landscape"
    elif width < height:
        return "portrait"
    return "square"


def _get_exif_dict(img) -> Optional[Dict[str, Any]]:
    """
    Extract EXIF data as a human-readable dictionary.
    
    Converts numeric tag IDs to string names and makes values JSON-serializable.
    """
    try:
        from PIL.ExifTags import TAGS, GPSTAGS
        
        exif_raw = img._getexif()
        if not exif_raw:
            return None
        
        exif_dict = {}
        for tag_id, value in exif_raw.items():
            tag_name = TAGS.get(tag_id, str(tag_id))
            
            # Handle GPSInfo specially
            if tag_name == "GPSInfo" and isinstance(value, dict):
                gps_dict = {}
                for gps_tag_id, gps_value in value.items():
                    gps_tag_name = GPSTAGS.get(gps_tag_id, str(gps_tag_id))
                    gps_dict[gps_tag_name] = _make_json_safe(gps_value)
                exif_dict[tag_name] = gps_dict
            else:
                exif_dict[tag_name] = _make_json_safe(value)
        
        return exif_dict
        
    except Exception:
        return None


def _make_json_safe(value: Any) -> Any:
    """Convert EXIF value to JSON-serializable type."""
    if value is None:
        return None
    
    # Handle bytes
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", errors="replace")
        except Exception:
            return f"<bytes: {len(value)} bytes>"
    
    # Handle tuples/lists (common for GPS coordinates)
    if isinstance(value, (tuple, list)):
        return [_make_json_safe(v) for v in value]
    
    # Handle IFDRational or similar fraction types
    if hasattr(value, "numerator") and hasattr(value, "denominator"):
        try:
            if value.denominator == 0:
                return None
            return float(value.numerator) / float(value.denominator)
        except Exception:
            return str(value)
    
    # Handle basic types
    if isinstance(value, (int, float, str, bool)):
        return value
    
    # Handle dict
    if isinstance(value, dict):
        return {str(k): _make_json_safe(v) for k, v in value.items()}
    
    # Fallback to string representation
    return str(value)


def _parse_datetime(exif_data: Dict[str, Any]) -> Optional[datetime]:
    """Parse capture datetime from EXIF data."""
    # Try various datetime tags in order of preference
    datetime_tags = ["DateTimeOriginal", "DateTimeDigitized", "DateTime"]
    
    for tag in datetime_tags:
        value = exif_data.get(tag)
        if value:
            parsed = _parse_exif_datetime(value)
            if parsed:
                return parsed
    
    return None


def _parse_exif_datetime(value: Any) -> Optional[datetime]:
    """Parse an EXIF datetime string."""
    if not isinstance(value, str):
        return None
    
    # Common EXIF datetime formats
    formats = [
        "%Y:%m:%d %H:%M:%S",  # Standard EXIF format
        "%Y-%m-%d %H:%M:%S",  # ISO-ish format
        "%Y/%m/%d %H:%M:%S",  # Slash format
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    
    return None


def _parse_camera(exif_data: Dict[str, Any]) -> Optional[str]:
    """Parse camera make/model from EXIF data."""
    make = exif_data.get("Make", "")
    model = exif_data.get("Model", "")
    
    if make and model:
        # Avoid duplication if model already contains make
        if make.lower() in model.lower():
            return model.strip()
        return f"{make.strip()} {model.strip()}"
    elif model:
        return model.strip()
    elif make:
        return make.strip()
    
    return None


def _parse_gps_coordinates(gps_info: Dict[str, Any]) -> Tuple[Optional[float], Optional[float]]:
    """
    Parse GPS latitude and longitude from EXIF GPSInfo.
    
    Converts degrees/minutes/seconds format to decimal degrees.
    
    Returns:
        Tuple of (latitude, longitude) in decimal degrees, or (None, None) on error.
    """
    try:
        lat = gps_info.get("GPSLatitude")
        lat_ref = gps_info.get("GPSLatitudeRef", "N")
        lon = gps_info.get("GPSLongitude")
        lon_ref = gps_info.get("GPSLongitudeRef", "E")
        
        if lat is None or lon is None:
            return None, None
        
        lat_decimal = _dms_to_decimal(lat, lat_ref)
        lon_decimal = _dms_to_decimal(lon, lon_ref)
        
        return lat_decimal, lon_decimal
        
    except Exception:
        return None, None


def _dms_to_decimal(dms: Any, ref: str) -> Optional[float]:
    """
    Convert degrees/minutes/seconds to decimal degrees.
    
    Args:
        dms: List/tuple of [degrees, minutes, seconds] (may be floats or rationals)
        ref: Reference direction ("N", "S", "E", "W")
        
    Returns:
        Decimal degrees, negative for S/W.
    """
    try:
        if not isinstance(dms, (list, tuple)) or len(dms) < 3:
            return None
        
        degrees = float(dms[0])
        minutes = float(dms[1])
        seconds = float(dms[2])
        
        decimal = degrees + (minutes / 60.0) + (seconds / 3600.0)
        
        # Apply direction
        if ref.upper() in ("S", "W"):
            decimal = -decimal
        
        return round(decimal, 7)  # ~1cm precision
        
    except Exception:
        return None


def _parse_gps_altitude(gps_info: Dict[str, Any]) -> Optional[float]:
    """Parse GPS altitude from EXIF GPSInfo."""
    try:
        altitude = gps_info.get("GPSAltitude")
        if altitude is None:
            return None
        
        alt_value = float(altitude)
        
        # Check altitude reference (0 = above sea level, 1 = below)
        alt_ref = gps_info.get("GPSAltitudeRef", 0)
        if alt_ref == 1:
            alt_value = -alt_value
        
        return round(alt_value, 2)
        
    except Exception:
        return None


def is_heic_file(filename: str, content_type: Optional[str] = None) -> bool:
    """
    Check if a file is a HEIC/HEIF image.
    
    Args:
        filename: Original filename
        content_type: MIME content type if available
        
    Returns:
        True if the file is likely HEIC/HEIF.
    """
    if filename:
        ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
        if ext in ("heic", "heif"):
            return True
    
    if content_type:
        heic_types = ["image/heic", "image/heif", "image/heic-sequence", "image/heif-sequence"]
        if content_type.lower() in heic_types:
            return True
    
    return False


def convert_heic_to_jpeg(file_bytes: bytes, quality: int = 90) -> bytes:
    """
    Convert HEIC/HEIF image bytes to JPEG.
    
    Args:
        file_bytes: Raw HEIC image bytes
        quality: JPEG quality (1-100)
        
    Returns:
        JPEG bytes
        
    Raises:
        Exception if conversion fails (pillow-heif not installed, invalid image, etc.)
    """
    from PIL import Image
    
    img = Image.open(BytesIO(file_bytes))
    
    # Convert to RGB if necessary (HEIC may have alpha or other modes)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    
    # Save to JPEG bytes
    output = BytesIO()
    img.save(output, format="JPEG", quality=quality, optimize=True)
    output.seek(0)
    
    return output.read()


def register_heif_opener():
    """
    Register HEIF/HEIC opener with Pillow if pillow-heif is available.
    
    Call this at application startup to enable HEIC support.
    Safe to call multiple times or if pillow-heif is not installed.
    """
    try:
        from pillow_heif import register_heif_opener as _register
        _register()
        return True
    except ImportError:
        return False
