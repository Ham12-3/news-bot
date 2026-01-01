from sqlalchemy import select, update
from app.db.session import AsyncSessionLocal
from app.db.models import RawItem, ExtractedContent
from app.core.logging import get_logger
from .extractor import ContentExtractor
from .embeddings import EmbeddingService
from .dedup import DeduplicationService

logger = get_logger(__name__)


class ProcessingService:
    """Orchestrates all processing steps for raw items."""

    def __init__(self):
        self.extractor = ContentExtractor()
        self.embedding_service = EmbeddingService()
        self.dedup_service = DeduplicationService()

    async def process_all_pending(self) -> dict:
        """Process all unprocessed items."""
        results = {
            "items_processed": 0,
            "content_extracted": 0,
            "embeddings_generated": 0,
            "duplicates_found": 0,
            "errors": [],
        }

        async with AsyncSessionLocal() as session:
            # Get unprocessed items
            query = select(RawItem).where(RawItem.is_processed == False).limit(100)
            result = await session.execute(query)
            items = result.scalars().all()

            for item in items:
                try:
                    item_result = await self._process_item(session, item)
                    results["items_processed"] += 1

                    if item_result.get("content_extracted"):
                        results["content_extracted"] += 1
                    if item_result.get("embedding_generated"):
                        results["embeddings_generated"] += 1
                    if item_result.get("is_duplicate"):
                        results["duplicates_found"] += 1

                    # Mark as processed
                    item.is_processed = True
                    await session.commit()

                except Exception as e:
                    logger.error(f"Failed to process item {item.id}: {e}")
                    item.processing_error = str(e)
                    results["errors"].append({"item_id": item.id, "error": str(e)})
                    await session.commit()

        return results

    async def _process_item(self, session, item: RawItem) -> dict:
        """Process a single item through the pipeline."""
        result = {
            "content_extracted": False,
            "embedding_generated": False,
            "is_duplicate": False,
        }

        # Step 1: Extract content if it's an article link
        if self._should_extract_content(item):
            try:
                extracted = await self.extractor.extract(item.url)
                if extracted:
                    content = ExtractedContent(
                        raw_item_id=item.id,
                        clean_text=extracted["text"],
                        word_count=extracted["word_count"],
                        language=extracted.get("language", "en"),
                        extraction_method=extracted.get("method", "trafilatura"),
                        extraction_quality=extracted.get("quality", 1.0),
                    )
                    session.add(content)
                    result["content_extracted"] = True
            except Exception as e:
                logger.warning(f"Content extraction failed for {item.url}: {e}")

        # Step 2: Check for exact duplicates first
        is_exact_dup = await self.dedup_service.check_exact_duplicate(session, item)
        if is_exact_dup:
            result["is_duplicate"] = True
            return result

        # Step 3: Generate embedding
        try:
            text_for_embedding = self._get_text_for_embedding(item, result.get("content_extracted"))
            if text_for_embedding:
                await self.embedding_service.generate_for_item(session, item.id, text_for_embedding)
                result["embedding_generated"] = True
        except Exception as e:
            logger.warning(f"Embedding generation failed for item {item.id}: {e}")

        # Step 4: Check for semantic duplicates
        if result["embedding_generated"]:
            is_semantic_dup = await self.dedup_service.check_semantic_duplicate(session, item.id)
            if is_semantic_dup:
                result["is_duplicate"] = True

        return result

    def _should_extract_content(self, item: RawItem) -> bool:
        """Determine if we should try to extract article content."""
        # Skip if it's just a HN discussion or Reddit self-post
        if item.raw_payload.get("is_self"):
            return False

        # Skip HN items that are text posts (Ask HN, etc.)
        if item.raw_payload.get("type") == "story" and not item.url.startswith("http"):
            return False

        # Skip certain domains that don't need extraction
        skip_domains = ["twitter.com", "x.com", "youtube.com", "reddit.com"]
        for domain in skip_domains:
            if domain in item.url:
                return False

        return True

    def _get_text_for_embedding(self, item: RawItem, has_extracted: bool) -> str:
        """Get the best text to use for embedding."""
        # Prefer extracted content, fall back to title + snippet
        text_parts = [item.title]

        if item.content_snippet:
            text_parts.append(item.content_snippet)

        return " ".join(text_parts)
