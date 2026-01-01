"""
Signals API routes - access high-signal news items.
"""

from uuid import UUID
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, RawItem, ItemScore, Source
from app.api.deps import get_db, get_current_user, get_current_user_optional
from app.services.scoring.service import ScoringService

router = APIRouter(prefix="/signals", tags=["signals"])


class SignalResponse(BaseModel):
    id: str
    title: str
    url: str
    source_name: str
    source_type: str
    published_at: str | None
    signal_score: float
    relevance: float
    velocity: float
    cross_source: float
    novelty: float
    content_preview: str | None


class SignalListResponse(BaseModel):
    signals: list[SignalResponse]
    total: int
    has_more: bool


class SignalDetailResponse(SignalResponse):
    raw_text: str | None
    canonical_url: str | None
    score_explanation: dict | None


@router.get("", response_model=SignalListResponse)
async def list_signals(
    min_score: float = Query(0.5, ge=0, le=1),
    category: str | None = None,
    source_type: str | None = None,
    hours: int = Query(24, ge=1, le=168),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_current_user_optional),
):
    """
    List high-signal items.
    Supports filtering by category, source type, and time range.
    """
    cutoff = datetime.utcnow() - timedelta(hours=hours)

    # Build query
    query = (
        select(RawItem, ItemScore, Source)
        .join(ItemScore, RawItem.id == ItemScore.raw_item_id)
        .join(Source, RawItem.source_id == Source.id)
        .where(RawItem.fetched_at >= cutoff)
        .where(ItemScore.signal_score >= min_score)
    )

    if category:
        query = query.where(Source.category == category)

    if source_type:
        query = query.where(Source.type == source_type)

    # Get total count (without limit/offset)
    count_query = select(RawItem.id).select_from(query.subquery())
    # For simplicity, we'll estimate total as limit + 1 if more results exist

    query = query.order_by(desc(ItemScore.signal_score)).offset(offset).limit(limit + 1)

    result = await db.execute(query)
    rows = result.all()

    has_more = len(rows) > limit
    rows = rows[:limit]

    signals = []
    for item, score, source in rows:
        signals.append(SignalResponse(
            id=str(item.id),
            title=item.title,
            url=item.url,
            source_name=source.name,
            source_type=source.type.value,
            published_at=item.published_at.isoformat() if item.published_at else None,
            signal_score=round(score.signal_score, 3),
            relevance=round(score.relevance_score, 3),
            velocity=round(score.velocity_score, 3),
            cross_source=round(score.cross_source_score, 3),
            novelty=round(score.novelty_score, 3),
            content_preview=item.raw_text[:300] if item.raw_text else None,
        ))

    return SignalListResponse(
        signals=signals,
        total=len(signals) + (1 if has_more else 0),
        has_more=has_more,
    )


@router.get("/top", response_model=list[SignalResponse])
async def get_top_signals(
    limit: int = Query(10, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
):
    """Get the top signals from the last 24 hours."""
    service = ScoringService()
    signals = await service.get_high_signals(limit=limit, min_score=0.6)

    return [SignalResponse(**s) for s in signals]


@router.get("/{signal_id}", response_model=SignalDetailResponse)
async def get_signal(
    signal_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """Get detailed information about a specific signal."""
    result = await db.execute(
        select(RawItem, ItemScore, Source)
        .join(ItemScore, RawItem.id == ItemScore.raw_item_id)
        .join(Source, RawItem.source_id == Source.id)
        .where(RawItem.id == signal_id)
    )
    row = result.first()

    if not row:
        raise HTTPException(status_code=404, detail="Signal not found")

    item, score, source = row

    return SignalDetailResponse(
        id=str(item.id),
        title=item.title,
        url=item.url,
        source_name=source.name,
        source_type=source.type.value,
        published_at=item.published_at.isoformat() if item.published_at else None,
        signal_score=round(score.signal_score, 3),
        relevance=round(score.relevance_score, 3),
        velocity=round(score.velocity_score, 3),
        cross_source=round(score.cross_source_score, 3),
        novelty=round(score.novelty_score, 3),
        content_preview=item.raw_text[:300] if item.raw_text else None,
        raw_text=item.raw_text,
        canonical_url=item.canonical_url,
        score_explanation=score.score_explanation,
    )


@router.get("/categories/stats")
async def get_category_stats(
    hours: int = Query(24, ge=1, le=168),
    db: AsyncSession = Depends(get_db),
):
    """Get signal statistics by category."""
    from sqlalchemy import func

    cutoff = datetime.utcnow() - timedelta(hours=hours)

    query = (
        select(
            Source.category,
            func.count(RawItem.id).label("count"),
            func.avg(ItemScore.signal_score).label("avg_score"),
        )
        .join(RawItem, Source.id == RawItem.source_id)
        .join(ItemScore, RawItem.id == ItemScore.raw_item_id)
        .where(RawItem.fetched_at >= cutoff)
        .group_by(Source.category)
    )

    result = await db.execute(query)
    rows = result.all()

    return [
        {
            "category": row.category or "uncategorized",
            "count": row.count,
            "avg_score": round(float(row.avg_score or 0), 3),
        }
        for row in rows
    ]
