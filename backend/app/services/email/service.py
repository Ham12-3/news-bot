"""
Email service for sending briefings via SMTP.
"""

import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from uuid import UUID

import aiosmtplib
from sqlalchemy import select

from app.db.session import AsyncSessionLocal
from app.db.models import User, Briefing
from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger(__name__)


class EmailService:
    """Service for sending emails via SMTP."""

    def __init__(self):
        self.smtp_host = settings.SMTP_HOST
        self.smtp_port = settings.SMTP_PORT
        self.smtp_user = settings.SMTP_USER
        self.smtp_password = settings.SMTP_PASSWORD
        self.smtp_use_tls = settings.SMTP_USE_TLS
        self.from_email = settings.EMAIL_FROM
        self.from_name = settings.EMAIL_FROM_NAME

    async def send_email(
        self,
        to_email: str,
        subject: str,
        html_content: str,
        text_content: str | None = None,
    ) -> bool:
        """
        Send an email via SMTP.

        Args:
            to_email: Recipient email address
            subject: Email subject
            html_content: HTML body content
            text_content: Plain text fallback (optional)

        Returns:
            True if sent successfully, False otherwise
        """
        try:
            # Create message
            message = MIMEMultipart("alternative")
            message["Subject"] = subject
            message["From"] = f"{self.from_name} <{self.from_email}>"
            message["To"] = to_email

            # Add text part (fallback)
            if text_content:
                text_part = MIMEText(text_content, "plain", "utf-8")
                message.attach(text_part)

            # Add HTML part
            html_part = MIMEText(html_content, "html", "utf-8")
            message.attach(html_part)

            # Send via SMTP
            await aiosmtplib.send(
                message,
                hostname=self.smtp_host,
                port=self.smtp_port,
                username=self.smtp_user,
                password=self.smtp_password,
                start_tls=self.smtp_use_tls,
            )

            logger.info(f"Email sent successfully to {to_email}")
            return True

        except Exception as e:
            logger.error(f"Failed to send email to {to_email}: {e}")
            return False

    async def send_briefing(self, briefing_id: UUID) -> dict:
        """
        Send a briefing email to its user.

        Args:
            briefing_id: UUID of the briefing to send

        Returns:
            Result dict with success status
        """
        async with AsyncSessionLocal() as session:
            # Get briefing with user
            result = await session.execute(
                select(Briefing).where(Briefing.id == briefing_id)
            )
            briefing = result.scalar_one_or_none()

            if not briefing:
                return {"error": "Briefing not found"}

            # Get user
            user_result = await session.execute(
                select(User).where(User.id == briefing.user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                return {"error": "User not found"}

            if not user.email_verified:
                return {"error": "User email not verified", "skipped": True}

            # Format email
            subject = f"Your Daily Briefing - {briefing.generated_at.strftime('%B %d, %Y')}"
            html_content = self._format_briefing_html(briefing)
            text_content = self._format_briefing_text(briefing)

            # Send
            success = await self.send_email(
                to_email=user.email,
                subject=subject,
                html_content=html_content,
                text_content=text_content,
            )

            if success:
                # Update briefing as sent
                briefing.sent_at = datetime.utcnow()
                await session.commit()

            return {
                "success": success,
                "briefing_id": str(briefing_id),
                "user_email": user.email,
            }

    async def send_briefings_batch(self, briefing_ids: list[UUID]) -> dict:
        """Send multiple briefings concurrently."""
        results = {
            "sent": 0,
            "failed": 0,
            "skipped": 0,
            "errors": [],
        }

        tasks = [self.send_briefing(bid) for bid in briefing_ids]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for bid, outcome in zip(briefing_ids, outcomes):
            if isinstance(outcome, Exception):
                results["failed"] += 1
                results["errors"].append({
                    "briefing_id": str(bid),
                    "error": str(outcome),
                })
            elif outcome.get("success"):
                results["sent"] += 1
            elif outcome.get("skipped"):
                results["skipped"] += 1
            else:
                results["failed"] += 1
                results["errors"].append({
                    "briefing_id": str(bid),
                    "error": outcome.get("error", "Unknown error"),
                })

        return results

    def _format_briefing_html(self, briefing: Briefing) -> str:
        """Format briefing as HTML email."""
        # Get markdown content and convert to basic HTML
        content = briefing.content or ""

        # Basic markdown to HTML conversion
        html_content = content
        # Headers
        html_content = html_content.replace("### ", "<h3>").replace("\n", "</h3>\n", 1)
        html_content = html_content.replace("## ", "<h2>").replace("\n", "</h2>\n", 1)
        html_content = html_content.replace("# ", "<h1>").replace("\n", "</h1>\n", 1)
        # Bold
        import re
        html_content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", html_content)
        # Italic
        html_content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", html_content)
        # Line breaks
        html_content = html_content.replace("\n\n", "</p><p>")
        html_content = html_content.replace("\n", "<br>")

        return f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <style>
                body {{
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                    line-height: 1.6;
                    color: #333;
                    max-width: 600px;
                    margin: 0 auto;
                    padding: 20px;
                }}
                h1 {{ color: #1a1a1a; border-bottom: 2px solid #0066cc; padding-bottom: 10px; }}
                h2 {{ color: #333; margin-top: 30px; }}
                h3 {{ color: #666; }}
                a {{ color: #0066cc; }}
                .footer {{
                    margin-top: 40px;
                    padding-top: 20px;
                    border-top: 1px solid #eee;
                    font-size: 12px;
                    color: #666;
                }}
            </style>
        </head>
        <body>
            <h1>Daily Intelligence Briefing</h1>
            <p><em>{briefing.generated_at.strftime('%B %d, %Y')}</em></p>
            <p>{html_content}</p>
            <div class="footer">
                <p>Generated by News Intelligence Platform</p>
                <p><a href="{{{{ unsubscribe_url }}}}">Manage preferences</a></p>
            </div>
        </body>
        </html>
        """

    def _format_briefing_text(self, briefing: Briefing) -> str:
        """Format briefing as plain text email."""
        content = briefing.content or ""
        date_str = briefing.generated_at.strftime('%B %d, %Y')

        return f"""
DAILY INTELLIGENCE BRIEFING
{date_str}
{'=' * 50}

{content}

---
Generated by News Intelligence Platform
        """.strip()


# Singleton instance
_email_service: EmailService | None = None


def get_email_service() -> EmailService:
    """Get the email service singleton."""
    global _email_service
    if _email_service is None:
        _email_service = EmailService()
    return _email_service
