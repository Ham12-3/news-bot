"""
Hacker News API ingester.
"""

from datetime import datetime
from uuid import UUID
import httpx

from sqlalchemy import select

from app.db.session import get_worker_session
from app.db.models import Source, SourceType, ItemKind
from app.core.logging import get_logger
from app.core.config import settings
from .base import BaseIngester, NormalizedItem

logger = get_logger(__name__)


class HackerNewsIngester(BaseIngester):
    """Ingester for Hacker News via official Firebase API."""

    source_type = SourceType.API_HN

    BASE_URL = "https://hacker-news.firebaseio.com/v0"
    HN_ITEM_URL = "https://news.ycombinator.com/item?id="

    def __init__(self):
        self.timeout = 30
        self.max_items = settings.MAX_ITEMS_PER_SOURCE

    async def fetch(self, source: Source) -> list[NormalizedItem]:
        """Fetch top/new stories from Hacker News."""
        items = []

        # Determine which stories to fetch based on source metadata
        story_type = source.source_metadata.get("story_type", "top")  # top, new, best
        endpoint = f"{self.BASE_URL}/{story_type}stories.json"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Get story IDs
            response = await client.get(endpoint)
            response.raise_for_status()
            story_ids = response.json()[:self.max_items]

            # Fetch each story
            for story_id in story_ids:
                try:
                    item = await self._fetch_story(client, story_id)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.warning(f"Failed to fetch HN story {story_id}: {e}")

        return items

    async def _fetch_story(self, client: httpx.AsyncClient, story_id: int) -> NormalizedItem | None:
        """Fetch a single story from HN API."""
        url = f"{self.BASE_URL}/item/{story_id}.json"
        response = await client.get(url)
        response.raise_for_status()
        story = response.json()

        if not story or story.get("type") != "story":
            return None

        # Skip deleted or dead stories
        if story.get("deleted") or story.get("dead"):
            return None

        title = story.get("title", "").strip()
        if not title:
            return None

        # HN stories can be links or text posts (Ask HN, Show HN)
        item_url = story.get("url") or f"{self.HN_ITEM_URL}{story_id}"

        # Determine item kind
        kind = ItemKind.ARTICLE
        if title.startswith("Ask HN:") or title.startswith("Tell HN:"):
            kind = ItemKind.POST
        elif title.startswith("Show HN:"):
            kind = ItemKind.POST

        # Get text content for text posts
        raw_text = story.get("text")

        # Parse timestamp
        published_at = None
        if story.get("time"):
            published_at = datetime.utcfromtimestamp(story["time"])

        # Store full API response as raw_payload
        raw_payload = {
            "hn_id": story_id,
            "score": story.get("score", 0),
            "descendants": story.get("descendants", 0),
            "by": story.get("by"),
            "type": story.get("type"),
            "hn_url": f"{self.HN_ITEM_URL}{story_id}",
            "kids": story.get("kids", [])[:10],
        }

        return NormalizedItem(
            external_id=str(story_id),
            url=item_url,
            title=title,
            kind=kind,
            raw_text=raw_text,
            author=story.get("by"),
            published_at=published_at,
            canonical_url=story.get("url"),
            raw_payload=raw_payload,
        )

    async def ingest_frontpage(self) -> dict:
        """
        Convenience method to ingest HN front page.
        Creates a virtual source if needed.
        """
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Find or create HN source
            result = await session.execute(
                select(Source).where(
                    Source.type == SourceType.API_HN,
                    Source.name == "Hacker News - Top"
                )
            )
            source = result.scalar_one_or_none()

            if not source:
                source = Source(
                    name="Hacker News - Top",
                    type=SourceType.API_HN,
                    url="https://news.ycombinator.com",
                    category="tech",
                    credibility_tier=2,
                    source_metadata={"story_type": "top"},
                )
                session.add(source)
                await session.commit()
                await session.refresh(source)

        return await self.ingest(source.id)
