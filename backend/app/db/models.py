"""
Production database models with UUID primary keys and proper enums.
Matches the schema in scripts/init-db.sql
"""

from datetime import datetime, time
from typing import Optional
from uuid import UUID
import enum

from sqlalchemy import (
    String, Text, Integer, Float, Boolean, DateTime, ForeignKey,
    Index, UniqueConstraint, LargeBinary, Time, Enum as SQLEnum
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import UUID as PGUUID, JSONB, ARRAY
from pgvector.sqlalchemy import Vector

from app.db.session import Base


# ============================================================================
# Enum Types
# ============================================================================

class SourceType(str, enum.Enum):
    """Types of content sources."""
    RSS = "rss"
    API_HN = "api_hn"
    API_REDDIT = "api_reddit"
    API_X = "api_x"
    SCRAPE = "scrape"


class ItemKind(str, enum.Enum):
    """Types of content items."""
    ARTICLE = "article"
    POST = "post"
    COMMENT = "comment"
    TWEET = "tweet"
    UNKNOWN = "unknown"


class ClusterStatus(str, enum.Enum):
    """Status of a dedup cluster."""
    OPEN = "open"
    MERGED = "merged"
    ARCHIVED = "archived"


class FeedbackKind(str, enum.Enum):
    """Types of user feedback."""
    UP = "up"
    DOWN = "down"
    SAVE = "save"
    HIDE = "hide"


# ============================================================================
# Sources
# ============================================================================

class Source(Base):
    """Registry of all content sources (RSS feeds, APIs, etc.)."""
    __tablename__ = "sources"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    type: Mapped[SourceType] = mapped_column(
        SQLEnum(SourceType, name="source_type", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False
    )
    url: Mapped[Optional[str]] = mapped_column(Text)
    source_metadata: Mapped[dict] = mapped_column("metadata", JSONB, nullable=False, server_default="{}")
    category: Mapped[Optional[str]] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    credibility_tier: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # 1 high, 5 low
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    raw_items: Mapped[list["RawItem"]] = relationship(back_populates="source", cascade="all, delete-orphan")

    __table_args__ = (
        Index("idx_sources_enabled", "enabled"),
        Index("idx_sources_type", "type"),
    )


# ============================================================================
# Raw Items (one row per fetched entry)
# ============================================================================

class RawItem(Base):
    """Raw items as fetched from sources, before processing."""
    __tablename__ = "raw_items"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("sources.id", ondelete="CASCADE"),
        nullable=False
    )
    external_id: Mapped[Optional[str]] = mapped_column(Text)
    kind: Mapped[ItemKind] = mapped_column(
        SQLEnum(ItemKind, name="item_kind", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=ItemKind.UNKNOWN
    )
    title: Mapped[Optional[str]] = mapped_column(Text)
    url: Mapped[Optional[str]] = mapped_column(Text)
    author: Mapped[Optional[str]] = mapped_column(Text)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    lang: Mapped[Optional[str]] = mapped_column(Text)
    raw_payload: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")
    raw_text: Mapped[Optional[str]] = mapped_column(Text)
    canonical_url: Mapped[Optional[str]] = mapped_column(Text)
    content_hash: Mapped[Optional[bytes]] = mapped_column(LargeBinary)
    status: Mapped[str] = mapped_column(Text, nullable=False, default="new")

    # Relationships
    source: Mapped["Source"] = relationship(back_populates="raw_items")
    extracted_content: Mapped[Optional["ExtractedContent"]] = relationship(
        back_populates="raw_item",
        cascade="all, delete-orphan"
    )
    embedding: Mapped[Optional["ItemEmbedding"]] = relationship(
        back_populates="raw_item",
        cascade="all, delete-orphan"
    )
    cluster_memberships: Mapped[list["ClusterMember"]] = relationship(
        back_populates="raw_item",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_raw_items_source_time", "source_id", "fetched_at"),
        Index("idx_raw_items_published", "published_at"),
        Index("idx_raw_items_url", "url"),
        Index("idx_raw_items_status", "status"),
        Index("idx_raw_items_content_hash", "content_hash"),
        UniqueConstraint(
            "source_id", "external_id",
            name="uq_raw_items_source_external",
            # Note: The actual SQL uses WHERE external_id IS NOT NULL
        ),
    )


# ============================================================================
# Extracted Content (clean article text)
# ============================================================================

class ExtractedContent(Base):
    """Extracted and cleaned content from articles."""
    __tablename__ = "extracted_content"

    raw_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="CASCADE"),
        primary_key=True
    )
    final_url: Mapped[Optional[str]] = mapped_column(Text)
    title: Mapped[Optional[str]] = mapped_column(Text)
    byline: Mapped[Optional[str]] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    html: Mapped[Optional[str]] = mapped_column(Text)
    word_count: Mapped[Optional[int]] = mapped_column(Integer)
    extracted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    extraction_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Relationships
    raw_item: Mapped["RawItem"] = relationship(back_populates="extracted_content")


# ============================================================================
# Embeddings
# ============================================================================

class ItemEmbedding(Base):
    """Vector embeddings for semantic search and deduplication."""
    __tablename__ = "item_embeddings"

    raw_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="CASCADE"),
        primary_key=True
    )
    embed_model: Mapped[str] = mapped_column(Text, nullable=False)
    dim: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[list] = mapped_column(Vector(1536))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    raw_item: Mapped["RawItem"] = relationship(back_populates="embedding")

    __table_args__ = (
        Index(
            "idx_item_embeddings_ivfflat",
            "embedding",
            postgresql_using="ivfflat",
            postgresql_with={"lists": 100},
            postgresql_ops={"embedding": "vector_cosine_ops"}
        ),
    )


# ============================================================================
# Clusters (semantic dedup groups)
# ============================================================================

class Cluster(Base):
    """Groups of duplicate/related items with a canonical representative."""
    __tablename__ = "clusters"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    canonical_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="RESTRICT"),
        nullable=False
    )
    status: Mapped[ClusterStatus] = mapped_column(
        SQLEnum(ClusterStatus, name="cluster_status", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False,
        default=ClusterStatus.OPEN
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    members: Mapped[list["ClusterMember"]] = relationship(
        back_populates="cluster",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_clusters_canonical", "canonical_item_id"),
        Index("idx_clusters_status", "status"),
    )


class ClusterMember(Base):
    """Individual items belonging to a cluster."""
    __tablename__ = "cluster_members"

    cluster_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("clusters.id", ondelete="CASCADE"),
        primary_key=True
    )
    raw_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="CASCADE"),
        primary_key=True
    )
    is_canonical: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    similarity: Mapped[Optional[float]] = mapped_column(Float)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    cluster: Mapped["Cluster"] = relationship(back_populates="members")
    raw_item: Mapped["RawItem"] = relationship(back_populates="cluster_memberships")

    __table_args__ = (
        Index("idx_cluster_members_item", "raw_item_id"),
    )


# ============================================================================
# Item Scores (keep scoring history per item)
# ============================================================================

class ItemScore(Base):
    """Computed scores for each item (with history)."""
    __tablename__ = "item_scores"

    raw_item_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="CASCADE"),
        primary_key=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()",
        primary_key=True
    )
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    velocity_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    cross_source_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    signal_score: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    score_meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    __table_args__ = (
        Index("idx_item_scores_signal", "signal_score", "computed_at"),
    )


# ============================================================================
# Briefings
# ============================================================================

class Briefing(Base):
    """Daily briefings containing top signals."""
    __tablename__ = "briefings"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    scope: Mapped[str] = mapped_column(Text, nullable=False)  # "global" or "user:<uuid>"
    period_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    summary_md: Mapped[str] = mapped_column(Text, nullable=False)
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Relationships
    items: Mapped[list["BriefingItem"]] = relationship(
        back_populates="briefing",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_briefings_scope", "scope"),
        Index("idx_briefings_period", "period_start", "period_end"),
    )


class BriefingItem(Base):
    """Individual signals included in a briefing."""
    __tablename__ = "briefing_items"

    briefing_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("briefings.id", ondelete="CASCADE"),
        primary_key=True
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False, primary_key=True)
    cluster_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("clusters.id", ondelete="SET NULL")
    )
    raw_item_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="SET NULL")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    one_liner: Mapped[str] = mapped_column(Text, nullable=False)
    why_it_matters: Mapped[str] = mapped_column(Text, nullable=False)
    who_should_care: Mapped[Optional[str]] = mapped_column(Text)
    confidence: Mapped[str] = mapped_column(Text, nullable=False)  # low/med/high
    signal_score: Mapped[float] = mapped_column(Float, nullable=False)
    sources: Mapped[list] = mapped_column(JSONB, nullable=False, server_default="[]")

    # Relationships
    briefing: Mapped["Briefing"] = relationship(back_populates="items")


# ============================================================================
# Users
# ============================================================================

class User(Base):
    """User accounts."""
    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[Optional[str]] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_superuser: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    preferences: Mapped[Optional["UserPreference"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan",
        uselist=False
    )
    feedback: Mapped[list["UserFeedback"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )
    refresh_tokens: Mapped[list["RefreshToken"]] = relationship(
        back_populates="user",
        cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("idx_users_email", "email"),
    )


class UserPreference(Base):
    """User personalization settings."""
    __tablename__ = "user_preferences"

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True
    )
    topics: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    keywords_include: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    keywords_exclude: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    sources_blocked: Mapped[list[UUID]] = mapped_column(ARRAY(PGUUID(as_uuid=True)), nullable=False, server_default="{}")
    risk_tolerance: Mapped[int] = mapped_column(Integer, nullable=False, default=3)  # 1-5
    email_daily: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    email_time_utc: Mapped[time] = mapped_column(Time, nullable=False, server_default="'07:00'")
    timezone: Mapped[str] = mapped_column(Text, nullable=False, default="UTC")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="preferences")


# ============================================================================
# User Feedback
# ============================================================================

class UserFeedback(Base):
    """User feedback for learning."""
    __tablename__ = "user_feedback"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    cluster_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("clusters.id", ondelete="CASCADE")
    )
    raw_item_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("raw_items.id", ondelete="SET NULL")
    )
    kind: Mapped[FeedbackKind] = mapped_column(
        SQLEnum(FeedbackKind, name="feedback_kind", create_type=False, values_callable=lambda e: [x.value for x in e]),
        nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    meta: Mapped[dict] = mapped_column(JSONB, nullable=False, server_default="{}")

    # Relationships
    user: Mapped["User"] = relationship(back_populates="feedback")

    __table_args__ = (
        Index("idx_feedback_user_time", "user_id", "created_at"),
        Index("idx_feedback_cluster", "cluster_id"),
    )


# ============================================================================
# Refresh Tokens (for JWT auth)
# ============================================================================

class RefreshToken(Base):
    """Refresh tokens for JWT authentication."""
    __tablename__ = "refresh_tokens"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        server_default="gen_random_uuid()"
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default="now()"
    )
    revoked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))

    # Relationships
    user: Mapped["User"] = relationship(back_populates="refresh_tokens")

    __table_args__ = (
        Index("idx_refresh_tokens_user", "user_id"),
        Index("idx_refresh_tokens_hash", "token_hash"),
    )
