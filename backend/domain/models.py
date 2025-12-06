"""
Core domain models for the photo book generator.
These are framework-agnostic and can be used across all services.
"""
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


class AssetStatus(str, Enum):
    """Status of an asset in the curation workflow."""
    IMPORTED = "imported"
    APPROVED = "approved"
    REJECTED = "rejected"


class AssetType(str, Enum):
    """Type of asset."""
    PHOTO = "photo"
    AI_IMAGE = "ai_image"  # Future: DALL-E generated
    MAP_IMAGE = "map_image"  # Future: Map screenshots


class PageType(str, Enum):
    """
    Types of pages in a photo book.
    
    Currently implemented:
    - FRONT_COVER
    - PHOTO_GRID
    - BACK_COVER
    
    Future (defined for extensibility, not implemented yet):
    - MAP_ROUTE: Shows a map with polyline of the trip
    - SPOTLIGHT: Single photo with special treatment
    - POSTCARD_COVER: Vintage postcard-style cover
    - PHOTOBOOTH_STRIP: Multiple photos in strip format
    - TRIP_SUMMARY: Text-based summary of the trip
    - ITINERARY: Day-by-day itinerary view
    """
    # Currently implemented
    FRONT_COVER = "front_cover"
    PHOTO_GRID = "photo_grid"
    BACK_COVER = "back_cover"
    
    # Future page types (structure only)
    MAP_ROUTE = "map_route"
    SPOTLIGHT = "spotlight"
    POSTCARD_COVER = "postcard_cover"
    PHOTOBOOTH_STRIP = "photobooth_strip"
    TRIP_SUMMARY = "trip_summary"
    ITINERARY = "itinerary"


class BookSize(str, Enum):
    """Standard book sizes."""
    SQUARE_8 = "8x8"
    SQUARE_10 = "10x10"
    PORTRAIT_8X10 = "8x10"
    LANDSCAPE_10X8 = "10x8"
    LARGE_11X14 = "11x14"


@dataclass
class AssetMetadata:
    """Metadata extracted from an image file."""
    width: Optional[int] = None
    height: Optional[int] = None
    orientation: Optional[str] = None  # "landscape", "portrait", "square"
    taken_at: Optional[datetime] = None
    camera: Optional[str] = None
    location: Optional[Dict[str, float]] = None  # {"lat": ..., "lng": ...}
    # GPS fields
    gps_lat: Optional[float] = None
    gps_lon: Optional[float] = None
    gps_altitude: Optional[float] = None
    # Raw EXIF data for debugging/future use
    raw_exif: Optional[Dict[str, Any]] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AssetMetadata":
        taken_at = data.get("taken_at")
        if isinstance(taken_at, str):
            taken_at = datetime.fromisoformat(taken_at)
        return cls(
            width=data.get("width"),
            height=data.get("height"),
            orientation=data.get("orientation"),
            taken_at=taken_at,
            camera=data.get("camera"),
            location=data.get("location"),
            gps_lat=data.get("gps_lat"),
            gps_lon=data.get("gps_lon"),
            gps_altitude=data.get("gps_altitude"),
            raw_exif=data.get("raw_exif"),
        )


@dataclass
class Asset:
    """
    An asset in a photo book project.
    
    Assets start as 'imported' and can be approved/rejected during curation.
    Only approved assets are included in the generated book.
    """
    id: str
    book_id: str
    status: AssetStatus
    type: AssetType
    file_path: str  # Relative to media root
    thumbnail_path: Optional[str] = None
    metadata: AssetMetadata = field(default_factory=AssetMetadata)
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    @staticmethod
    def generate_id() -> str:
        return str(uuid.uuid4())


@dataclass
class Page:
    """
    A page in a photo book.
    
    The payload field contains type-specific data:
    - front_cover: {"title": str, "subtitle": str, "hero_asset_id": str}
    - photo_grid: {"asset_ids": List[str], "layout": str}
    - back_cover: {"text": str}
    """
    index: int
    page_type: PageType
    payload: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "page_type": self.page_type.value,
            "payload": self.payload,
        }


@dataclass
class Book:
    """
    A photo book project.
    
    Contains metadata and the structure of the book (covers + pages).
    """
    id: str
    title: str
    size: BookSize
    front_cover: Optional[Page] = None
    pages: List[Page] = field(default_factory=list)
    back_cover: Optional[Page] = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    last_generated: Optional[datetime] = None
    pdf_path: Optional[str] = None
    
    @staticmethod
    def generate_id() -> str:
        return str(uuid.uuid4())
    
    def get_all_pages(self) -> List[Page]:
        """Returns all pages in order: front cover, interior pages, back cover."""
        result = []
        if self.front_cover:
            result.append(self.front_cover)
        result.extend(self.pages)
        if self.back_cover:
            result.append(self.back_cover)
        return result


# Timeline / Manifest models for pipeline

@dataclass
class ManifestEntry:
    """A single entry in the timeline manifest."""
    asset_id: str
    timestamp: Optional[datetime] = None
    day_index: Optional[int] = None
    event_index: Optional[int] = None


@dataclass
class Manifest:
    """
    The timeline manifest built from approved assets.
    This is the output of the manifest building stage.
    """
    book_id: str
    entries: List[ManifestEntry] = field(default_factory=list)
    
    @property
    def asset_ids(self) -> List[str]:
        return [e.asset_id for e in self.entries]


@dataclass
class Event:
    """A group of photos from a specific event/location."""
    index: int
    entries: List[ManifestEntry] = field(default_factory=list)
    name: Optional[str] = None


@dataclass
class Day:
    """A day in the trip, containing multiple events."""
    index: int
    date: Optional[datetime] = None
    events: List[Event] = field(default_factory=list)
    
    @property
    def all_entries(self) -> List[ManifestEntry]:
        result = []
        for event in self.events:
            result.extend(event.entries)
        return result


# Theme / Render context

@dataclass
class Theme:
    """
    Theme configuration for rendering.
    
    This provides colors, fonts, and styling for the book.
    Can be extended later to support multiple themes.
    """
    name: str = "default"
    primary_color: str = "#1a1a1a"
    secondary_color: str = "#666666"
    background_color: str = "#ffffff"
    accent_color: str = "#3b82f6"
    font_family: str = "Arial, sans-serif"
    title_font_family: str = "Georgia, serif"
    
    # Page styling
    page_margin_mm: float = 10.0
    photo_gap_mm: float = 3.0
    
    # Cover styling
    cover_background_color: str = "#1a1a1a"
    cover_text_color: str = "#ffffff"


@dataclass
class RenderContext:
    """
    Context passed to layout and render functions.
    Contains size information and theme.
    """
    book_size: BookSize
    theme: Theme = field(default_factory=Theme)
    
    @property
    def page_width_mm(self) -> float:
        """Page width in millimeters."""
        sizes = {
            BookSize.SQUARE_8: 203.2,  # 8 inches
            BookSize.SQUARE_10: 254.0,  # 10 inches
            BookSize.PORTRAIT_8X10: 203.2,
            BookSize.LANDSCAPE_10X8: 254.0,
            BookSize.LARGE_11X14: 279.4,  # 11 inches
        }
        return sizes.get(self.book_size, 203.2)
    
    @property
    def page_height_mm(self) -> float:
        """Page height in millimeters."""
        sizes = {
            BookSize.SQUARE_8: 203.2,
            BookSize.SQUARE_10: 254.0,
            BookSize.PORTRAIT_8X10: 254.0,
            BookSize.LANDSCAPE_10X8: 203.2,
            BookSize.LARGE_11X14: 355.6,  # 14 inches
        }
        return sizes.get(self.book_size, 203.2)


# Layout output models

@dataclass
class LayoutRect:
    """A positioned rectangle in the layout."""
    x_mm: float
    y_mm: float
    width_mm: float
    height_mm: float
    asset_id: Optional[str] = None
    text: Optional[str] = None
    font_size: Optional[float] = None
    color: Optional[str] = None
    image_path: Optional[str] = None  # Absolute path for PDF rendering
    image_url: Optional[str] = None   # Web URL for live preview


@dataclass 
class PageLayout:
    """The computed layout for a single page."""
    page_index: int
    page_type: PageType
    background_color: Optional[str] = None
    elements: List[LayoutRect] = field(default_factory=list)
