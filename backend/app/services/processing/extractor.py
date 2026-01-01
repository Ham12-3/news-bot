from uuid import UUID
import httpx
from sqlalchemy import select, update

from app.core.logging import get_logger
from app.core.config import settings
from app.db.session import get_worker_session
from app.db.models import RawItem, ExtractedContent

logger = get_logger(__name__)


class ContentExtractor:
    """Extracts clean text content from article URLs."""

    def __init__(self):
        self.timeout = 30

    async def extract(self, url: str) -> dict | None:
        """
        Extract clean text from a URL.
        Returns dict with text, word_count, method, quality.
        """
        try:
            # Fetch the page
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.get(
                    url,
                    headers={
                        "User-Agent": "Mozilla/5.0 (compatible; NewsBot/0.1)",
                    },
                    follow_redirects=True,
                )
                response.raise_for_status()
                html = response.text

            # Try trafilatura first (best quality)
            result = self._extract_with_trafilatura(html, url)

            if result and result.get("word_count", 0) > 50:
                return result

            # Fall back to readability
            result = self._extract_with_readability(html, url)

            if result and result.get("word_count", 0) > 50:
                return result

            return None

        except httpx.HTTPError as e:
            logger.warning(f"HTTP error extracting {url}: {e}")
            return None
        except Exception as e:
            logger.warning(f"Extraction failed for {url}: {e}")
            return None

    def _extract_with_trafilatura(self, html: str, url: str) -> dict | None:
        """Extract using trafilatura library."""
        try:
            import trafilatura

            text = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=False,
                no_fallback=False,
                favor_precision=True,
            )

            if not text:
                return None

            word_count = len(text.split())

            return {
                "text": text,
                "word_count": word_count,
                "method": "trafilatura",
                "quality": 0.9,
            }

        except Exception as e:
            logger.debug(f"Trafilatura extraction failed: {e}")
            return None

    def _extract_with_readability(self, html: str, url: str) -> dict | None:
        """Extract using readability-lxml library."""
        try:
            from readability import Document
            from bs4 import BeautifulSoup

            doc = Document(html)
            content_html = doc.summary()

            # Convert to plain text
            soup = BeautifulSoup(content_html, "lxml")
            text = soup.get_text(separator=" ", strip=True)

            if not text:
                return None

            word_count = len(text.split())

            return {
                "text": text,
                "word_count": word_count,
                "method": "readability",
                "quality": 0.7,
            }

        except Exception as e:
            logger.debug(f"Readability extraction failed: {e}")
            return None

    async def extract_all_pending(self, limit: int = 100) -> dict:
        """
        Extract content from all items with status='new'.
        Returns stats about the extraction process.
        """
        result = {
            "items_processed": 0,
            "extracted": 0,
            "failed": 0,
            "skipped": 0,
        }

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get items that need extraction
            query = select(RawItem).where(
                RawItem.status == "new"
            ).limit(limit)

            items = (await session.execute(query)).scalars().all()

            for item in items:
                result["items_processed"] += 1

                try:
                    # Skip items without URLs
                    if not item.url:
                        result["skipped"] += 1
                        await session.execute(
                            update(RawItem)
                            .where(RawItem.id == item.id)
                            .values(status="extracted")
                        )
                        continue

                    # Extract content
                    extracted = await self.extract(item.url)

                    if extracted:
                        # Save extracted content
                        content = ExtractedContent(
                            raw_item_id=item.id,
                            final_url=item.url,
                            title=item.title,
                            text=extracted["text"],
                            word_count=extracted["word_count"],
                            extraction_meta={
                                "method": extracted["method"],
                                "quality": extracted["quality"],
                            }
                        )
                        session.add(content)
                        result["extracted"] += 1
                    else:
                        result["failed"] += 1

                    # Update status
                    await session.execute(
                        update(RawItem)
                        .where(RawItem.id == item.id)
                        .values(status="extracted")
                    )

                except Exception as e:
                    logger.warning(f"Failed to extract item {item.id}: {e}")
                    result["failed"] += 1

            await session.commit()

        return result

    async def extract_item(self, raw_item_id: UUID) -> dict:
        """Extract content from a single item by ID."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get the item
            query = select(RawItem).where(RawItem.id == raw_item_id)
            item = (await session.execute(query)).scalar_one_or_none()

            if not item:
                return {"success": False, "error": "Item not found"}

            if not item.url:
                return {"success": False, "error": "Item has no URL"}

            # Extract content
            extracted = await self.extract(item.url)

            if not extracted:
                return {"success": False, "error": "Extraction failed"}

            # Save extracted content
            content = ExtractedContent(
                raw_item_id=item.id,
                final_url=item.url,
                title=item.title,
                text=extracted["text"],
                word_count=extracted["word_count"],
                extraction_meta={
                    "method": extracted["method"],
                    "quality": extracted["quality"],
                }
            )
            session.add(content)

            # Update status
            await session.execute(
                update(RawItem)
                .where(RawItem.id == item.id)
                .values(status="extracted")
            )

            await session.commit()

            return {
                "success": True,
                "word_count": extracted["word_count"],
                "method": extracted["method"],
            }
