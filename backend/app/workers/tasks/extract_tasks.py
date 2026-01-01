"""
Extraction tasks - extract clean text from articles.
Queue: extract
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def extract_pending_items(self):
    """
    Extract content from all items with status='new'.
    Runs every 10 minutes via Celery Beat.
    """
    import asyncio
    from app.services.processing.extractor import ContentExtractor

    logger.info("Starting extraction for pending items")

    try:
        extractor = ContentExtractor()
        result = asyncio.run(extractor.extract_all_pending())

        logger.info(
            "Extraction completed",
            extra={
                "items_processed": result.get("items_processed", 0),
                "extracted": result.get("extracted", 0),
                "failed": result.get("failed", 0),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Extraction batch failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=15)
def extract_single_item(self, raw_item_id: str):
    """Extract content from a single item."""
    import asyncio
    from app.services.processing.extractor import ContentExtractor

    logger.info(f"Extracting content for item {raw_item_id}")

    try:
        extractor = ContentExtractor()
        result = asyncio.run(extractor.extract_item(UUID(raw_item_id)))
        return result

    except Exception as e:
        logger.error(f"Extraction failed for item {raw_item_id}: {e}")
        raise self.retry(exc=e)
