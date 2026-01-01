"""
Briefings API routes - user briefing management.
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import User, Briefing, BriefingItem, RawItem, Source
from app.api.deps import get_db, get_current_user
from app.services.briefing import BriefingService

router = APIRouter(prefix="/briefings", tags=["briefings"])


class BriefingItemResponse(BaseModel):
    id: str
    title: str
    url: str
    source: str


class BriefingResponse(BaseModel):
    id: str
    created_at: str
    summary_md: str


class BriefingDetailResponse(BriefingResponse):
    items: list[BriefingItemResponse]


class BriefingListResponse(BaseModel):
    briefings: list[BriefingResponse]
    total: int


class GenerateBriefingRequest(BaseModel):
    force: bool = False  # Force regeneration even if one exists today


@router.get("", response_model=BriefingListResponse)
async def list_briefings(
    limit: int = Query(10, ge=1, le=50),
    offset: int = Query(0, ge=0),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's briefings."""
    user_scope = f"user:{current_user.id}"
    query = (
        select(Briefing)
        .where(Briefing.scope == user_scope)
        .order_by(desc(Briefing.created_at))
        .offset(offset)
        .limit(limit)
    )

    result = await db.execute(query)
    briefings = result.scalars().all()

    return BriefingListResponse(
        briefings=[
            BriefingResponse(
                id=str(b.id),
                created_at=b.created_at.isoformat(),
                summary_md=b.summary_md,
            )
            for b in briefings
        ],
        total=len(briefings),
    )


@router.get("/latest", response_model=BriefingDetailResponse | None)
async def get_latest_briefing(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get the user's most recent briefing."""
    user_scope = f"user:{current_user.id}"
    result = await db.execute(
        select(Briefing)
        .where(Briefing.scope == user_scope)
        .order_by(desc(Briefing.created_at))
        .limit(1)
    )
    briefing = result.scalar_one_or_none()

    if not briefing:
        return None

    # Get linked items
    items_query = (
        select(RawItem, Source)
        .join(BriefingItem, BriefingItem.raw_item_id == RawItem.id)
        .join(Source, RawItem.source_id == Source.id)
        .where(BriefingItem.briefing_id == briefing.id)
    )
    items_result = await db.execute(items_query)
    items = items_result.all()

    return BriefingDetailResponse(
        id=str(briefing.id),
        created_at=briefing.created_at.isoformat(),
        summary_md=briefing.summary_md,
        items=[
            BriefingItemResponse(
                id=str(item.id),
                title=item.title or "",
                url=item.url or "",
                source=source.name,
            )
            for item, source in items
        ],
    )


@router.get("/{briefing_id}", response_model=BriefingDetailResponse)
async def get_briefing(
    briefing_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get a specific briefing by ID."""
    user_scope = f"user:{current_user.id}"
    result = await db.execute(
        select(Briefing).where(
            Briefing.id == briefing_id,
            Briefing.scope == user_scope,
        )
    )
    briefing = result.scalar_one_or_none()

    if not briefing:
        raise HTTPException(status_code=404, detail="Briefing not found")

    # Get linked items
    items_query = (
        select(RawItem, Source)
        .join(BriefingItem, BriefingItem.raw_item_id == RawItem.id)
        .join(Source, RawItem.source_id == Source.id)
        .where(BriefingItem.briefing_id == briefing.id)
    )
    items_result = await db.execute(items_query)
    items = items_result.all()

    return BriefingDetailResponse(
        id=str(briefing.id),
        created_at=briefing.created_at.isoformat(),
        summary_md=briefing.summary_md,
        items=[
            BriefingItemResponse(
                id=str(item.id),
                title=item.title or "",
                url=item.url or "",
                source=source.name,
            )
            for item, source in items
        ],
    )


@router.post("/generate", response_model=dict)
async def generate_briefing(
    request: GenerateBriefingRequest | None = None,
    current_user: User = Depends(get_current_user),
):
    """
    Generate a new briefing for the current user.
    By default, won't regenerate if one was already created today.
    """
    from datetime import datetime

    # Check if already has today's briefing (unless force=True)
    if not (request and request.force):
        service = BriefingService()
        existing = await service.get_user_briefings(current_user.id, limit=1)

        if existing:
            today = datetime.utcnow().date()
            latest_date = datetime.fromisoformat(existing[0]["created_at"]).date()

            if latest_date == today:
                return {
                    "message": "Briefing already exists for today",
                    "briefing_id": existing[0]["id"],
                    "generated": False,
                }

    # Generate new briefing
    service = BriefingService()
    result = await service.generate_for_user(current_user.id)

    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])

    return {
        "message": "Briefing generated successfully",
        "briefing_id": result.get("briefing_id"),
        "items_included": result.get("items_included"),
        "generated": True,
    }
