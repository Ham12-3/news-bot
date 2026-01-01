"""
Embedding tasks - generate vector embeddings.
Queue: embed
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def embed_pending_items(self):
    """
    Generate embeddings for items with status='extracted' that don't have embeddings.
    Runs every 15 minutes via Celery Beat.
    """
    import asyncio
    from app.services.processing.embeddings import EmbeddingService

    logger.info("Starting embedding generation for pending items")

    try:
        service = EmbeddingService()
        result = asyncio.run(service.embed_all_pending())

        logger.info(
            "Embedding generation completed",
            extra={
                "items_processed": result.get("items_processed", 0),
                "embeddings_created": result.get("embeddings_created", 0),
                "tokens_used": result.get("tokens_used", 0),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Embedding batch failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def embed_single_item(self, raw_item_id: str):
    """Generate embedding for a single item."""
    import asyncio
    from app.services.processing.embeddings import EmbeddingService

    logger.info(f"Generating embedding for item {raw_item_id}")

    try:
        service = EmbeddingService()
        result = asyncio.run(service.embed_item(UUID(raw_item_id)))
        return result

    except Exception as e:
        logger.error(f"Embedding failed for item {raw_item_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def embed_batch(self, raw_item_ids: list[str]):
    """Generate embeddings for a batch of items."""
    import asyncio
    from app.services.processing.embeddings import EmbeddingService

    logger.info(f"Generating embeddings for {len(raw_item_ids)} items")

    try:
        service = EmbeddingService()
        uuids = [UUID(id) for id in raw_item_ids]
        result = asyncio.run(service.embed_batch(uuids))
        return result

    except Exception as e:
        logger.error(f"Batch embedding failed: {e}")
        raise self.retry(exc=e)
