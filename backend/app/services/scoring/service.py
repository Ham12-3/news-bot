"""
Scoring service for computing signal scores.
Combines heuristics with optional AI-powered relevance scoring.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_worker_session
from app.db.models import RawItem, ItemScore, ClusterMember, Source
from app.core.logging import get_logger
from app.core.config import settings
from .prompts import RELEVANCE_SYSTEM_PROMPT, RELEVANCE_USER_TEMPLATE

logger = get_logger(__name__)


class ScoringService:
    """Computes signal scores for items."""

    # Score weights (must sum to 1.0)
    WEIGHTS = {
        "relevance": 0.40,
        "velocity": 0.20,
        "cross_source": 0.20,
        "novelty": 0.20,
    }

    def __init__(self):
        self.high_signal_threshold = 0.6
        self._ai_client = None

    def _get_ai_client(self):
        """Lazy load AI client."""
        if self._ai_client is None and settings.AI_SCORING_ENABLED:
            try:
                from app.services.ai import get_ai_client
                self._ai_client = get_ai_client()
            except Exception as e:
                logger.warning(f"Failed to initialize AI client: {e}")
        return self._ai_client

    async def score_all_pending(self) -> dict:
        """Score all processed items that need scoring."""
        return await self.score_all()

    async def score_all(self) -> dict:
        """Score all processed items that need scoring."""
        results = {
            "items_scored": 0,
            "high_signal_count": 0,
        }

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get items with status='extracted' that haven't been scored yet
            query = (
                select(RawItem)
                .outerjoin(ItemScore, RawItem.id == ItemScore.raw_item_id)
                .where(RawItem.status == "extracted")
                .where(ItemScore.raw_item_id == None)
                .limit(200)
            )
            result = await session.execute(query)
            items = result.scalars().all()

            for item in items:
                try:
                    score = await self._score_item(session, item)
                    results["items_scored"] += 1

                    if score.signal_score >= self.high_signal_threshold:
                        results["high_signal_count"] += 1

                except Exception as e:
                    logger.error(f"Failed to score item {item.id}: {e}")

            await session.commit()

        return results

    async def score_item(self, item_id: UUID) -> dict | None:
        """Score a single item."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            result = await session.execute(
                select(RawItem).where(RawItem.id == item_id)
            )
            item = result.scalar_one_or_none()

            if not item:
                return None

            score = await self._score_item(session, item)
            await session.commit()

            return {
                "item_id": str(item_id),
                "signal_score": score.signal_score,
                "relevance": score.relevance_score,
                "velocity": score.velocity_score,
                "cross_source": score.cross_source_score,
                "novelty": score.novelty_score,
            }

    async def _score_item(self, session: AsyncSession, item: RawItem) -> ItemScore:
        """Compute all scores for an item."""
        # Get source info
        source_result = await session.execute(
            select(Source).where(Source.id == item.source_id)
        )
        source = source_result.scalar_one()

        # Compute individual scores
        relevance = await self._compute_relevance(item, source)
        velocity = await self._compute_velocity(session, item)
        cross_source = await self._compute_cross_source(session, item)
        novelty = await self._compute_novelty(session, item)

        # Weighted final score
        signal_score = (
            self.WEIGHTS["relevance"] * relevance +
            self.WEIGHTS["velocity"] * velocity +
            self.WEIGHTS["cross_source"] * cross_source +
            self.WEIGHTS["novelty"] * novelty
        )

        # Explanation for transparency
        explanation = {
            "weights": self.WEIGHTS,
            "components": {
                "relevance": {"score": relevance, "reason": "Based on source credibility and content quality"},
                "velocity": {"score": velocity, "reason": "Engagement metrics from source"},
                "cross_source": {"score": cross_source, "reason": "Number of sources covering this story"},
                "novelty": {"score": novelty, "reason": "How new/unique this information is"},
            },
            "computed_at": datetime.now(timezone.utc).isoformat(),
            "ai_scored": settings.AI_SCORING_ENABLED,
        }

        # Create score record
        score = ItemScore(
            raw_item_id=item.id,
            relevance_score=relevance,
            velocity_score=velocity,
            cross_source_score=cross_source,
            novelty_score=novelty,
            signal_score=signal_score,
            score_meta=explanation,
        )
        session.add(score)

        # Update item status
        item.status = "scored"

        return score

    async def _compute_relevance(self, item: RawItem, source: Source) -> float:
        """
        Compute relevance score using AI or heuristics.
        """
        # Try AI scoring first if enabled
        ai_client = self._get_ai_client()
        if ai_client and settings.AI_SCORING_ENABLED:
            try:
                return await self._compute_relevance_ai(item, source, ai_client)
            except Exception as e:
                logger.warning(f"AI relevance scoring failed, falling back to heuristics: {e}")

        # Fallback to heuristic scoring
        return await self._compute_relevance_heuristic(item, source)

    async def _compute_relevance_ai(self, item: RawItem, source: Source, ai_client) -> float:
        """Compute relevance using LLM."""
        from app.services.ai.client import ModelTier

        # Format the prompt
        content_preview = item.raw_text[:500] if item.raw_text else "(no content)"
        published_str = item.published_at.isoformat() if item.published_at else "unknown"

        user_prompt = RELEVANCE_USER_TEMPLATE.format(
            title=item.title,
            source_name=source.name,
            credibility_tier=source.credibility_tier,
            published_at=published_str,
            category=source.category or "general",
            content_preview=content_preview,
        )

        # Get AI score
        result = await ai_client.complete_json(
            system_prompt=RELEVANCE_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            tier=ModelTier.CHEAP,
            max_tokens=100,
        )

        if "error" in result:
            raise ValueError(f"AI scoring failed: {result.get('error')}")

        # Normalize 0-10 score to 0-1
        ai_score = result.get("score", 5) / 10.0
        return max(0.0, min(1.0, ai_score))

    async def _compute_relevance_heuristic(self, item: RawItem, source: Source) -> float:
        """Compute relevance using heuristics."""
        # Base score from source credibility (1-5 scale -> 0.2-1.0)
        score = source.credibility_tier / 5.0

        # Boost for longer content (more substantive)
        if item.raw_text and len(item.raw_text) > 200:
            score += 0.1

        # Slight penalty for very short titles
        if len(item.title) < 20:
            score -= 0.1

        return max(0.0, min(1.0, score))

    async def _compute_velocity(self, session: AsyncSession, item: RawItem) -> float:
        """
        Compute velocity/momentum score based on:
        - HN score, Reddit upvotes
        - Recent engagement growth
        """
        score = 0.5  # Base score

        payload = item.raw_payload or {}

        # HN-specific (stored in raw_payload)
        if "hn_id" in payload:
            hn_score = payload.get("score", 0)
            # Normalize HN score (100+ is significant)
            score = min(1.0, hn_score / 200)

        # Reddit-specific
        if "reddit_id" in payload:
            reddit_score = payload.get("score", 0)
            upvote_ratio = payload.get("upvote_ratio", 0.5)
            # Consider both raw score and ratio
            score = min(1.0, (reddit_score / 500) * upvote_ratio)

        return max(0.0, min(1.0, score))

    async def _compute_cross_source(self, session: AsyncSession, item: RawItem) -> float:
        """
        Compute cross-source validation score:
        - How many sources are covering this story?
        """
        # Check cluster size (if item is in a cluster)
        # First find if this item is in a cluster
        subquery = (
            select(ClusterMember.cluster_id)
            .where(ClusterMember.raw_item_id == item.id)
            .limit(1)
            .scalar_subquery()
        )
        # Then count members in that cluster
        cluster_query = (
            select(func.count(ClusterMember.raw_item_id))
            .where(ClusterMember.cluster_id == subquery)
        )

        try:
            result = await session.execute(cluster_query)
            cluster_size = result.scalar() or 1
        except Exception:
            cluster_size = 1

        # Normalize (3+ sources is very strong signal)
        if cluster_size >= 3:
            return 1.0
        elif cluster_size == 2:
            return 0.7
        else:
            return 0.3

    async def _compute_novelty(self, session: AsyncSession, item: RawItem) -> float:
        """
        Compute novelty score:
        - Is this new information or rehashed?
        - Based on recency (can be enhanced with embedding similarity)
        """
        # Use recency as proxy for novelty
        now = datetime.now(timezone.utc)
        if item.published_at:
            # Ensure published_at is timezone-aware
            published = item.published_at
            if published.tzinfo is None:
                published = published.replace(tzinfo=timezone.utc)
            age_hours = (now - published).total_seconds() / 3600
            # Newer = more novel
            if age_hours < 6:
                return 0.9
            elif age_hours < 24:
                return 0.7
            elif age_hours < 72:
                return 0.5
            else:
                return 0.3
        else:
            # Use fetch time if no publish time
            fetched = item.fetched_at
            if fetched.tzinfo is None:
                fetched = fetched.replace(tzinfo=timezone.utc)
            age_hours = (now - fetched).total_seconds() / 3600
            if age_hours < 6:
                return 0.8
            elif age_hours < 24:
                return 0.6
            else:
                return 0.4

    async def score_cluster(self, cluster_id: UUID) -> dict:
        """Score all items in a cluster."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get all items in the cluster
            query = (
                select(RawItem)
                .join(ClusterMember, RawItem.id == ClusterMember.raw_item_id)
                .where(ClusterMember.cluster_id == cluster_id)
            )
            result = await session.execute(query)
            items = result.scalars().all()

            scored = 0
            for item in items:
                try:
                    await self._score_item(session, item)
                    scored += 1
                except Exception as e:
                    logger.error(f"Failed to score item {item.id} in cluster: {e}")

            await session.commit()

            return {"cluster_id": str(cluster_id), "items_scored": scored}

    async def compute_ai_relevance(self, item_id: UUID) -> dict:
        """Compute AI-based relevance score for a single item."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            result = await session.execute(
                select(RawItem).where(RawItem.id == item_id)
            )
            item = result.scalar_one_or_none()

            if not item:
                return {"success": False, "error": "Item not found"}

            source_result = await session.execute(
                select(Source).where(Source.id == item.source_id)
            )
            source = source_result.scalar_one()

            ai_client = self._get_ai_client()
            if not ai_client:
                return {"success": False, "error": "AI client not available"}

            try:
                score = await self._compute_relevance_ai(item, source, ai_client)
                return {"success": True, "relevance_score": score}
            except Exception as e:
                return {"success": False, "error": str(e)}

    async def get_high_signals(self, limit: int = 50, min_score: float = 0.6) -> list[dict]:
        """Get high-signal items for briefing generation."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            query = (
                select(RawItem, ItemScore, Source)
                .join(ItemScore, RawItem.id == ItemScore.raw_item_id)
                .join(Source, RawItem.source_id == Source.id)
                .where(ItemScore.signal_score >= min_score)
                .order_by(ItemScore.signal_score.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            rows = result.all()

            signals = []
            for item, score, source in rows:
                signals.append({
                    "id": str(item.id),
                    "title": item.title,
                    "url": item.url,
                    "source_name": source.name,
                    "source_type": source.type.value,
                    "published_at": item.published_at.isoformat() if item.published_at else None,
                    "signal_score": score.signal_score,
                    "relevance": score.relevance_score,
                    "velocity": score.velocity_score,
                    "cross_source": score.cross_source_score,
                    "novelty": score.novelty_score,
                    "content_preview": item.raw_text[:300] if item.raw_text else None,
                })

            return signals
