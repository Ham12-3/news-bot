// API Types

export interface User {
  id: string;
  email: string;
  display_name: string | null;
  email_verified: boolean;
}

export interface AuthResponse {
  user: User;
  access_token: string;
  refresh_token: string;
  token_type: string;
}

export interface Signal {
  id: string;
  title: string;
  url: string;
  source_name: string;
  source_type: string;
  published_at: string | null;
  signal_score: number;
  relevance: number;
  velocity: number;
  cross_source: number;
  novelty: number;
  content_preview: string | null;
}

export interface SignalDetail extends Signal {
  raw_text: string | null;
  canonical_url: string | null;
  score_explanation: Record<string, unknown> | null;
}

export interface SignalListResponse {
  signals: Signal[];
  total: number;
  has_more: boolean;
}

export interface Briefing {
  id: string;
  generated_at: string;
  sent_at: string | null;
  content: string;
}

export interface BriefingItem {
  id: string;
  title: string;
  url: string;
  source: string;
}

export interface BriefingDetail extends Briefing {
  items: BriefingItem[];
}

export interface Feedback {
  id: string;
  raw_item_id: string;
  kind: 'like' | 'dislike' | 'save' | 'hide';
  created_at: string;
}

export interface CategoryStats {
  category: string;
  count: number;
  avg_score: number;
}
