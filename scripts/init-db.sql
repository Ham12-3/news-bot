-- ============================================================================
-- News Intelligence Platform - Production Database Schema
-- ============================================================================

-- Extensions
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";
CREATE EXTENSION IF NOT EXISTS "vector";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";

-- ============================================================================
-- Enum Types
-- ============================================================================

DO $$ BEGIN
  CREATE TYPE source_type AS ENUM ('rss', 'api_hn', 'api_reddit', 'api_x', 'scrape');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE item_kind AS ENUM ('article', 'post', 'comment', 'tweet', 'unknown');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE cluster_status AS ENUM ('open', 'merged', 'archived');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
  CREATE TYPE feedback_kind AS ENUM ('up', 'down', 'save', 'hide');
EXCEPTION
  WHEN duplicate_object THEN null;
END $$;

-- ============================================================================
-- Sources
-- ============================================================================

CREATE TABLE IF NOT EXISTS sources (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name             text NOT NULL,
  type             source_type NOT NULL,
  url              text,
  metadata         jsonb NOT NULL DEFAULT '{}'::jsonb,
  category         text,
  enabled          boolean NOT NULL DEFAULT true,
  credibility_tier int NOT NULL DEFAULT 3, -- 1 high, 5 low
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sources_enabled ON sources(enabled);
CREATE INDEX IF NOT EXISTS idx_sources_type ON sources(type);

-- ============================================================================
-- Raw Items (one row per fetched entry)
-- ============================================================================

CREATE TABLE IF NOT EXISTS raw_items (
  id                 uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  source_id          uuid NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
  external_id        text,            -- hn id, reddit id, etc
  kind               item_kind NOT NULL DEFAULT 'unknown',
  title              text,
  url                text,
  author             text,
  published_at       timestamptz,
  fetched_at         timestamptz NOT NULL DEFAULT now(),
  lang               text,
  raw_payload        jsonb NOT NULL DEFAULT '{}'::jsonb,  -- store original response
  raw_text           text,                                 -- snippet or body if present
  canonical_url      text,
  content_hash       bytea,                                -- for quick exact dedup
  status             text NOT NULL DEFAULT 'new'           -- new, extracted, filtered, etc
);

CREATE INDEX IF NOT EXISTS idx_raw_items_source_time ON raw_items(source_id, fetched_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_items_published ON raw_items(published_at DESC);
CREATE INDEX IF NOT EXISTS idx_raw_items_url ON raw_items(url);
CREATE INDEX IF NOT EXISTS idx_raw_items_status ON raw_items(status);
CREATE INDEX IF NOT EXISTS idx_raw_items_content_hash ON raw_items(content_hash);
CREATE UNIQUE INDEX IF NOT EXISTS uq_raw_items_source_external
  ON raw_items(source_id, external_id) WHERE external_id IS NOT NULL;

-- ============================================================================
-- Extracted Content (clean article text)
-- ============================================================================

CREATE TABLE IF NOT EXISTS extracted_content (
  raw_item_id      uuid PRIMARY KEY REFERENCES raw_items(id) ON DELETE CASCADE,
  final_url        text,
  title            text,
  byline           text,
  text             text NOT NULL,
  html             text,
  word_count       int,
  extracted_at     timestamptz NOT NULL DEFAULT now(),
  extraction_meta  jsonb NOT NULL DEFAULT '{}'::jsonb
);

-- ============================================================================
-- Embeddings
-- ============================================================================

CREATE TABLE IF NOT EXISTS item_embeddings (
  raw_item_id      uuid PRIMARY KEY REFERENCES raw_items(id) ON DELETE CASCADE,
  embed_model      text NOT NULL,
  dim              int NOT NULL,
  embedding        vector(1536),
  created_at       timestamptz NOT NULL DEFAULT now()
);

-- IVFFlat index for pgvector (tune lists based on data size)
CREATE INDEX IF NOT EXISTS idx_item_embeddings_ivfflat
  ON item_embeddings USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

-- ============================================================================
-- Clusters (semantic dedup groups)
-- ============================================================================

CREATE TABLE IF NOT EXISTS clusters (
  id               uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  canonical_item_id uuid NOT NULL REFERENCES raw_items(id) ON DELETE RESTRICT,
  status           cluster_status NOT NULL DEFAULT 'open',
  created_at       timestamptz NOT NULL DEFAULT now(),
  updated_at       timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_clusters_canonical ON clusters(canonical_item_id);
CREATE INDEX IF NOT EXISTS idx_clusters_status ON clusters(status);

-- ============================================================================
-- Cluster Members
-- ============================================================================

CREATE TABLE IF NOT EXISTS cluster_members (
  cluster_id       uuid NOT NULL REFERENCES clusters(id) ON DELETE CASCADE,
  raw_item_id      uuid NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
  is_canonical     boolean NOT NULL DEFAULT false,
  similarity       real,
  added_at         timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (cluster_id, raw_item_id)
);

CREATE INDEX IF NOT EXISTS idx_cluster_members_item ON cluster_members(raw_item_id);

-- ============================================================================
-- Item Scores (keep scoring history per item)
-- ============================================================================

CREATE TABLE IF NOT EXISTS item_scores (
  raw_item_id        uuid NOT NULL REFERENCES raw_items(id) ON DELETE CASCADE,
  computed_at        timestamptz NOT NULL DEFAULT now(),
  relevance_score    real NOT NULL DEFAULT 0,
  novelty_score      real NOT NULL DEFAULT 0,
  velocity_score     real NOT NULL DEFAULT 0,
  cross_source_score real NOT NULL DEFAULT 0,
  signal_score       real NOT NULL DEFAULT 0,
  score_meta         jsonb NOT NULL DEFAULT '{}'::jsonb,
  PRIMARY KEY (raw_item_id, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_item_scores_signal
  ON item_scores(signal_score DESC, computed_at DESC);

-- ============================================================================
-- Briefings
-- ============================================================================

CREATE TABLE IF NOT EXISTS briefings (
  id              uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  scope           text NOT NULL, -- eg "global", "user:<uuid>"
  period_start    timestamptz NOT NULL,
  period_end      timestamptz NOT NULL,
  created_at      timestamptz NOT NULL DEFAULT now(),
  summary_md      text NOT NULL,
  meta            jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_briefings_scope ON briefings(scope);
CREATE INDEX IF NOT EXISTS idx_briefings_period ON briefings(period_start, period_end);

-- ============================================================================
-- Briefing Items (top signals included in briefing)
-- ============================================================================

CREATE TABLE IF NOT EXISTS briefing_items (
  briefing_id      uuid NOT NULL REFERENCES briefings(id) ON DELETE CASCADE,
  cluster_id       uuid REFERENCES clusters(id) ON DELETE SET NULL,
  raw_item_id      uuid REFERENCES raw_items(id) ON DELETE SET NULL,
  rank             int NOT NULL,
  title            text NOT NULL,
  one_liner        text NOT NULL,
  why_it_matters   text NOT NULL,
  who_should_care  text,
  confidence       text NOT NULL, -- low/med/high
  signal_score     real NOT NULL,
  sources          jsonb NOT NULL DEFAULT '[]'::jsonb,
  PRIMARY KEY (briefing_id, rank)
);

-- ============================================================================
-- Users
-- ============================================================================

CREATE TABLE IF NOT EXISTS users (
  id             uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email          text UNIQUE NOT NULL,
  hashed_password text NOT NULL,
  name           text,
  is_active      boolean NOT NULL DEFAULT true,
  is_superuser   boolean NOT NULL DEFAULT false,
  created_at     timestamptz NOT NULL DEFAULT now(),
  updated_at     timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);

-- ============================================================================
-- User Preferences
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_preferences (
  user_id           uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  topics            text[] NOT NULL DEFAULT '{}',
  keywords_include  text[] NOT NULL DEFAULT '{}',
  keywords_exclude  text[] NOT NULL DEFAULT '{}',
  sources_blocked   uuid[] NOT NULL DEFAULT '{}',
  risk_tolerance    int NOT NULL DEFAULT 3, -- 1 aggressive, 5 conservative
  email_daily       boolean NOT NULL DEFAULT true,
  email_time_utc    time NOT NULL DEFAULT '07:00',
  timezone          text NOT NULL DEFAULT 'UTC',
  updated_at        timestamptz NOT NULL DEFAULT now()
);

-- ============================================================================
-- User Feedback
-- ============================================================================

CREATE TABLE IF NOT EXISTS user_feedback (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  cluster_id    uuid REFERENCES clusters(id) ON DELETE CASCADE,
  raw_item_id   uuid REFERENCES raw_items(id) ON DELETE SET NULL,
  kind          feedback_kind NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  meta          jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS idx_feedback_user_time ON user_feedback(user_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_feedback_cluster ON user_feedback(cluster_id);

-- ============================================================================
-- Refresh Tokens (for JWT auth)
-- ============================================================================

CREATE TABLE IF NOT EXISTS refresh_tokens (
  id            uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  token_hash    text NOT NULL UNIQUE,
  expires_at    timestamptz NOT NULL,
  created_at    timestamptz NOT NULL DEFAULT now(),
  revoked_at    timestamptz
);

CREATE INDEX IF NOT EXISTS idx_refresh_tokens_user ON refresh_tokens(user_id);
CREATE INDEX IF NOT EXISTS idx_refresh_tokens_hash ON refresh_tokens(token_hash);

-- ============================================================================
-- Helper Functions
-- ============================================================================

-- Content hash helper
CREATE OR REPLACE FUNCTION make_content_hash(t text)
RETURNS bytea LANGUAGE sql IMMUTABLE AS $$
  SELECT digest(coalesce(t, ''), 'sha256');
$$;

-- Updated at trigger function
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Apply updated_at triggers
DROP TRIGGER IF EXISTS update_sources_updated_at ON sources;
CREATE TRIGGER update_sources_updated_at BEFORE UPDATE ON sources
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_clusters_updated_at ON clusters;
CREATE TRIGGER update_clusters_updated_at BEFORE UPDATE ON clusters
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_users_updated_at ON users;
CREATE TRIGGER update_users_updated_at BEFORE UPDATE ON users
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();

DROP TRIGGER IF EXISTS update_user_preferences_updated_at ON user_preferences;
CREATE TRIGGER update_user_preferences_updated_at BEFORE UPDATE ON user_preferences
    FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
