from datetime import datetime, timedelta
from uuid import UUID
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_worker_session
from app.db.models import RawItem, ItemEmbedding, Cluster, ClusterMember, ClusterStatus
from app.core.logging import get_logger

logger = get_logger(__name__)


class DeduplicationService:
    """Handles exact and semantic deduplication."""

    def __init__(self):
        self.semantic_threshold = 0.92  # Cosine similarity threshold
        self.time_window_days = 7  # Look back window for duplicates

    async def check_exact_duplicate(self, session: AsyncSession, item: RawItem) -> bool:
        """
        Check for exact duplicates based on URL or title.
        Returns True if item is a duplicate.
        """
        # Check for exact URL match (excluding self)
        url_query = select(RawItem).where(
            RawItem.url == item.url,
            RawItem.id != item.id,
        )
        result = await session.execute(url_query)
        url_match = result.scalar_one_or_none()

        if url_match:
            # Link to existing cluster or create new one
            await self._add_to_cluster(session, item, url_match, "exact", 1.0)
            return True

        # Check for exact title match (within time window)
        cutoff = datetime.utcnow() - timedelta(days=self.time_window_days)
        title_query = select(RawItem).where(
            RawItem.title == item.title,
            RawItem.id != item.id,
            RawItem.fetched_at >= cutoff,
        )
        result = await session.execute(title_query)
        title_match = result.scalar_one_or_none()

        if title_match:
            await self._add_to_cluster(session, item, title_match, "exact", 1.0)
            return True

        return False

    async def check_semantic_duplicate(self, session: AsyncSession, item_id: int) -> bool:
        """
        Check for semantic duplicates using embedding similarity.
        Returns True if item is a duplicate.
        """
        # Get the item's embedding
        embed_query = select(ItemEmbedding).where(ItemEmbedding.raw_item_id == item_id)
        result = await session.execute(embed_query)
        item_embedding = result.scalar_one_or_none()

        if not item_embedding:
            return False

        # Find similar embeddings using pgvector
        # Uses cosine distance: 1 - similarity
        cutoff = datetime.utcnow() - timedelta(days=self.time_window_days)

        # Note: This uses pgvector's <=> operator for cosine distance
        similarity_query = text("""
            SELECT
                ie.raw_item_id,
                1 - (ie.embedding <=> :target_embedding) as similarity
            FROM item_embeddings ie
            JOIN raw_items ri ON ri.id = ie.raw_item_id
            WHERE ie.raw_item_id != :item_id
            AND ri.fetched_at >= :cutoff
            AND 1 - (ie.embedding <=> :target_embedding) >= :threshold
            ORDER BY similarity DESC
            LIMIT 5
        """)

        result = await session.execute(
            similarity_query,
            {
                "target_embedding": str(item_embedding.embedding),
                "item_id": item_id,
                "cutoff": cutoff,
                "threshold": self.semantic_threshold,
            }
        )
        similar_items = result.fetchall()

        if similar_items:
            # Get the most similar item
            best_match_id, similarity = similar_items[0]

            # Get the canonical item
            canonical_query = select(RawItem).where(RawItem.id == best_match_id)
            result = await session.execute(canonical_query)
            canonical_item = result.scalar_one_or_none()

            if canonical_item:
                item_query = select(RawItem).where(RawItem.id == item_id)
                result = await session.execute(item_query)
                item = result.scalar_one_or_none()

                if item:
                    await self._add_to_cluster(
                        session, item, canonical_item, "semantic", similarity
                    )
                    return True

        return False

    async def _add_to_cluster(
        self,
        session: AsyncSession,
        duplicate_item: RawItem,
        canonical_item: RawItem,
        cluster_type: str,
        similarity: float,
    ) -> None:
        """Add an item to a cluster (create cluster if needed)."""
        # Check if canonical item already has a cluster
        cluster_query = select(ClusterMember).where(
            ClusterMember.raw_item_id == canonical_item.id,
            ClusterMember.is_canonical == True,
        )
        result = await session.execute(cluster_query)
        existing_member = result.scalar_one_or_none()

        if existing_member:
            cluster_id = existing_member.cluster_id
        else:
            # Create new cluster
            cluster = Cluster(
                canonical_item_id=canonical_item.id,
                status=ClusterStatus.OPEN,
            )
            session.add(cluster)
            await session.flush()

            # Add canonical item as member
            canonical_member = ClusterMember(
                cluster_id=cluster.id,
                raw_item_id=canonical_item.id,
                similarity=1.0,
                is_canonical=True,
            )
            session.add(canonical_member)
            cluster_id = cluster.id

        # Add duplicate item as member
        duplicate_member = ClusterMember(
            cluster_id=cluster_id,
            raw_item_id=duplicate_item.id,
            similarity=similarity,
            is_canonical=False,
        )
        session.add(duplicate_member)

        logger.info(
            f"Item added to cluster: duplicate={duplicate_item.id}, canonical={canonical_item.id}, "
            f"cluster={cluster_id}, type={cluster_type}, similarity={similarity}"
        )

    async def cluster_all_pending(self, limit: int = 100) -> dict:
        """
        Cluster items with embeddings that haven't been clustered yet.
        """
        result = {
            "items_processed": 0,
            "clusters_created": 0,
            "duplicates_found": 0,
        }

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get items with embeddings that aren't in any cluster
            query = (
                select(RawItem)
                .join(ItemEmbedding, RawItem.id == ItemEmbedding.raw_item_id)
                .outerjoin(ClusterMember, RawItem.id == ClusterMember.raw_item_id)
                .where(RawItem.status == "embedded")
                .where(ClusterMember.raw_item_id == None)
                .limit(limit)
            )

            items = (await session.execute(query)).scalars().all()

            for item in items:
                result["items_processed"] += 1

                try:
                    # Check for semantic duplicates
                    is_dup = await self.check_semantic_duplicate(session, item.id)

                    if is_dup:
                        result["duplicates_found"] += 1
                    else:
                        # Create a new single-item cluster
                        cluster = Cluster(
                            canonical_item_id=item.id,
                            status=ClusterStatus.OPEN,
                        )
                        session.add(cluster)
                        await session.flush()

                        # Add item as canonical member
                        member = ClusterMember(
                            cluster_id=cluster.id,
                            raw_item_id=item.id,
                            is_canonical=True,
                            similarity=1.0,
                        )
                        session.add(member)
                        result["clusters_created"] += 1

                    # Update item status
                    await session.execute(
                        update(RawItem)
                        .where(RawItem.id == item.id)
                        .values(status="clustered")
                    )

                except Exception as e:
                    logger.warning(f"Failed to cluster item {item.id}: {e}")

            await session.commit()

        return result

    async def assign_cluster(self, raw_item_id: UUID) -> dict:
        """Assign a single item to a cluster."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get the item
            query = select(RawItem).where(RawItem.id == raw_item_id)
            item = (await session.execute(query)).scalar_one_or_none()

            if not item:
                return {"success": False, "error": "Item not found"}

            # Check for duplicates
            is_dup = await self.check_semantic_duplicate(session, raw_item_id)

            if is_dup:
                await session.commit()
                return {"success": True, "is_duplicate": True}

            # Create new cluster
            cluster = Cluster(
                canonical_item_id=item.id,
                status=ClusterStatus.OPEN,
            )
            session.add(cluster)
            await session.flush()

            # Add item as canonical member
            member = ClusterMember(
                cluster_id=cluster.id,
                raw_item_id=item.id,
                is_canonical=True,
                similarity=1.0,
            )
            session.add(member)

            # Update item status
            await session.execute(
                update(RawItem)
                .where(RawItem.id == item.id)
                .values(status="clustered")
            )

            await session.commit()

            return {"success": True, "cluster_id": str(cluster.id), "is_duplicate": False}

    async def merge_clusters(self, cluster_ids: list[UUID]) -> dict:
        """Merge multiple clusters into one."""
        if len(cluster_ids) < 2:
            return {"success": False, "error": "Need at least 2 clusters to merge"}

        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            # Get the first cluster as the target
            target_cluster_id = cluster_ids[0]

            # Move all members from other clusters to target
            members_moved = 0
            for cluster_id in cluster_ids[1:]:
                # Update cluster members
                await session.execute(
                    update(ClusterMember)
                    .where(ClusterMember.cluster_id == cluster_id)
                    .values(cluster_id=target_cluster_id, is_canonical=False)
                )

                # Get count of moved members
                count_query = select(ClusterMember).where(ClusterMember.cluster_id == target_cluster_id)
                result = await session.execute(count_query)
                members_moved += len(result.scalars().all())

                # Mark old cluster as merged
                await session.execute(
                    update(Cluster)
                    .where(Cluster.id == cluster_id)
                    .values(status=ClusterStatus.MERGED)
                )

            await session.commit()

            return {
                "success": True,
                "target_cluster_id": str(target_cluster_id),
                "clusters_merged": len(cluster_ids) - 1,
                "members_moved": members_moved,
            }

    async def archive_old_clusters(self, days_old: int = 30) -> dict:
        """Archive clusters older than N days."""
        WorkerSession = get_worker_session()
        async with WorkerSession() as session:
            cutoff = datetime.utcnow() - timedelta(days=days_old)

            # Archive old clusters
            result = await session.execute(
                update(Cluster)
                .where(Cluster.created_at < cutoff)
                .where(Cluster.status == ClusterStatus.OPEN)
                .values(status=ClusterStatus.ARCHIVED)
            )

            await session.commit()

            return {"clusters_archived": result.rowcount}
