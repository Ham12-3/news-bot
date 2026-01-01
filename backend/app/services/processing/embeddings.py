from datetime import datetime
from uuid import UUID
import numpy as np
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_worker_session
from app.db.models import ItemEmbedding, RawItem, ExtractedContent
from app.core.logging import get_logger
from app.core.config import settings

logger = get_logger(__name__)


class EmbeddingService:
    """Generates and manages embeddings for items."""

    def __init__(self):
        self.model = "text-embedding-ada-002"
        self.dimension = 1536

    async def generate_for_item(
        self, session: AsyncSession, item_id, text: str
    ) -> list[float] | None:
        """Generate embedding for an item and store it."""
        try:
            embedding = await self._generate_embedding(text)

            if embedding:
                item_embedding = ItemEmbedding(
                    raw_item_id=item_id,
                    embed_model=self.model,
                    dim=self.dimension,
                    embedding=embedding,
                )
                session.add(item_embedding)

            return embedding

        except Exception as e:
            logger.error(f"Failed to generate embedding for item {item_id}: {e}")
            return None

    async def embed_all_pending(self, limit: int = 100) -> dict:
        """
        Generate embeddings for items with status='extracted' that don't have embeddings.
        """
        result = {
            "items_processed": 0,
            "embeddings_created": 0,
            "tokens_used": 0,
            "failed": 0,
        }

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get items that need embeddings
            query = (
                select(RawItem)
                .outerjoin(ItemEmbedding, RawItem.id == ItemEmbedding.raw_item_id)
                .where(RawItem.status == "extracted")
                .where(ItemEmbedding.raw_item_id == None)
                .limit(limit)
            )

            items = (await session.execute(query)).scalars().all()

            for item in items:
                result["items_processed"] += 1

                try:
                    # Get text for embedding
                    text = await self._get_text_for_embedding(session, item)

                    if not text:
                        result["failed"] += 1
                        continue

                    # Generate embedding
                    embedding = await self._generate_embedding(text)

                    if embedding:
                        item_embedding = ItemEmbedding(
                            raw_item_id=item.id,
                            embed_model=self.model,
                            dim=self.dimension,
                            embedding=embedding,
                        )
                        session.add(item_embedding)
                        result["embeddings_created"] += 1

                        # Update item status
                        await session.execute(
                            update(RawItem)
                            .where(RawItem.id == item.id)
                            .values(status="embedded")
                        )
                    else:
                        result["failed"] += 1

                except Exception as e:
                    logger.warning(f"Failed to embed item {item.id}: {e}")
                    result["failed"] += 1

            await session.commit()

        return result

    async def embed_item(self, raw_item_id: UUID) -> dict:
        """Generate embedding for a single item."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get the item
            query = select(RawItem).where(RawItem.id == raw_item_id)
            item = (await session.execute(query)).scalar_one_or_none()

            if not item:
                return {"success": False, "error": "Item not found"}

            # Get text for embedding
            text = await self._get_text_for_embedding(session, item)

            if not text:
                return {"success": False, "error": "No text available for embedding"}

            # Generate embedding
            embedding = await self._generate_embedding(text)

            if not embedding:
                return {"success": False, "error": "Embedding generation failed"}

            item_embedding = ItemEmbedding(
                raw_item_id=item.id,
                embed_model=self.model,
                dim=self.dimension,
                embedding=embedding,
            )
            session.add(item_embedding)

            # Update item status
            await session.execute(
                update(RawItem)
                .where(RawItem.id == item.id)
                .values(status="embedded")
            )

            await session.commit()

            return {"success": True, "dimensions": self.dimension}

    async def embed_batch(self, raw_item_ids: list[UUID]) -> dict:
        """Generate embeddings for a batch of items."""
        result = {
            "items_processed": len(raw_item_ids),
            "embeddings_created": 0,
            "failed": 0,
        }

        for item_id in raw_item_ids:
            item_result = await self.embed_item(item_id)
            if item_result.get("success"):
                result["embeddings_created"] += 1
            else:
                result["failed"] += 1

        return result

    async def _get_text_for_embedding(self, session: AsyncSession, item: RawItem) -> str | None:
        """Get the best text for generating an embedding."""
        # Try to get extracted content first
        query = select(ExtractedContent).where(ExtractedContent.raw_item_id == item.id)
        extracted = (await session.execute(query)).scalar_one_or_none()

        if extracted and extracted.text:
            return f"{item.title or ''} {extracted.text}"[:8000]

        # Fall back to title + raw_text
        parts = []
        if item.title:
            parts.append(item.title)
        if item.raw_text:
            parts.append(item.raw_text)

        if parts:
            return " ".join(parts)[:8000]

        return None

    async def _generate_embedding(self, text: str) -> list[float] | None:
        """Call OpenAI API to generate embedding."""
        if not settings.OPENAI_API_KEY:
            logger.warning("OpenAI API key not configured, using dummy embedding")
            return self._generate_dummy_embedding()

        try:
            from openai import AsyncOpenAI

            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

            # Truncate text to avoid token limits
            text = text[:8000]

            response = await client.embeddings.create(
                input=text,
                model=self.model,
            )

            embedding = response.data[0].embedding

            # Track usage
            await track_model_call(
                model=self.model,
                tokens=response.usage.total_tokens,
                cost=response.usage.total_tokens * 0.0001 / 1000,  # Approximate cost
            )

            return embedding

        except Exception as e:
            logger.error(f"OpenAI embedding API error: {e}")
            return None

    def _generate_dummy_embedding(self) -> list[float]:
        """Generate a random embedding for development/testing."""
        return list(np.random.randn(self.dimension).astype(float))

    async def compute_similarity(
        self, embedding1: list[float], embedding2: list[float]
    ) -> float:
        """Compute cosine similarity between two embeddings."""
        a = np.array(embedding1)
        b = np.array(embedding2)

        return float(np.dot(a, b) / (np.linalg.norm(a) * np.linalg.norm(b)))
