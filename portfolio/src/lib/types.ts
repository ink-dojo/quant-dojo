import type { FactorCategory } from "./constants";

export interface Meta {
  generated_at: string;
  coverage_generated_at: string;
  git: { sha: string | null; short: string | null; subject: string | null };
  face: { research: string; production: string };
}

export interface FactorIndexItem {
  name: string;
  category: FactorCategory;
  docstring: string;
  coverage_score: number;
  has_research_folder: boolean;
  research_slug: string | null;
  in_v7: boolean;
  in_v16: boolean;
  in_snapshot: boolean;
  ic_mean: number | null;
  icir: number | null;
  fm_t_stat: number | null;
  verdict: string | null;
}

export interface FactorIndex {
  generated_at: string;
  total: number;
  with_ic_stats: number;
  with_research_folder: number;
  in_v7_strategy: number;
  in_v16_strategy: number;
  by_category_counts: Record<string, number>;
  factors: FactorIndexItem[];
}

export type HeroTier = "core" | "experimental";

export interface HeroFactor {
  name: string;
  tier: HeroTier;
  title_en: string;
  title_zh: string;
  pitch: string;
  category: FactorCategory;
  docstring: string;
  coverage_score: number;
  research_slug: string | null;
  lineno: number;
  in_v7: boolean;
  in_v16: boolean;
  ic_mean: number | null;
  icir: number | null;
  ic_positive_pct: number | null;
  fm_t_stat: number | null;
  verdict: string | null;
  has_ic_stats: boolean;
}

export interface HeroFactorsFile {
  generated_at: string;
  factors: HeroFactor[];
}

export interface ICSummary {
  ic_mean: number | null;
  ic_std: number | null;
  icir: number | null;
  t_stat: number | null;
  pct_pos: number | null;
  n: number;
}

export interface ICMonthlyPoint {
  date: string;
  ic: number;
}

export interface DecayPayload {
  ic_by_lag: { lag: number; ic: number | null }[];
  half_life_days: number | null;
  decay_rate: number | null;
  ic_0: number | null;
  fit_quality: number | null;
  recommended_rebalance_freq: string;
}

export interface QuintilePoint {
  date: string;
  Q1: number | null;
  Q2: number | null;
  Q3: number | null;
  Q4: number | null;
  Q5: number | null;
}

export interface LongShortStats {
  ann_return?: number;
  ann_vol?: number;
  sharpe?: number | null;
  max_drawdown?: number;
  total_return?: number;
  n_days?: number;
}

export interface HeroDetailEntry {
  name: string;
  direction?: "positive" | "reversal";
  fwd_days?: number;
  ic?: { summary: ICSummary; monthly: ICMonthlyPoint[] };
  decay?: DecayPayload;
  quintile?: {
    direction: string;
    cum_monthly: QuintilePoint[];
    ls_stats: LongShortStats;
  };
  error?: string;
}

export interface HeroDetailFile {
  generated_at: string;
  window: {
    warmup_start: string;
    analysis_start: string;
    analysis_end: string;
  };
  fwd_days: number;
  universe_size: number;
  trading_days: number;
  factors: Record<string, HeroDetailEntry>;
}

export interface StrategyMetrics {
  total_return: number | null;
  annualized_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  volatility: number | null;
  win_rate: number | null;
  n_trading_days: number | null;
  period_start: string | null;
  period_end: string | null;
}

export type StrategyStatus =
  | "legacy"
  | "research-face"
  | "production"
  | "candidate"
  | "rejected"
  | "running";

export interface StrategyVersion {
  id: string;
  name_en: string;
  name_zh: string;
  tagline: string;
  status: StrategyStatus;
  era_start: string;
  factors: string[];
  highlights?: string[];
  eval_report?: string;
  is_active: boolean;
  run_id: string | null;
  metrics: StrategyMetrics | null;
  equity_file: string | null;
}

export interface StrategyVersionsFile {
  generated_at: string;
  active_strategy: string | null;
  active_note: string | null;
  research_face: string;
  production_face: string;
  versions: StrategyVersion[];
}

export interface EquityPoint {
  date: string;
  cum_return: number;
}

export interface EquityCurveFile {
  strategy: string;
  points: EquityPoint[];
}

export type PhaseStatus = "done" | "running" | "planned";

export interface Phase {
  id: string;
  label: string;
  title: string;
  status: PhaseStatus;
  checks_total: number;
  checks_done: number;
  progress: number | null;
}

export interface JourneyFile {
  generated_at: string;
  source: string;
  phases: Phase[];
}
