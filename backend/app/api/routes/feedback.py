"""
Feedback API routes - user feedback on signals.
"""

from uuid import UUID
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.dialects.postgresql import insert

from app.db.models import User, UserFeedback, FeedbackKind, RawItem
from app.api.deps import get_db, get_current_user

router = APIRouter(prefix="/feedback", tags=["feedback"])


class FeedbackRequest(BaseModel):
    raw_item_id: str
    kind: str  # "like", "dislike", "save", "hide"


class FeedbackResponse(BaseModel):
    id: str
    raw_item_id: str
    kind: str
    created_at: str


class FeedbackListResponse(BaseModel):
    feedback: list[FeedbackResponse]
    total: int


@router.post("", response_model=FeedbackResponse)
async def submit_feedback(
    request: FeedbackRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Submit feedback on a signal.
    Feedback types:
    - like: User found this valuable
    - dislike: User didn't find this valuable
    - save: User wants to save for later
    - hide: User doesn't want to see similar content
    """
    # Validate feedback kind
    try:
        kind = FeedbackKind(request.kind)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid feedback kind. Must be one of: {[k.value for k in FeedbackKind]}",
        )

    # Verify item exists
    item_id = UUID(request.raw_item_id)
    result = await db.execute(
        select(RawItem.id).where(RawItem.id == item_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Item not found")

    # Upsert feedback (replace if exists for same user/item)
    stmt = insert(UserFeedback).values(
        user_id=current_user.id,
        raw_item_id=item_id,
        kind=kind,
    ).on_conflict_do_update(
        index_elements=["user_id", "raw_item_id"],
        set_={"kind": kind, "created_at": datetime.utcnow()},
    ).returning(UserFeedback)

    result = await db.execute(stmt)
    feedback = result.scalar_one()
    await db.commit()

    return FeedbackResponse(
        id=str(feedback.id),
        raw_item_id=str(feedback.raw_item_id),
        kind=feedback.kind.value,
        created_at=feedback.created_at.isoformat(),
    )


@router.get("", response_model=FeedbackListResponse)
async def list_feedback(
    kind: str | None = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List user's feedback."""
    query = select(UserFeedback).where(UserFeedback.user_id == current_user.id)

    if kind:
        try:
            feedback_kind = FeedbackKind(kind)
            query = query.where(UserFeedback.kind == feedback_kind)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid feedback kind")

    query = query.order_by(UserFeedback.created_at.desc())

    result = await db.execute(query)
    feedbacks = result.scalars().all()

    return FeedbackListResponse(
        feedback=[
            FeedbackResponse(
                id=str(f.id),
                raw_item_id=str(f.raw_item_id),
                kind=f.kind.value,
                created_at=f.created_at.isoformat(),
            )
            for f in feedbacks
        ],
        total=len(feedbacks),
    )


@router.delete("/{item_id}")
async def remove_feedback(
    item_id: UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Remove feedback on an item."""
    result = await db.execute(
        select(UserFeedback).where(
            UserFeedback.user_id == current_user.id,
            UserFeedback.raw_item_id == item_id,
        )
    )
    feedback = result.scalar_one_or_none()

    if not feedback:
        raise HTTPException(status_code=404, detail="Feedback not found")

    await db.delete(feedback)
    await db.commit()

    return {"success": True}


@router.get("/saved", response_model=FeedbackListResponse)
async def get_saved_items(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Get user's saved items."""
    query = (
        select(UserFeedback)
        .where(UserFeedback.user_id == current_user.id)
        .where(UserFeedback.kind == FeedbackKind.SAVE)
        .order_by(UserFeedback.created_at.desc())
    )

    result = await db.execute(query)
    feedbacks = result.scalars().all()

    return FeedbackListResponse(
        feedback=[
            FeedbackResponse(
                id=str(f.id),
                raw_item_id=str(f.raw_item_id),
                kind=f.kind.value,
                created_at=f.created_at.isoformat(),
            )
            for f in feedbacks
        ],
        total=len(feedbacks),
    )
