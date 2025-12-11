"""
Books API routes.
"""
import logging
from typing import List, Optional
from datetime import date, datetime
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from db import SessionLocal
from domain.models import Book, BookSize, PageType
from repositories import BooksRepository, AssetsRepository
from storage.file_storage import FileStorage
from services.book_planner import plan_book, get_book_segment_debug
from services.timeline import TimelineService
from services.itinerary import build_book_itinerary, build_place_candidates, PlaceCandidate
from services.places_enrichment import enrich_place_candidates_with_names
from services.curation import filter_approved
from settings import settings

router = APIRouter()
books_repo = BooksRepository()
assets_repo = AssetsRepository()
storage = FileStorage()
logger = logging.getLogger(__name__)


class BookCreate(BaseModel):
    title: str
    size: str = "8x8"


class BookResponse(BaseModel):
    id: str
    title: str
    size: str
    created_at: str
    updated_at: str
    asset_count: int
    approved_count: int
    last_generated: Optional[str] = None
    pdf_path: Optional[str] = None


def book_to_response(book: Book, asset_count: int, approved_count: int) -> BookResponse:
    """Convert domain Book to API response."""
    return BookResponse(
        id=book.id,
        title=book.title,
        size=book.size.value,
        created_at=book.created_at.isoformat(),
        updated_at=book.updated_at.isoformat(),
        asset_count=asset_count,
        approved_count=approved_count,
        last_generated=book.last_generated.isoformat() if book.last_generated else None,
        pdf_path=book.pdf_path,
    )


class DedupeDebugResponse(BaseModel):
    book_id: str
    approved_count: int
    considered_count: int
    used_count: int
    auto_hidden_clusters_count: int
    auto_hidden_hidden_assets_count: int
    auto_hidden_duplicate_clusters: List[dict]


class SegmentDebugSegment(BaseModel):
    segment_index: int
    asset_ids: List[str]
    start_taken_at: Optional[datetime]
    end_taken_at: Optional[datetime]
    duration_minutes: Optional[float]
    approx_distance_km: Optional[float]


class SegmentDebugDay(BaseModel):
    day_index: int
    date: Optional[date]
    asset_ids: List[str]
    segments: List[SegmentDebugSegment]


class BookSegmentDebugResponse(BaseModel):
    book_id: str
    total_days: int
    total_assets: int
    days: List[SegmentDebugDay]


class UsageDebugResponse(BaseModel):
    book_id: str
    approved_asset_ids: List[str]
    used_asset_ids: List[str]
    hidden_asset_ids: List[str]
    missing_asset_ids: List[str]
    pages: List[dict]


class ItineraryStopResponse(BaseModel):
    segment_index: int
    distance_km: float
    duration_hours: float
    location_short: Optional[str] = None
    location_full: Optional[str] = None
    polyline: Optional[List[tuple[float, float]]] = None
    kind: str = "local"
    time_bucket: Optional[str] = None


class ItineraryLocationResponse(BaseModel):
    location_short: Optional[str] = None
    location_full: Optional[str] = None


class ItineraryDayResponse(BaseModel):
    day_index: int
    date_iso: str
    photos_count: int
    segments_total_distance_km: float
    segments_total_duration_hours: float
    location_short: Optional[str] = None
    location_full: Optional[str] = None
    locations: List[ItineraryLocationResponse] = []
    stops: List[ItineraryStopResponse]


class BookItineraryResponse(BaseModel):
    book_id: str
    days: List[ItineraryDayResponse]


class PlaceCandidateThumbnailSchema(BaseModel):
    id: str
    thumbnail_path: Optional[str] = None
    file_path: Optional[str] = None


class PlaceCandidateSchema(BaseModel):
    center_lat: float
    center_lon: float
    total_duration_hours: float
    total_photos: int
    total_distance_km: float
    visit_count: int
    day_indices: List[int]
    thumbnails: List[PlaceCandidateThumbnailSchema] = Field(default_factory=list)
    best_place_name: Optional[str] = None


@router.get("/{book_id}/dedupe_debug", response_model=DedupeDebugResponse)
async def dedupe_debug(book_id: str):
    """Return dedupe metadata for a book without altering existing endpoints."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        planned = plan_book(
            book_id=book.id,
            title=book.title,
            size=book.size,
            days=days,
            assets=approved_assets,
        )

        total, approved_count = assets_repo.count_by_book(session, book.id)
        considered_count = planned.considered_count or approved_count
        used_count = planned.used_count or 0
        return DedupeDebugResponse(
            book_id=book.id,
            approved_count=approved_count,
            considered_count=considered_count,
            used_count=used_count,
            auto_hidden_clusters_count=planned.auto_hidden_clusters_count,
            auto_hidden_hidden_assets_count=planned.auto_hidden_hidden_assets_count,
            auto_hidden_duplicate_clusters=planned.auto_hidden_duplicate_clusters,
        )


@router.get("/{book_id}/usage_debug", response_model=UsageDebugResponse)
async def usage_debug(book_id: str):
    """Debug endpoint: show asset usage (approved/used/hidden/missing) plus page summaries."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        approved_ids = [a.id for a in approved_assets]

        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        planned = plan_book(
            book_id=book.id,
            title=book.title,
            size=book.size,
            days=days,
            assets=approved_assets,
        )

        # Collect used asset IDs from all pages
        used_ids: set[str] = set()
        for page in planned.get_all_pages():
            payload_ids = page.payload.get("asset_ids") or []
            hero_id = page.payload.get("hero_asset_id")
            for aid in payload_ids:
                used_ids.add(aid)
            if hero_id:
                used_ids.add(hero_id)

        hidden_ids = {
            hid
            for cluster in planned.auto_hidden_duplicate_clusters
            for hid in cluster.get("hidden_asset_ids", [])
        }
        missing_ids = sorted(list(set(approved_ids) - used_ids - hidden_ids))

        pages_debug = [
            {
                "index": p.index,
                "page_type": p.page_type.value,
                "asset_ids": p.payload.get("asset_ids") or [],
                "hero_asset_id": p.payload.get("hero_asset_id"),
                "spread_slot": p.spread_slot,
            }
            for p in planned.get_all_pages()
        ]

        print("[usage_debug] missing asset ids:", missing_ids)
        print("[usage_debug] last pages:", pages_debug[-5:])

        return UsageDebugResponse(
            book_id=book.id,
            approved_asset_ids=approved_ids,
            used_asset_ids=sorted(list(used_ids)),
            hidden_asset_ids=sorted(list(hidden_ids)),
            missing_asset_ids=missing_ids,
            pages=pages_debug,
        )


@router.get("/{book_id}/segment_debug", response_model=BookSegmentDebugResponse)
async def segment_debug(book_id: str):
    """Debug endpoint: show per-day segments based on time gaps and distance jumps."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        data = get_book_segment_debug(book_id, days, approved_assets)
        return BookSegmentDebugResponse(**data)


@router.get("/{book_id}/itinerary", response_model=BookItineraryResponse)
async def itinerary(book_id: str):
    """Return a structured itinerary grouped by day with segment summaries."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        approved_assets = filter_approved(approved_assets)
        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        itinerary_days = build_book_itinerary(book, days, approved_assets)
        response_days = [
            ItineraryDayResponse(
                day_index=d.day_index,
                date_iso=d.date_iso,
                photos_count=d.photos_count,
                segments_total_distance_km=d.segments_total_distance_km,
                segments_total_duration_hours=d.segments_total_duration_hours,
                location_short=d.location_short,
                location_full=d.location_full,
                locations=[
                    ItineraryLocationResponse(
                        location_short=loc.location_short,
                        location_full=loc.location_full,
                    )
                    for loc in (d.locations or [])
                ],
                stops=[
                    ItineraryStopResponse(
                        segment_index=s.segment_index,
                        distance_km=s.distance_km,
                        duration_hours=s.duration_hours,
                        location_short=s.location_short,
                        location_full=s.location_full,
                        polyline=s.polyline,
                        kind=s.kind,
                        time_bucket=s.time_bucket,
                    )
                    for s in d.stops
                ],
            )
            for d in itinerary_days
        ]

        return BookItineraryResponse(book_id=book.id, days=response_days)


@router.get(
    "/{book_id}/places-debug",
    response_model=List[PlaceCandidateSchema],
)
async def get_book_places_debug(book_id: str):
    """Debug endpoint: aggregate place candidates from itinerary data."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")

        approved_assets = assets_repo.list_assets(session, book_id, status=None)
        approved_assets = filter_approved(approved_assets)
        timeline_service = TimelineService()
        days = timeline_service.organize_assets_by_day(approved_assets)

        itinerary_days = build_book_itinerary(book, days, approved_assets)
        candidates = build_place_candidates(itinerary_days, approved_assets)
        if settings.PLACES_LOOKUP_ENABLED and candidates:
            MAX_LOOKUPS = 10
            logger.debug("places-debug: enriching top %d places with Nominatim", min(len(candidates), MAX_LOOKUPS))
            candidates = enrich_place_candidates_with_names(candidates, max_lookups=MAX_LOOKUPS)
        return [
            PlaceCandidateSchema(
                center_lat=c.center_lat,
                center_lon=c.center_lon,
                total_duration_hours=c.total_duration_hours,
                total_photos=c.total_photos,
                total_distance_km=c.total_distance_km,
                visit_count=c.visit_count,
                day_indices=c.day_indices,
                thumbnails=[
                    PlaceCandidateThumbnailSchema(
                        id=thumb.id,
                        thumbnail_path=thumb.thumbnail_path,
                        file_path=thumb.file_path,
                    )
                    for thumb in (c.thumbnails or [])
                ],
                best_place_name=c.best_place_name,
            )
            for c in candidates
        ]


@router.get("", response_model=List[BookResponse])
async def list_books():
    """List all books."""
    with SessionLocal() as session:
        books = books_repo.list_books(session)
        responses = []
        for book in books:
            total, approved = assets_repo.count_by_book(session, book.id)
            responses.append(book_to_response(book, total, approved))
        return responses


@router.post("", response_model=BookResponse)
async def create_book(data: BookCreate):
    """Create a new book."""
    try:
        size = BookSize(data.size)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid size: {data.size}")
    
    book = Book(
        id=Book.generate_id(),
        title=data.title,
        size=size,
    )
    with SessionLocal() as session:
        saved = books_repo.create_book(session, book)
        total, approved = assets_repo.count_by_book(session, saved.id)
        return book_to_response(saved, total, approved)


@router.get("/{book_id}", response_model=BookResponse)
async def get_book(book_id: str):
    """Get a book by ID."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        total, approved = assets_repo.count_by_book(session, book.id)
        return book_to_response(book, total, approved)


@router.delete("/{book_id}")
async def delete_book(book_id: str):
    """Delete a book and all its assets."""
    with SessionLocal() as session:
        book = books_repo.get_book(session, book_id)
        if not book:
            raise HTTPException(status_code=404, detail="Book not found")
        books_repo.delete_book(session, book_id)
        # Best-effort file cleanup
        try:
            storage.delete_book_files(book_id)
        except Exception as e:
            print(f"[delete_book] Failed to delete media for book {book_id}: {e}")
        return {"status": "deleted"}
