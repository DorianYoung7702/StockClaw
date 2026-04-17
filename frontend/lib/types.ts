/* --------------------------------------------------------
   TypeScript interfaces matching Atlas backend schemas
   -------------------------------------------------------- */

export interface ChatMessage {
  role: "user" | "assistant" | "system";
  content: string;
  toolStatus?: string;
  /** Ticker options for Human-in-the-loop disambiguation */
  disambiguateOptions?: string[];
  /** True for harness system notifications (recovery, compaction, etc.) */
  isSystem?: boolean;
}

export interface ChatResponse {
  session_id: string;
  message: string;
  usage?: Record<string, unknown>;
  timestamp: string;
}

export interface StrongStock {
  ticker: string;
  name: string;
  reason: string;
  rsi: number;
  momentum_score: number;
  avg_volume: number;
  risk_level: "low" | "medium" | "high";
  trend: "strong" | "neutral" | "weak";
  market_type: string;
  // Quantitative metrics from screening
  rs_20d?: number;
  vol_score?: number;
  trend_r2?: number;
  performance_20d?: number;
  performance_40d?: number;
  performance_90d?: number;
  performance_180d?: number;
  current_price?: number;
}

export interface StrongStocksResponse {
  market_type: string;
  stocks: StrongStock[];
  filters_applied: Record<string, unknown>;
  timestamp: string;
}

export interface AnalysisSection {
  title: string;
  score: number; // 0-100
  summary: string;
  details: string[];
}

export interface PeerComparison {
  ticker: string;
  name: string;
  pe: number;
  pb: number;
  roe: number;
  market_cap: string;
}

export interface AnalysisEvidence {
  id: string;
  source_type: string;
  source_label: string;
  ticker?: string;
  title: string;
  snippet: string;
  score?: number | null;
  published_at?: string | null;
  url?: string | null;
  doc_label?: string | null;
  metadata?: Record<string, unknown>;
}

export interface RetrievalDebugEntry {
  status?: string;
  query?: string;
  effective_query?: string;
  rewrite_from_query?: string;
  top_k?: number;
  hit_count?: number;
  raw_item_count?: number;
  source_distribution?: Record<string, number>;
  per_ticker?: Record<string, Record<string, unknown>>;
  ticker?: string;
  scope?: string;
}

export interface StockAnalysis {
  ticker: string;
  name: string;
  conclusion: string;
  recommendation: "观察" | "关注" | "谨慎";
  sections: AnalysisSection[];
  peers: PeerComparison[];
  risks: string[];
  evidence_chain?: AnalysisEvidence[];
  retrieval_debug?: Record<string, RetrievalDebugEntry>;
  updated_at: string;
}

export interface WatchlistItem {
  ticker: string;
  note: string;
  added_at: string;
}

export interface WatchlistGroup {
  id: string;
  name: string;
  color: string;
  items: WatchlistItem[];
}

export interface SubscriptionPlan {
  id: string;
  name: string;
  price: string;
  period: string;
  features: string[];
  highlighted: boolean;
  cta: string;
}

export type SortField =
  | "momentum_score"
  | "performance_20d"
  | "performance_40d"
  | "performance_90d"
  | "performance_180d"
  | "rs_20d"
  | "vol_score"
  | "trend_r2"
  | "volume_5d_avg";

export interface ScreeningConfig {
  market_type: "us_stock" | "hk_stock" | "etf";
  top_count: number;
  rsi_threshold: number;
  momentum_days: number[];
  top_volume_count: number;
  sort_by: SortField;
  min_volume_turnover?: number;
}
