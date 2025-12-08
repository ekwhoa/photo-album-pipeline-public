"""
Tests for metadata extraction service.

Run with: pytest tests/test_metadata_extractor.py -v
"""
import pytest
from io import BytesIO
from datetime import datetime
from unittest.mock import patch, MagicMock

from services.metadata_extractor import (
    extract_exif_metadata,
    is_heic_file,
    convert_heic_to_jpeg,
    register_heif_opener,
    _dms_to_decimal,
    _parse_exif_datetime,
    _compute_orientation,
)
from domain.models import AssetMetadata


class TestComputeOrientation:
    """Test orientation computation."""
    
    def test_landscape(self):
        assert _compute_orientation(1920, 1080) == "landscape"
    
    def test_portrait(self):
        assert _compute_orientation(1080, 1920) == "portrait"
    
    def test_square(self):
        assert _compute_orientation(1000, 1000) == "square"


class TestDmsToDecimal:
    """Test GPS degrees/minutes/seconds conversion."""
    
    def test_north_positive(self):
        # 40° 26' 46.8" N = 40.446333...
        dms = [40.0, 26.0, 46.8]
        result = _dms_to_decimal(dms, "N")
        assert result is not None
        assert abs(result - 40.4463333) < 0.0001
    
    def test_south_negative(self):
        # 40° 26' 46.8" S = -40.446333...
        dms = [40.0, 26.0, 46.8]
        result = _dms_to_decimal(dms, "S")
        assert result is not None
        assert abs(result - (-40.4463333)) < 0.0001
    
    def test_east_positive(self):
        dms = [74.0, 0.0, 21.0]
        result = _dms_to_decimal(dms, "E")
        assert result is not None
        assert result > 0
    
    def test_west_negative(self):
        dms = [74.0, 0.0, 21.0]
        result = _dms_to_decimal(dms, "W")
        assert result is not None
        assert result < 0
    
    def test_invalid_input_none(self):
        assert _dms_to_decimal(None, "N") is None
    
    def test_invalid_input_short_list(self):
        assert _dms_to_decimal([40.0, 26.0], "N") is None


class TestParseExifDatetime:
    """Test EXIF datetime parsing."""
    
    def test_standard_format(self):
        result = _parse_exif_datetime("2024:06:15 14:30:45")
        assert result is not None
        assert result.year == 2024
        assert result.month == 6
        assert result.day == 15
        assert result.hour == 14
        assert result.minute == 30
        assert result.second == 45
    
    def test_iso_format(self):
        result = _parse_exif_datetime("2024-06-15 14:30:45")
        assert result is not None
        assert result.year == 2024
    
    def test_invalid_format(self):
        result = _parse_exif_datetime("not a date")
        assert result is None
    
    def test_non_string(self):
        result = _parse_exif_datetime(12345)
        assert result is None


class TestIsHeicFile:
    """Test HEIC file detection."""
    
    def test_heic_extension(self):
        assert is_heic_file("photo.heic") is True
        assert is_heic_file("PHOTO.HEIC") is True
        assert is_heic_file("photo.heif") is True
    
    def test_jpeg_extension(self):
        assert is_heic_file("photo.jpg") is False
        assert is_heic_file("photo.jpeg") is False
        assert is_heic_file("photo.png") is False
    
    def test_heic_content_type(self):
        assert is_heic_file("photo", "image/heic") is True
        assert is_heic_file("photo", "image/heif") is True
    
    def test_jpeg_content_type(self):
        assert is_heic_file("photo", "image/jpeg") is False


class TestExtractExifMetadata:
    """Test EXIF metadata extraction."""
    
    def test_no_exif_still_returns_metadata(self):
        """An image with no EXIF should still return dimensions."""
        # Create a minimal valid JPEG in memory
        from PIL import Image
        
        img = Image.new("RGB", (100, 200), color="red")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        buffer.seek(0)
        
        metadata = extract_exif_metadata(buffer.read())
        
        assert metadata.width == 100
        assert metadata.height == 200
        assert metadata.orientation == "portrait"
        assert metadata.taken_at is None  # No EXIF
        assert metadata.gps_lat is None
        assert metadata.gps_lon is None
    
    def test_invalid_bytes_returns_empty_metadata(self):
        """Invalid image bytes should return empty metadata, not raise."""
        metadata = extract_exif_metadata(b"not an image")
        
        assert isinstance(metadata, AssetMetadata)
        assert metadata.width is None
        assert metadata.height is None
    
    def test_empty_bytes_returns_empty_metadata(self):
        """Empty bytes should return empty metadata, not raise."""
        metadata = extract_exif_metadata(b"")
        
        assert isinstance(metadata, AssetMetadata)


class TestExtractExifWithMockedExif:
    """Test EXIF extraction with mocked EXIF data."""
    
    def test_with_datetime_original(self):
        """Test extraction of DateTimeOriginal."""
        from PIL import Image
        
        # Create test image
        img = Image.new("RGB", (800, 600), color="blue")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        buffer.seek(0)
        
        # Mock getexif to return test data
        with patch.object(Image.Image, "getexif", create=True) as mock_exif:
            mock_exif.return_value = {
                36867: "2024:01:15 10:30:00",  # DateTimeOriginal tag
                271: "Apple",  # Make
                272: "iPhone 15 Pro",  # Model
            }
            
            buffer.seek(0)
            metadata = extract_exif_metadata(buffer.read())
            
            assert metadata.taken_at is not None
            assert metadata.taken_at.year == 2024
            assert metadata.taken_at.month == 1
            assert metadata.camera == "Apple iPhone 15 Pro"
    
    def test_with_gps_info(self):
        """Test extraction of GPS coordinates."""
        from PIL import Image
        
        img = Image.new("RGB", (800, 600), color="green")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        buffer.seek(0)
        
        # Mock GPS data (New York City area)
        gps_info = {
            1: "N",  # GPSLatitudeRef
            2: [40.0, 42.0, 46.0],  # GPSLatitude
            3: "W",  # GPSLongitudeRef
            4: [74.0, 0.0, 21.0],  # GPSLongitude
            5: 0,  # GPSAltitudeRef (above sea level)
            6: 10.5,  # GPSAltitude
        }
        
        with patch.object(Image.Image, "getexif", create=True) as mock_exif:
            mock_exif.return_value = {
                34853: gps_info,  # GPSInfo tag
            }
            
            buffer.seek(0)
            metadata = extract_exif_metadata(buffer.read())
            
            # GPS should be parsed
            assert metadata.gps_lat is not None
            assert metadata.gps_lon is not None
            assert metadata.gps_lat > 40  # Roughly NYC latitude
            assert metadata.gps_lon < 0  # West longitude


class TestHeicConversion:
    """Test HEIC to JPEG conversion."""
    
    def test_heic_conversion_without_pillow_heif(self):
        """If pillow-heif is not installed, conversion should fail gracefully."""
        # This test verifies the function exists and handles missing deps
        # Actual conversion requires pillow-heif to be installed
        from PIL import Image
        
        # Create a regular JPEG as test input
        img = Image.new("RGB", (100, 100), color="yellow")
        buffer = BytesIO()
        img.save(buffer, format="JPEG")
        buffer.seek(0)
        
        # This should work for JPEG even though it's named convert_heic
        result = convert_heic_to_jpeg(buffer.read())
        assert len(result) > 0
    
    def test_register_heif_opener_safe(self):
        """register_heif_opener should not crash if pillow-heif is missing."""
        # This just verifies it doesn't raise
        result = register_heif_opener()
        # Result is True if pillow-heif is installed, False otherwise
        assert isinstance(result, bool)


class TestAssetUploadIntegration:
    """Integration-style tests for the upload flow."""
    
    def test_heic_filename_detection(self):
        """HEIC files should be detected by filename."""
        assert is_heic_file("IMG_1234.heic") is True
        assert is_heic_file("IMG_1234.HEIC") is True
        assert is_heic_file("photo.heif") is True
    
    def test_file_extension_change(self):
        """Helper to change extension should work correctly."""
        from api.routes.assets import _change_extension
        
        assert _change_extension("photo.heic", ".jpg") == "photo.jpg"
        assert _change_extension("photo.HEIC", ".jpg") == "photo.jpg"
        assert _change_extension("my.photo.heic", ".jpg") == "my.photo.jpg"
        assert _change_extension("photo", ".jpg") == "photo.jpg"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
