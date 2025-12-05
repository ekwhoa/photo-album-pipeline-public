"""
Asset repository backed by SQLAlchemy/SQLite.
"""
from datetime import datetime
from typing import List, Optional, Tuple
from sqlalchemy import func
from sqlalchemy.orm import Session

from domain.models import Asset, AssetMetadata, AssetStatus, AssetType
from repositories.models import AssetORM


def _metadata_to_dict(metadata: AssetMetadata) -> dict:
    return {
        "width": metadata.width,
        "height": metadata.height,
        "orientation": metadata.orientation,
        "taken_at": metadata.taken_at.isoformat() if metadata.taken_at else None,
        "camera": metadata.camera,
        "location": metadata.location,
        "gps_lat": metadata.gps_lat,
        "gps_lon": metadata.gps_lon,
        "gps_altitude": metadata.gps_altitude,
        "raw_exif": metadata.raw_exif,
    }


def _metadata_from_dict(data: Optional[dict]) -> AssetMetadata:
    if not data:
        return AssetMetadata()
    return AssetMetadata.from_dict(data)


def _asset_from_orm(orm: AssetORM) -> Asset:
    return Asset(
        id=orm.id,
        book_id=orm.book_id,
        status=AssetStatus(orm.status),
        type=AssetType(orm.type),
        file_path=orm.file_path,
        thumbnail_path=orm.thumbnail_path,
        metadata=_metadata_from_dict(orm.metadata_json),
        created_at=orm.created_at,
    )


class AssetsRepository:
    """CRUD operations for assets."""

    def list_assets(
        self, session: Session, book_id: str, status: Optional[AssetStatus] = None
    ) -> List[Asset]:
        query = session.query(AssetORM).filter(AssetORM.book_id == book_id)
        if status:
            query = query.filter(AssetORM.status == status.value)
        assets = query.order_by(AssetORM.created_at.desc()).all()
        return [_asset_from_orm(a) for a in assets]

    def create_asset(self, session: Session, asset: Asset) -> Asset:
        now = datetime.utcnow()
        orm = AssetORM(
            id=asset.id,
            book_id=asset.book_id,
            status=asset.status.value,
            type=asset.type.value,
            file_path=asset.file_path,
            thumbnail_path=asset.thumbnail_path,
            metadata_json=_metadata_to_dict(asset.metadata),
            created_at=asset.created_at or now,
        )
        session.add(orm)
        session.commit()
        session.refresh(orm)
        return _asset_from_orm(orm)

    def get_asset(self, session: Session, asset_id: str, book_id: str) -> Optional[Asset]:
        orm = (
            session.query(AssetORM)
            .filter(AssetORM.id == asset_id, AssetORM.book_id == book_id)
            .first()
        )
        return _asset_from_orm(orm) if orm else None

    def update_status(
        self, session: Session, asset_id: str, book_id: str, status: AssetStatus
    ) -> Optional[Asset]:
        orm = (
            session.query(AssetORM)
            .filter(AssetORM.id == asset_id, AssetORM.book_id == book_id)
            .first()
        )
        if not orm:
            return None
        orm.status = status.value
        # keep metadata JSON intact; only status changes
        session.add(orm)
        session.commit()
        session.refresh(orm)
        return _asset_from_orm(orm)

    def bulk_update_status(
        self, session: Session, asset_ids: List[str], book_id: str, status: AssetStatus
    ) -> List[Asset]:
        updated: List[Asset] = []
        if not asset_ids:
            return updated
        assets = (
            session.query(AssetORM)
            .filter(AssetORM.id.in_(asset_ids), AssetORM.book_id == book_id)
            .all()
        )
        for orm in assets:
            orm.status = status.value
            session.add(orm)
        session.commit()
        for orm in assets:
            session.refresh(orm)
            updated.append(_asset_from_orm(orm))
        return updated

    def delete_by_book(self, session: Session, book_id: str) -> None:
        session.query(AssetORM).filter(AssetORM.book_id == book_id).delete()
        session.commit()

    def count_by_book(self, session: Session, book_id: str) -> Tuple[int, int]:
        total = (
            session.query(func.count(AssetORM.id))
            .filter(AssetORM.book_id == book_id)
            .scalar()
            or 0
        )
        approved = (
            session.query(func.count(AssetORM.id))
            .filter(AssetORM.book_id == book_id, AssetORM.status == AssetStatus.APPROVED.value)
            .scalar()
            or 0
        )
        return total, approved
