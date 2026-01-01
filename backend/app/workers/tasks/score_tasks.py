"""
Scoring tasks - compute relevance and signal scores.
Queue: score
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def score_pending_items(self):
    """
    Score items that have been clustered but not yet scored.
    Runs every 15 minutes via Celery Beat.
    """
    import asyncio
    from app.services.scoring import ScoringService

    logger.info("Starting scoring for pending items")

    try:
        service = ScoringService()
        result = asyncio.run(service.score_all_pending())

        logger.info(
            "Scoring completed",
            extra={
                "items_scored": result.get("items_scored", 0),
                "high_signal_count": result.get("high_signal_count", 0),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Scoring batch failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def score_single_item(self, raw_item_id: str):
    """Score a single item."""
    import asyncio
    from app.services.scoring import ScoringService

    logger.info(f"Scoring item {raw_item_id}")

    try:
        service = ScoringService()
        result = asyncio.run(service.score_item(UUID(raw_item_id)))
        return result

    except Exception as e:
        logger.error(f"Scoring failed for item {raw_item_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def score_cluster(self, cluster_id: str):
    """Score all items in a cluster."""
    import asyncio
    from app.services.scoring import ScoringService

    logger.info(f"Scoring cluster {cluster_id}")

    try:
        service = ScoringService()
        result = asyncio.run(service.score_cluster(UUID(cluster_id)))
        return result

    except Exception as e:
        logger.error(f"Cluster scoring failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def compute_relevance_ai(self, raw_item_id: str):
    """
    Compute AI-based relevance score for an item.
    Uses cheap model (Haiku/GPT-3.5-turbo).
    """
    import asyncio
    from app.services.scoring import ScoringService

    logger.info(f"Computing AI relevance for item {raw_item_id}")

    try:
        service = ScoringService()
        result = asyncio.run(service.compute_ai_relevance(UUID(raw_item_id)))
        return result

    except Exception as e:
        logger.error(f"AI relevance scoring failed: {e}")
        raise self.retry(exc=e)
