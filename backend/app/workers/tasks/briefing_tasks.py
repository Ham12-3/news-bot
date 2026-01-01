"""
Briefing tasks - generate daily briefings with LLM.
Queue: summarise
"""

from celery import shared_task
from uuid import UUID
from datetime import datetime, timedelta

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=300)
def generate_all_briefings(self):
    """
    Generate briefings for all users who need them.
    Runs at 06:50 UTC via Celery Beat.
    """
    import asyncio
    from app.services.briefing import BriefingService

    logger.info("Generating daily briefings for all users")

    try:
        service = BriefingService()
        result = asyncio.run(service.generate_all_pending())

        logger.info(
            "Daily briefings generation complete",
            extra={
                "users_processed": result.get("users_processed", 0),
                "briefings_generated": result.get("briefings_generated", 0),
                "errors": len(result.get("errors", [])),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Daily briefings generation failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def generate_user_briefing(self, user_id: str):
    """Generate a personalized briefing for a specific user."""
    import asyncio
    from app.services.briefing import BriefingService

    logger.info(f"Generating briefing for user {user_id}")

    try:
        service = BriefingService()
        result = asyncio.run(service.generate_for_user(UUID(user_id)))

        if "error" in result:
            logger.warning(f"Briefing generation returned error: {result['error']}")

        return result

    except Exception as e:
        logger.error(f"User briefing generation failed: {e}")
        raise self.retry(exc=e)


@shared_task
def get_user_briefings(user_id: str, limit: int = 10):
    """Get recent briefings for a user (for API use)."""
    import asyncio
    from app.services.briefing import BriefingService

    try:
        service = BriefingService()
        result = asyncio.run(service.get_user_briefings(UUID(user_id), limit))
        return result

    except Exception as e:
        logger.error(f"Failed to get user briefings: {e}")
        return []


@shared_task
def get_briefing_detail(briefing_id: str):
    """Get a specific briefing with linked items."""
    import asyncio
    from app.services.briefing import BriefingService

    try:
        service = BriefingService()
        result = asyncio.run(service.get_briefing_by_id(UUID(briefing_id)))
        return result

    except Exception as e:
        logger.error(f"Failed to get briefing detail: {e}")
        return None
