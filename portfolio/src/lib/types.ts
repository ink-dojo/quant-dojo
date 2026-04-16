import type { FactorCategory } from "./constants";

export interface ICStats {
  source_name: string;
  category_zh: string;
  ic_mean: number;
  icir: number;
  ic_positive_pct: number;
  fm_t_stat: number;
  verdict: string;
}

export interface FactorSummary {
  name: string;
  category: FactorCategory;
  lineno: number;
  docstring_first: string;
  has_compute_func: boolean;
  has_research_folder: boolean;
  research_folder_slug: string | null;
  has_dedicated_notebook: boolean;
  has_ic_stats: boolean;
  ic_stats: ICStats | null;
  in_v7_strategy: boolean;
  in_v16_strategy: boolean;
  in_latest_snapshot: boolean;
  coverage_score: number;
}

export interface FactorIndex {
  generated_at: string;
  source_file: string;
  total_factors: number;
  with_ic_stats: number;
  with_research_folder: number;
  in_v7_strategy: number;
  in_v16_strategy: number;
  by_category: Record<string, string[]>;
  factors: FactorSummary[];
}

export interface StrategyMetrics {
  annualized_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  information_ratio: number | null;
  total_return: number | null;
  start_date: string | null;
  end_date: string | null;
  n_trading_days: number | null;
}

export interface StrategyVersion {
  id: string;
  role: "research_face" | "production_face" | "historical" | "pending";
  label: string;
  summary: string;
  factors: string[];
  metrics: StrategyMetrics | null;
  run_id: string | null;
  commit: string | null;
  notes: string[];
}

export interface StrategyVersionsFile {
  generated_at: string;
  research_face: string;
  production_face: string;
  versions: StrategyVersion[];
}

export interface EquityPoint {
  date: string;
  nav: number;
}

export interface EquityCurve {
  version: string;
  series: EquityPoint[];
  metrics: StrategyMetrics;
}

export interface Phase {
  id: number;
  title: string;
  subtitle: string;
  period: string;
  status: "complete" | "in_progress" | "pending";
  deliverables: string[];
  key_decision: string | null;
  metrics: Record<string, number | string> | null;
}

export interface JourneyFile {
  generated_at: string;
  phases: Phase[];
}

export interface HeroFactorStats {
  name: string;
  ic_series: { date: string; ic: number }[];
  decay_curve: { lag: number; ic: number }[];
  quintile: {
    labels: string[];
    annual_returns: number[];
    sharpes: number[];
  };
  formula_latex: string;
  economic_intuition: string;
  implementation_code: string;
  stats: {
    ic_mean: number;
    ic_std: number;
    icir: number;
    t_stat: number;
    ic_positive_pct: number;
    half_life_days: number | null;
    long_short_annual: number;
    long_short_sharpe: number;
  };
  related_factors: string[];
}

export interface HeroFactorsFile {
  generated_at: string;
  computed_period: { start: string; end: string };
  hero_factors: HeroFactorStats[];
}
