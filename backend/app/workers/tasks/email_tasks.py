"""
Email tasks - send briefings to users.
Queue: email
"""

from celery import shared_task
from uuid import UUID

from app.core.logging import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=300)
def send_daily_briefings(self):
    """
    Send today's briefing emails to all users.
    Runs at 07:00 UTC via Celery Beat (after briefing generation).
    """
    import asyncio
    from datetime import datetime
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models import Briefing
    from app.services.email import get_email_service

    logger.info("Starting daily briefing email send")

    async def get_unsent_briefings():
        """Get briefings generated today that haven't been sent."""
        today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

        async with AsyncSessionLocal() as session:
            query = (
                select(Briefing.id)
                .where(Briefing.generated_at >= today)
                .where(Briefing.sent_at == None)
            )
            result = await session.execute(query)
            return [row[0] for row in result.all()]

    async def send_all():
        briefing_ids = await get_unsent_briefings()

        if not briefing_ids:
            return {"sent": 0, "failed": 0, "message": "No unsent briefings found"}

        service = get_email_service()
        return await service.send_briefings_batch(briefing_ids)

    try:
        result = asyncio.run(send_all())

        logger.info(
            "Daily briefing emails sent",
            extra={
                "emails_sent": result.get("sent", 0),
                "emails_failed": result.get("failed", 0),
                "emails_skipped": result.get("skipped", 0),
            }
        )
        return result

    except Exception as e:
        logger.error(f"Daily briefing email send failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def send_briefing_email(self, briefing_id: str):
    """Send a specific briefing email."""
    import asyncio
    from app.services.email import get_email_service

    logger.info(f"Sending briefing {briefing_id}")

    try:
        service = get_email_service()
        result = asyncio.run(service.send_briefing(UUID(briefing_id)))

        if not result.get("success"):
            logger.warning(f"Briefing email failed: {result.get('error')}")

        return result

    except Exception as e:
        logger.error(f"Briefing email failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def send_welcome_email(self, user_id: str):
    """Send welcome email to a new user."""
    import asyncio
    from sqlalchemy import select
    from app.db.session import AsyncSessionLocal
    from app.db.models import User
    from app.services.email import get_email_service

    logger.info(f"Sending welcome email to user {user_id}")

    async def get_user_and_send():
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                select(User).where(User.id == UUID(user_id))
            )
            user = result.scalar_one_or_none()

            if not user:
                return {"error": "User not found"}

            service = get_email_service()
            return await service.send_email(
                to_email=user.email,
                subject="Welcome to News Intelligence Platform",
                html_content=f"""
                <html>
                <body>
                    <h1>Welcome!</h1>
                    <p>Thank you for signing up for the News Intelligence Platform.</p>
                    <p>You'll start receiving daily briefings with the most important tech news,
                    curated and analyzed just for you.</p>
                    <p>Best,<br>The News Intelligence Team</p>
                </body>
                </html>
                """,
                text_content="Welcome to News Intelligence Platform! You'll start receiving daily briefings soon.",
            )

    try:
        result = asyncio.run(get_user_and_send())
        return {"success": result} if isinstance(result, bool) else result

    except Exception as e:
        logger.error(f"Welcome email failed: {e}")
        raise self.retry(exc=e)


@shared_task(bind=True, max_retries=2)
def send_test_email(self, email: str):
    """Send a test email to verify SMTP configuration."""
    import asyncio
    from app.services.email import get_email_service

    logger.info(f"Sending test email to {email}")

    async def send():
        service = get_email_service()
        return await service.send_email(
            to_email=email,
            subject="Test Email - News Intelligence Platform",
            html_content="""
            <html>
            <body>
                <h1>Test Email</h1>
                <p>This is a test email from the News Intelligence Platform.</p>
                <p>If you received this, your SMTP configuration is working correctly!</p>
            </body>
            </html>
            """,
            text_content="This is a test email from the News Intelligence Platform. SMTP is working!",
        )

    try:
        success = asyncio.run(send())
        return {"success": success, "email": email}

    except Exception as e:
        logger.error(f"Test email failed: {e}")
        raise self.retry(exc=e)
