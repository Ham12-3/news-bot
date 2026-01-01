from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel
from typing import Optional

from app.api.deps import get_db
from app.db.models import Source

router = APIRouter()


class SourceCreate(BaseModel):
    name: str
    source_type: str  # rss, hackernews, reddit
    url: str
    category: str
    enabled: bool = True
    credibility_score: float = 0.5
    config: dict = {}


class SourceResponse(BaseModel):
    id: int
    name: str
    source_type: str
    url: str
    category: str
    enabled: bool
    credibility_score: float
    config: dict

    class Config:
        from_attributes = True


@router.get("/sources", response_model=list[SourceResponse])
async def list_sources(
    category: Optional[str] = None,
    enabled_only: bool = True,
    db: AsyncSession = Depends(get_db),
):
    """List all registered sources."""
    query = select(Source)

    if category:
        query = query.where(Source.category == category)
    if enabled_only:
        query = query.where(Source.enabled == True)

    result = await db.execute(query)
    return result.scalars().all()


@router.post("/sources", response_model=SourceResponse)
async def create_source(
    source: SourceCreate,
    db: AsyncSession = Depends(get_db),
):
    """Register a new source."""
    db_source = Source(**source.model_dump())
    db.add(db_source)
    await db.commit()
    await db.refresh(db_source)
    return db_source


@router.delete("/sources/{source_id}")
async def delete_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete a source."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    source = result.scalar_one_or_none()

    if not source:
        raise HTTPException(status_code=404, detail="Source not found")

    await db.delete(source)
    await db.commit()

    return {"status": "deleted", "id": source_id}
