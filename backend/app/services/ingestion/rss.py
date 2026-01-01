"""
RSS/Atom feed ingester.
"""

import feedparser
from datetime import datetime
from dateutil import parser as date_parser
import httpx

from app.db.models import Source, SourceType, ItemKind
from app.core.logging import get_logger
from .base import BaseIngester, NormalizedItem

logger = get_logger(__name__)


class RSSIngester(BaseIngester):
    """Ingester for RSS/Atom feeds."""

    source_type = SourceType.RSS

    def __init__(self):
        self.timeout = 30

    async def fetch(self, source: Source) -> list[NormalizedItem]:
        """Fetch and parse RSS feed."""
        items = []

        try:
            # Fetch feed content
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    source.url,
                    headers={"User-Agent": "NewsBot/0.1 (RSS Reader)"},
                    follow_redirects=True,
                )
                response.raise_for_status()
                content = response.text

            # Parse feed
            feed = feedparser.parse(content)

            if feed.bozo and feed.bozo_exception:
                logger.warning(f"Feed parsing warning for {source.url}: {feed.bozo_exception}")

            for entry in feed.entries[:100]:  # Limit per source
                try:
                    item = self._parse_entry(entry, source)
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.warning(f"Failed to parse RSS entry: {e}")

        except httpx.HTTPError as e:
            logger.error(f"HTTP error fetching RSS {source.url}: {e}")
            raise
        except Exception as e:
            logger.error(f"Error fetching RSS {source.url}: {e}")
            raise

        return items

    def _parse_entry(self, entry: dict, source: Source) -> NormalizedItem | None:
        """Parse a single RSS entry into normalized format."""
        # Get unique ID
        external_id = entry.get("id") or entry.get("guid") or entry.get("link")
        if not external_id:
            return None

        # Get URL
        url = entry.get("link")
        if not url:
            return None

        # Get title
        title = entry.get("title", "").strip()
        if not title:
            return None

        # Get content snippet
        raw_text = None
        if entry.get("summary"):
            raw_text = entry.summary[:2000]
        elif entry.get("description"):
            raw_text = entry.description[:2000]

        # Get author
        author = entry.get("author") or entry.get("creator")

        # Get published date
        published_at = None
        for date_field in ["published_parsed", "updated_parsed", "created_parsed"]:
            if entry.get(date_field):
                try:
                    published_at = datetime(*entry[date_field][:6])
                    break
                except Exception:
                    pass

        # If no parsed date, try string parsing
        if not published_at:
            for date_field in ["published", "updated", "created"]:
                if entry.get(date_field):
                    try:
                        published_at = date_parser.parse(entry[date_field])
                        break
                    except Exception:
                        pass

        # Store full entry as raw_payload
        raw_payload = {
            "feed_title": getattr(entry, "source", {}).get("title") if hasattr(entry, "source") else None,
            "tags": [tag.term for tag in entry.get("tags", [])],
            "id": entry.get("id"),
            "guid": entry.get("guid"),
        }

        return NormalizedItem(
            external_id=str(external_id),
            url=url,
            title=title,
            kind=ItemKind.ARTICLE,
            raw_text=raw_text,
            author=author,
            published_at=published_at,
            canonical_url=url,
            raw_payload=raw_payload,
        )
