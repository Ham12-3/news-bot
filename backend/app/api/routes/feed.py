from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc
from pydantic import BaseModel
from datetime import datetime
from typing import Optional

from app.api.deps import get_db
from app.db.models import RawItem, ItemScore, Source

router = APIRouter()


class FeedItem(BaseModel):
    id: int
    title: str
    url: str
    source_name: str
    source_type: str
    category: str
    published_at: Optional[datetime]
    fetched_at: datetime
    signal_score: float
    content_snippet: Optional[str]
    metadata: dict

    class Config:
        from_attributes = True


class FeedResponse(BaseModel):
    items: list[FeedItem]
    total: int
    page: int
    page_size: int


@router.get("/feed", response_model=FeedResponse)
async def get_feed(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    category: Optional[str] = None,
    min_score: float = Query(0.0, ge=0.0, le=1.0),
    db: AsyncSession = Depends(get_db),
):
    """Get the ranked signal feed."""
    # Build query joining raw items with scores and sources
    query = (
        select(
            RawItem.id,
            RawItem.title,
            RawItem.url,
            RawItem.content_snippet,
            RawItem.published_at,
            RawItem.fetched_at,
            RawItem.raw_payload,
            Source.name.label("source_name"),
            Source.type.label("source_type"),
            Source.category,
            ItemScore.signal_score,
        )
        .join(Source, RawItem.source_id == Source.id)
        .outerjoin(ItemScore, RawItem.id == ItemScore.raw_item_id)
        .where(RawItem.is_processed == True)
    )

    if category:
        query = query.where(Source.category == category)

    if min_score > 0:
        query = query.where(ItemScore.signal_score >= min_score)

    # Order by signal score, then by recency
    query = query.order_by(
        desc(ItemScore.signal_score),
        desc(RawItem.published_at)
    )

    # Count total
    # For simplicity, we'll estimate - in production use a count query
    total = 100  # Placeholder

    # Paginate
    offset = (page - 1) * page_size
    query = query.offset(offset).limit(page_size)

    result = await db.execute(query)
    rows = result.all()

    items = [
        FeedItem(
            id=row.id,
            title=row.title,
            url=row.url,
            source_name=row.source_name,
            source_type=row.source_type,
            category=row.category,
            published_at=row.published_at,
            fetched_at=row.fetched_at,
            signal_score=row.signal_score or 0.0,
            content_snippet=row.content_snippet,
            metadata=row.raw_payload or {},
        )
        for row in rows
    ]

    return FeedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )
