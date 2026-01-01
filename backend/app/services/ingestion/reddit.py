"""
Reddit API ingester.
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


class RedditIngester(BaseIngester):
    """Ingester for Reddit via official API."""

    source_type = SourceType.API_REDDIT

    BASE_URL = "https://oauth.reddit.com"
    AUTH_URL = "https://www.reddit.com/api/v1/access_token"

    def __init__(self):
        self.timeout = 30
        self.max_items = settings.MAX_ITEMS_PER_SOURCE
        self._access_token = None

    async def _get_access_token(self) -> str:
        """Get OAuth access token for Reddit API."""
        if self._access_token:
            return self._access_token

        if not settings.REDDIT_CLIENT_ID or not settings.REDDIT_CLIENT_SECRET:
            raise ValueError("Reddit API credentials not configured")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                self.AUTH_URL,
                auth=(settings.REDDIT_CLIENT_ID, settings.REDDIT_CLIENT_SECRET),
                data={"grant_type": "client_credentials"},
                headers={"User-Agent": settings.REDDIT_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()
            self._access_token = data["access_token"]
            return self._access_token

    async def fetch(self, source: Source) -> list[NormalizedItem]:
        """Fetch posts from a subreddit."""
        items = []

        # Get subreddit from source metadata
        subreddit = source.source_metadata.get("subreddit")
        if not subreddit:
            # Try to extract from URL
            url = source.url or ""
            if "/r/" in url:
                subreddit = url.split("/r/")[1].split("/")[0]
            else:
                logger.error(f"Cannot determine subreddit from source {source.id}")
                return []

        sort = source.source_metadata.get("sort", "hot")
        time_filter = source.source_metadata.get("time", "day")

        try:
            token = await self._get_access_token()
        except Exception as e:
            logger.warning(f"Reddit auth failed, trying unauthenticated: {e}")
            return await self._fetch_unauthenticated(subreddit, sort, time_filter)

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": settings.REDDIT_USER_AGENT,
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"{self.BASE_URL}/r/{subreddit}/{sort}"
            params = {"limit": self.max_items, "t": time_filter}

            response = await client.get(url, headers=headers, params=params)
            response.raise_for_status()
            data = response.json()

            for post in data.get("data", {}).get("children", []):
                try:
                    item = self._parse_post(post["data"])
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.warning(f"Failed to parse Reddit post: {e}")

        return items

    async def _fetch_unauthenticated(
        self, subreddit: str, sort: str, time_filter: str
    ) -> list[NormalizedItem]:
        """Fallback to public JSON endpoint (rate limited)."""
        items = []

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            url = f"https://www.reddit.com/r/{subreddit}/{sort}.json"
            params = {"limit": min(25, self.max_items), "t": time_filter}

            response = await client.get(
                url,
                params=params,
                headers={"User-Agent": settings.REDDIT_USER_AGENT},
            )
            response.raise_for_status()
            data = response.json()

            for post in data.get("data", {}).get("children", []):
                try:
                    item = self._parse_post(post["data"])
                    if item:
                        items.append(item)
                except Exception as e:
                    logger.warning(f"Failed to parse Reddit post: {e}")

        return items

    def _parse_post(self, post: dict) -> NormalizedItem | None:
        """Parse a Reddit post into normalized format."""
        post_id = post.get("id")
        if not post_id:
            return None

        title = post.get("title", "").strip()
        if not title:
            return None

        # Skip removed/deleted posts
        if post.get("removed_by_category") or post.get("removed"):
            return None

        # Get URL (external link or Reddit comments)
        url = post.get("url")
        if not url or url.startswith("/r/"):
            url = f"https://reddit.com{post.get('permalink', '')}"

        # Determine item kind
        kind = ItemKind.POST
        if not post.get("is_self", False) and post.get("url"):
            kind = ItemKind.ARTICLE

        # Get content
        raw_text = post.get("selftext", "")[:2000] if post.get("selftext") else None

        # Parse timestamp
        published_at = None
        if post.get("created_utc"):
            published_at = datetime.utcfromtimestamp(post["created_utc"])

        # Store full API response as raw_payload
        raw_payload = {
            "reddit_id": post_id,
            "subreddit": post.get("subreddit"),
            "score": post.get("score", 0),
            "upvote_ratio": post.get("upvote_ratio", 0),
            "num_comments": post.get("num_comments", 0),
            "is_self": post.get("is_self", False),
            "link_flair_text": post.get("link_flair_text"),
            "permalink": f"https://reddit.com{post.get('permalink', '')}",
            "over_18": post.get("over_18", False),
            "spoiler": post.get("spoiler", False),
        }

        # Canonical URL is the external link for link posts
        canonical_url = None
        if not post.get("is_self", False):
            canonical_url = post.get("url")

        return NormalizedItem(
            external_id=post_id,
            url=url,
            title=title,
            kind=kind,
            raw_text=raw_text,
            author=post.get("author"),
            published_at=published_at,
            canonical_url=canonical_url,
            raw_payload=raw_payload,
        )

    async def ingest_subreddits(self, subreddits: list[str]) -> dict:
        """
        Convenience method to ingest from multiple subreddits.
        Creates sources if needed.
        """
        results = {"subreddits": [], "total_items": 0}

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            for subreddit in subreddits:
                # Find or create source
                result = await session.execute(
                    select(Source).where(
                        Source.type == SourceType.API_REDDIT,
                        Source.url.contains(f"/r/{subreddit}")
                    )
                )
                source = result.scalar_one_or_none()

                if not source:
                    source = Source(
                        name=f"Reddit - r/{subreddit}",
                        type=SourceType.API_REDDIT,
                        url=f"https://reddit.com/r/{subreddit}",
                        category="tech",
                        credibility_tier=3,
                        source_metadata={"subreddit": subreddit, "sort": "hot"},
                    )
                    session.add(source)
                    await session.commit()
                    await session.refresh(source)

                # Ingest
                result = await self.ingest(source.id)
                results["subreddits"].append({
                    "subreddit": subreddit,
                    "items": result.get("items_inserted", 0),
                })
                results["total_items"] += result.get("items_inserted", 0)

        return results
