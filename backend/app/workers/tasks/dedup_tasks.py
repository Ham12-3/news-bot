"""
Deduplication tasks - cluster similar items.
Queue: score
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def cluster_pending_items(self):
    """
    Cluster items with embeddings that haven't been clustered yet.
    Runs every 15 minutes via Celery Beat.
    """
    import asyncio
    from app.services.processing.dedup import DeduplicationService

    logger.info("Starting clustering for pending items")

    try:
        service = DeduplicationService()
        result = asyncio.run(service.cluster_all_pending())

        logger.info(
            "Clustering completed",
            extra={
                "items_processed": result.get("items_processed", 0),
                "clusters_created": result.get("clusters_created", 0),
                "duplicates_found": result.get("duplicates_found", 0),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Clustering batch failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def cluster_single_item(self, raw_item_id: str):
    """Assign a single item to a cluster."""
    import asyncio
    from app.services.processing.dedup import DeduplicationService

    logger.info(f"Clustering item {raw_item_id}")

    try:
        service = DeduplicationService()
        result = asyncio.run(service.assign_cluster(UUID(raw_item_id)))
        return result

    except Exception as e:
        logger.error(f"Clustering failed for item {raw_item_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def merge_clusters(self, cluster_ids: list[str]):
    """Merge multiple clusters into one."""
    import asyncio
    from app.services.processing.dedup import DeduplicationService

    logger.info(f"Merging {len(cluster_ids)} clusters")

    try:
        service = DeduplicationService()
        uuids = [UUID(id) for id in cluster_ids]
        result = asyncio.run(service.merge_clusters(uuids))
        return result

    except Exception as e:
        logger.error(f"Cluster merge failed: {e}")
        raise self.retry(exc=e)


@shared_task
def archive_old_clusters(self, days_old: int = 30):
    """Archive clusters older than N days."""
    import asyncio
    from app.services.processing.dedup import DeduplicationService

    logger.info(f"Archiving clusters older than {days_old} days")

    try:
        service = DeduplicationService()
        result = asyncio.run(service.archive_old_clusters(days_old))
        return result

    except Exception as e:
        logger.error(f"Cluster archival failed: {e}")
        raise
