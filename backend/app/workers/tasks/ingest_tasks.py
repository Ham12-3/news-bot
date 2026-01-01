"""
Ingestion tasks - fetch content from sources.
Queue: ingest
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def ingest_all_sources(self):
    """
    Main ingestion task - fetches from all enabled sources.
    Runs every 30 minutes via Celery Beat.
    """
    import asyncio
    from app.services.ingestion import IngestionService

    logger.info("Starting ingestion for all sources")

    try:
        service = IngestionService()
        result = asyncio.run(service.ingest_all())

        logger.info(
            "Ingestion completed",
            extra={
                "sources_processed": result.get("sources_processed", 0),
                "items_ingested": result.get("items_ingested", 0),
                "errors": len(result.get("errors", [])),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Ingestion failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def ingest_source(self, source_id: str):
    """Ingest from a single source."""
    import asyncio
    from app.services.ingestion import IngestionService

    logger.info(f"Starting ingestion for source {source_id}")

    try:
        service = IngestionService()
        result = asyncio.run(service.ingest_source(UUID(source_id)))
        return result

    except Exception as e:
        logger.error(f"Ingestion failed for source {source_id}: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def ingest_rss_source(self, source_id: str, feed_url: str):
    """Ingest from a specific RSS feed."""
    import asyncio
    from app.services.ingestion.rss import RSSIngester

    logger.info(f"Ingesting RSS feed: {feed_url}")

    try:
        ingester = RSSIngester()
        result = asyncio.run(ingester.ingest(UUID(source_id)))
        return result

    except Exception as e:
        logger.error(f"RSS ingestion failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def ingest_hackernews(self):
    """Ingest from Hacker News API."""
    import asyncio
    from app.services.ingestion.hackernews import HackerNewsIngester

    logger.info("Ingesting from Hacker News")

    try:
        ingester = HackerNewsIngester()
        result = asyncio.run(ingester.ingest_frontpage())
        return result

    except Exception as e:
        logger.error(f"HN ingestion failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3)
def ingest_reddit_subreddits(self, subreddits: list[str]):
    """Ingest from Reddit subreddits."""
    import asyncio
    from app.services.ingestion.reddit import RedditIngester

    logger.info(f"Ingesting from Reddit: {subreddits}")

    try:
        ingester = RedditIngester()
        result = asyncio.run(ingester.ingest_subreddits(subreddits))
        return result

    except Exception as e:
        logger.error(f"Reddit ingestion failed: {e}")
        raise self.retry(exc=e)
