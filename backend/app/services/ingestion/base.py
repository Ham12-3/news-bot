"""
Base ingestion service and classes.
Updated for UUID-based schema.
"""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any
from dataclasses import dataclass, field
from uuid import UUID
import hashlib

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.db.session import get_worker_session
from app.db.models import Source, RawItem, SourceType, ItemKind
from app.core.logging import get_logger
from app.core.metrics import track_items_ingested

logger = get_logger(__name__)


def compute_content_hash(text: str | None) -> bytes | None:
    """Compute SHA-256 hash of content for exact dedup."""
    if not text:
        return None
    return hashlib.sha256(text.encode("utf-8")).digest()


@dataclass
class NormalizedItem:
    """Common format for all ingested items."""
    external_id: str
    url: str
    title: str
    kind: ItemKind = ItemKind.UNKNOWN
    raw_text: str | None = None
    author: str | None = None
    published_at: datetime | None = None
    lang: str | None = None
    canonical_url: str | None = None
    raw_payload: dict = field(default_factory=dict)

    @property
    def content_hash(self) -> bytes | None:
        """Compute hash from title + raw_text for dedup."""
        content = f"{self.title or ''}\n{self.raw_text or ''}"
        return compute_content_hash(content.strip())


class BaseIngester(ABC):
    """Base class for all source ingesters."""

    source_type: SourceType = SourceType.RSS

    @abstractmethod
    async def fetch(self, source: Source) -> list[NormalizedItem]:
        """Fetch items from the source. Override in subclasses."""
        pass

    async def ingest(self, source_id: UUID) -> dict[str, Any]:
        """Main ingestion method."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get source
            result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            source = result.scalar_one_or_none()

            if not source:
                logger.error(f"Source {source_id} not found")
                return {"error": "Source not found"}

            if not source.enabled:
                logger.info(f"Source {source_id} is disabled, skipping")
                return {"skipped": True, "reason": "disabled"}

            # Fetch items
            try:
                items = await self.fetch(source)
            except Exception as e:
                logger.error(f"Failed to fetch from source {source_id}: {e}")
                return {"error": str(e)}

            # Store items - check for duplicates first
            inserted_count = 0
            for item in items:
                try:
                    # Check if item already exists
                    existing = await session.execute(
                        select(RawItem.id).where(
                            RawItem.source_id == source_id,
                            RawItem.external_id == item.external_id
                        ).limit(1)
                    )
                    if existing.scalar_one_or_none():
                        continue  # Skip existing item

                    # Insert new item
                    raw_item = RawItem(
                        source_id=source_id,
                        external_id=item.external_id,
                        kind=item.kind,
                        title=item.title,
                        url=item.url,
                        author=item.author,
                        published_at=item.published_at,
                        lang=item.lang,
                        raw_payload=item.raw_payload,
                        raw_text=item.raw_text,
                        canonical_url=item.canonical_url,
                        content_hash=item.content_hash,
                        status="new",
                    )
                    session.add(raw_item)
                    await session.flush()
                    inserted_count += 1
                except Exception as e:
                    await session.rollback()
                    logger.warning(f"Failed to insert item {item.external_id}: {e}")

            await session.commit()

            # Track metrics
            await track_items_ingested(self.source_type.value, inserted_count)

            logger.info(
                f"Ingestion complete for source {source_id}",
                extra={
                    "source_id": str(source_id),
                    "source_type": self.source_type.value,
                    "items_fetched": len(items),
                    "items_inserted": inserted_count,
                }
            )

            return {
                "source_id": str(source_id),
                "items_fetched": len(items),
                "items_inserted": inserted_count,
            }


class IngestionService:
    """Orchestrates ingestion from all sources."""

    def __init__(self):
        from .rss import RSSIngester
        from .hackernews import HackerNewsIngester
        from .reddit import RedditIngester

        self.ingesters = {
            SourceType.RSS: RSSIngester(),
            SourceType.API_HN: HackerNewsIngester(),
            SourceType.API_REDDIT: RedditIngester(),
        }

    async def ingest_all(self) -> dict[str, Any]:
        """Ingest from all enabled sources."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            result = await session.execute(
                select(Source).where(Source.enabled == True)
            )
            sources = result.scalars().all()

        results = {
            "sources_processed": 0,
            "items_ingested": 0,
            "errors": [],
        }

        for source in sources:
            ingester = self.ingesters.get(source.type)
            if not ingester:
                logger.warning(f"No ingester for source type: {source.type}")
                continue

            try:
                result = await ingester.ingest(source.id)
                results["sources_processed"] += 1
                results["items_ingested"] += result.get("items_inserted", 0)
            except Exception as e:
                results["errors"].append({
                    "source_id": str(source.id),
                    "error": str(e),
                })

        return results

    async def ingest_source(self, source_id: UUID) -> dict[str, Any]:
        """Ingest from a specific source."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            result = await session.execute(
                select(Source).where(Source.id == source_id)
            )
            source = result.scalar_one_or_none()

        if not source:
            return {"error": "Source not found"}

        ingester = self.ingesters.get(source.type)
        if not ingester:
            return {"error": f"No ingester for source type: {source.type}"}

        return await ingester.ingest(source_id)
