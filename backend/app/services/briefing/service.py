"""
Briefing generation service.
Generates AI-powered daily briefings for users based on high-signal items.
"""

import json
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import select, desc, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import AsyncSessionLocal
from app.db.models import (
    RawItem, ItemScore, Briefing, BriefingItem,
    User, UserPreference, Source, ExtractedContent
)
from app.core.logging import get_logger
from app.core.config import settings
from app.services.ai import get_ai_client
from app.services.ai.client import ModelTier
from app.services.scoring.prompts import BRIEFING_SYSTEM_PROMPT, BRIEFING_USER_TEMPLATE

logger = get_logger(__name__)


class BriefingService:
    """Generates AI-powered daily briefings for users."""

    def __init__(self):
        self.high_signal_threshold = 0.5
        self.max_items_per_briefing = settings.BRIEFING_NUM_ITEMS
        self.target_words = settings.BRIEFING_TARGET_WORDS
        self._ai_client = None

    def _get_ai_client(self):
        """Lazy load AI client."""
        if self._ai_client is None:
            try:
                self._ai_client = get_ai_client()
            except Exception as e:
                logger.warning(f"Failed to initialize AI client: {e}")
        return self._ai_client

    async def generate_for_user(self, user_id: UUID) -> dict:
        """Generate a daily briefing for a specific user."""
        async with AsyncSessionLocal() as session:
            # Get user and preferences
            user_result = await session.execute(
                select(User).where(User.id == user_id)
            )
            user = user_result.scalar_one_or_none()

            if not user:
                return {"error": "User not found"}

            # Get user preferences
            pref_result = await session.execute(
                select(UserPreference).where(UserPreference.user_id == user_id)
            )
            preferences = pref_result.scalar_one_or_none()

            # Get high-signal items
            signals = await self._get_user_signals(session, user, preferences)

            if not signals:
                return {"error": "No high-signal items available"}

            # Generate briefing content
            content = await self._generate_briefing_content(signals, preferences)

            if not content:
                return {"error": "Failed to generate briefing content"}

            # Create briefing record
            now = datetime.utcnow()
            briefing = Briefing(
                scope=f"user:{user_id}",
                period_start=now - timedelta(hours=24),
                period_end=now,
                summary_md=content["briefing"],
            )
            session.add(briefing)
            await session.flush()

            # Link briefing to items used
            for rank, item_id in enumerate(content.get("items_used", []), start=1):
                try:
                    # Get signal info from the signals list
                    signal_info = next((s for s in signals if s["id"] == item_id), None)
                    briefing_item = BriefingItem(
                        briefing_id=briefing.id,
                        rank=rank,
                        raw_item_id=UUID(item_id),
                        title=signal_info["title"] if signal_info else "Unknown",
                        one_liner=signal_info.get("content", "")[:200] if signal_info else "",
                        why_it_matters="High signal item",
                        confidence="med",
                        signal_score=signal_info.get("signal_score", 0.0) if signal_info else 0.0,
                        sources=[{"name": signal_info.get("source", "Unknown")}] if signal_info else [],
                    )
                    session.add(briefing_item)
                except Exception as e:
                    logger.warning(f"Failed to link item {item_id} to briefing: {e}")

            await session.commit()

            return {
                "briefing_id": str(briefing.id),
                "user_id": str(user_id),
                "items_included": len(content.get("items_used", [])),
                "word_count": len(content["briefing"].split()),
            }

    async def generate_all_pending(self) -> dict:
        """Generate briefings for all users who need them."""
        results = {
            "users_processed": 0,
            "briefings_generated": 0,
            "errors": [],
        }

        async with AsyncSessionLocal() as session:
            # Get users who haven't received a briefing today
            today = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

            # Get all active users
            query = select(User).where(User.is_active == True)
            result = await session.execute(query)
            users = result.scalars().all()

            # Filter out users who already have today's briefing
            users_to_process = []
            for user in users:
                user_scope = f"user:{user.id}"
                briefing_result = await session.execute(
                    select(Briefing)
                    .where(Briefing.scope == user_scope)
                    .where(Briefing.created_at >= today)
                    .limit(1)
                )
                if not briefing_result.scalar_one_or_none():
                    users_to_process.append(user)
            users = users_to_process

        for user in users:
            try:
                result = await self.generate_for_user(user.id)
                results["users_processed"] += 1

                if "error" not in result:
                    results["briefings_generated"] += 1
                else:
                    logger.warning(f"Briefing failed for user {user.id}: {result['error']}")

            except Exception as e:
                results["errors"].append({
                    "user_id": str(user.id),
                    "error": str(e),
                })

        return results

    async def _get_user_signals(
        self,
        session: AsyncSession,
        user: User,
        preferences: UserPreference | None
    ) -> list[dict]:
        """Get high-signal items tailored to user preferences."""
        cutoff = datetime.utcnow() - timedelta(hours=24)

        # Base query for high-signal items
        query = (
            select(RawItem, ItemScore, Source)
            .join(ItemScore, RawItem.id == ItemScore.raw_item_id)
            .join(Source, RawItem.source_id == Source.id)
            .where(RawItem.fetched_at >= cutoff)
            .where(ItemScore.signal_score >= self.high_signal_threshold)
        )

        # Filter by user's preferred topics if set
        if preferences and preferences.topics:
            query = query.where(Source.category.in_(preferences.topics))

        # Order by signal score
        query = query.order_by(desc(ItemScore.signal_score)).limit(self.max_items_per_briefing * 2)

        result = await session.execute(query)
        rows = result.all()

        # Format signals for briefing generation
        signals = []
        for item, score, source in rows[:self.max_items_per_briefing]:
            signals.append({
                "id": str(item.id),
                "title": item.title,
                "url": item.url,
                "source": source.name,
                "category": source.category,
                "published_at": item.published_at.isoformat() if item.published_at else None,
                "signal_score": round(score.signal_score, 2),
                "content": item.raw_text[:500] if item.raw_text else "",
            })

        return signals

    async def _generate_briefing_content(
        self,
        signals: list[dict],
        preferences: UserPreference | None
    ) -> dict | None:
        """Generate briefing content using LLM."""
        ai_client = self._get_ai_client()

        if not ai_client:
            logger.error("No AI client available for briefing generation")
            return await self._generate_fallback_briefing(signals)

        # Determine focus areas from preferences
        focus_areas = "general technology news"
        if preferences and preferences.topics:
            focus_areas = ", ".join(preferences.topics)

        # Format signals for prompt
        signals_json = json.dumps(signals, indent=2)

        user_prompt = BRIEFING_USER_TEMPLATE.format(
            signals_json=signals_json,
            num_items=min(len(signals), self.max_items_per_briefing),
            target_words=self.target_words,
            focus_areas=focus_areas,
        )

        try:
            result = await ai_client.complete_json(
                system_prompt=BRIEFING_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                tier=ModelTier.STRONG,
                max_tokens=2000,
            )

            if "error" in result:
                logger.warning(f"AI briefing generation failed: {result.get('error')}")
                return await self._generate_fallback_briefing(signals)

            return {
                "briefing": result.get("briefing", ""),
                "items_used": result.get("items_used", [s["id"] for s in signals]),
            }

        except Exception as e:
            logger.error(f"Briefing generation error: {e}")
            return await self._generate_fallback_briefing(signals)

    async def _generate_fallback_briefing(self, signals: list[dict]) -> dict:
        """Generate a simple markdown briefing without AI."""
        lines = [
            "# Daily Intelligence Briefing",
            f"*Generated {datetime.utcnow().strftime('%B %d, %Y')}*",
            "",
            "## Top Signals",
            "",
        ]

        items_used = []
        for i, signal in enumerate(signals[:self.max_items_per_briefing], 1):
            lines.append(f"### {i}. {signal['title']}")
            lines.append(f"*Source: {signal['source']} | Score: {signal['signal_score']}*")
            lines.append("")
            if signal.get("content"):
                lines.append(signal["content"][:200] + "...")
            lines.append(f"[Read more]({signal['url']})")
            lines.append("")
            items_used.append(signal["id"])

        return {
            "briefing": "\n".join(lines),
            "items_used": items_used,
        }

    async def get_user_briefings(
        self,
        user_id: UUID,
        limit: int = 10
    ) -> list[dict]:
        """Get recent briefings for a user."""
        async with AsyncSessionLocal() as session:
            user_scope = f"user:{user_id}"
            query = (
                select(Briefing)
                .where(Briefing.scope == user_scope)
                .order_by(desc(Briefing.created_at))
                .limit(limit)
            )
            result = await session.execute(query)
            briefings = result.scalars().all()

            return [
                {
                    "id": str(b.id),
                    "created_at": b.created_at.isoformat(),
                    "summary_md": b.summary_md,
                }
                for b in briefings
            ]

    async def get_briefing_by_id(self, briefing_id: UUID) -> dict | None:
        """Get a specific briefing with its items."""
        async with AsyncSessionLocal() as session:
            # Get briefing
            result = await session.execute(
                select(Briefing).where(Briefing.id == briefing_id)
            )
            briefing = result.scalar_one_or_none()

            if not briefing:
                return None

            # Get linked items
            items_query = (
                select(RawItem, Source)
                .join(BriefingItem, BriefingItem.raw_item_id == RawItem.id)
                .join(Source, RawItem.source_id == Source.id)
                .where(BriefingItem.briefing_id == briefing_id)
            )
            items_result = await session.execute(items_query)
            items = items_result.all()

            return {
                "id": str(briefing.id),
                "scope": briefing.scope,
                "created_at": briefing.created_at.isoformat(),
                "summary_md": briefing.summary_md,
                "items": [
                    {
                        "id": str(item.id),
                        "title": item.title or "",
                        "url": item.url or "",
                        "source": source.name,
                    }
                    for item, source in items
                ],
            }
