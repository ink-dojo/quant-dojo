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

export interface GateCheck {
  value: number | boolean;
  threshold: number | boolean;
  pass: boolean;
}

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
  gate_check?: Record<string, GateCheck>;
  is_active: boolean;
  run_id: string | null;
  metrics: StrategyMetrics | null;
  equity_file: string | null;
}

export interface StrategyVersionsFile {
  generated_at: string;
  production_face: string;
  research_face: string;
  candidate: string;
  declared_active: string | null;
  declared_note: string | null;
  face_note: string;
  versions: StrategyVersion[];
}

export interface CandidateRow {
  id: string;
  change_zh: string;
  run_id: string;
  strategy_name: string;
  created_at: string;
  status: string;
  annualized_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  win_rate: number | null;
  selected: boolean;
}

export interface CandidatesFile {
  session_date: string;
  session_note: string;
  selected: string;
  candidates: CandidateRow[];
}

export interface CandidateReviewGate {
  ann_return_ge_15pct: boolean;
  sharpe_ge_08: boolean;
  max_dd_gt_neg30pct: boolean;
  psr_ge_95pct: boolean;
  all_pass: boolean;
}

export interface CandidateReviewRow {
  version: string;
  n_days: number;
  period_start: string;
  period_end: string;
  ann_return: number;
  ann_volatility: number;
  sharpe: number;
  max_drawdown: number;
  win_rate: number;
  psr_vs_zero: number;
  psr_vs_admission_gate: number;
  sharpe_ci_low: number;
  sharpe_ci_high: number;
  mintrl_days: number | null;
  dsr: number;
  dsr_trials: number;
  dsr_sharpe_std: number;
  gate: CandidateReviewGate;
  equity_file: string;
}

export interface CandidateReviewFile {
  generated_at: string;
  n_candidates: number;
  selection_pool_sharpe_std: number;
  admission_gate_note: string;
  candidates: CandidateReviewRow[];
}

export interface EquityPoint {
  date: string;
  cum_return: number;
}

export interface EquityCurveFile {
  strategy: string;
  points: EquityPoint[];
}

export interface LiveRunSummary {
  run_id: string;
  strategy_id: string;
  strategy_name: string;
  status: string;
  created_at: string;
  annualized_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
}

export interface LiveDashboard {
  generated_at: string;
  declared_active: string | null;
  declared_note: string | null;
  state_updated_at: string | null;
  production_face: string;
  candidate: string;
  last_signal_strategy: string | null;
  signal_dates: string[];
  snapshot_dates: string[];
  recent_runs: LiveRunSummary[];
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

export interface CategoryRepFactor {
  name: string;
  why: string;
}

export interface CategoryOverview {
  key: FactorCategory;
  label_zh: string;
  label_en: string;
  one_liner: string;
  intuition: string;
  a_share_specifics: string[];
  representative_factors: CategoryRepFactor[];
  common_pitfalls: string[];
  references: string[];
}

export interface CategoriesFile {
  generated_at: string;
  note?: string;
  categories: Record<FactorCategory, CategoryOverview>;
}

export interface GlossaryTerm {
  key: string;
  term_en: string;
  term_zh: string;
  category: string;
  formula_latex?: string | null;
  formula_caption?: string | null;
  intuition: string;
  typical_values?: string | null;
  pitfall?: string | null;
  related: string[];
}

export interface GlossaryFile {
  generated_at: string;
  note?: string;
  terms: GlossaryTerm[];
}

export type DSRStatus =
  | "paper_trade_candidate"
  | "retired"
  | "failed"
  | "component"
  | "active"
  | "archived";

export interface DSRGates {
  ann_ge_15pct: boolean | null;
  sharpe_ge_08: boolean | null;
  mdd_gt_neg30pct: boolean | null;
  psr_ge_95pct: boolean | null;
  ci_low_ge_05: boolean | null;
  n_pass: number;
}

export interface DSRMetrics {
  n_obs: number | null;
  ann_return: number | null;
  sharpe: number | null;
  max_drawdown: number | null;
  psr: number | null;
  sharpe_ci_low: number | null;
  sharpe_ci_high: number | null;
}

export interface DSRSizing {
  unit: string;
  gross_cap: number;
}

export interface DSRStrategy {
  id: string;
  name_en: string;
  name_zh: string;
  status: DSRStatus;
  status_note?: string;
  category: string;
  tagline: string;
  event_source: string;
  universe_filter: string;
  hold_window: string;
  direction: "LONG" | "SHORT" | "NEUTRAL";
  sizing: DSRSizing;
  theory: string;
  metrics_8yr: DSRMetrics;
  recent_24m_sharpe: number | null;
  gates_5: DSRGates;
  highlights: string[];
  failure_modes: string[];
  decay_evidence?: string | null;
  equity_file: string | null;
  paper_trade_spec?: string | null;
  refs: string[];
}

export interface DSRTrialsSummary {
  total_trials: number;
  pass_4_of_5: number;
  pass_5_of_5_ensemble: number;
  note?: string;
}

export interface DSRStrategiesFile {
  generated_at: string;
  note?: string;
  strategies: DSRStrategy[];
  trials_summary?: DSRTrialsSummary;
}

export type TimelineVersionStatus =
  | "legacy"
  | "production"
  | "rejected"
  | "mining-round"
  | "candidate"
  | "active";

export interface TimelineVersion {
  id: string;
  name_en: string;
  name_zh: string;
  date: string;
  status: TimelineVersionStatus;
  motivation: string;
  method: string;
  result: string;
  lessons: string[];
  next_trigger?: string;
}

export interface TimelineEra {
  id: string;
  era_label: string;
  theme: string;
  versions: TimelineVersion[];
}

export interface StrategyTimelineFile {
  generated_at: string;
  note?: string;
  eras: TimelineEra[];
}

export interface FactorDetail {
  formula_latex?: string | null;
  formula_caption?: string | null;
  intuition: string;
  a_share: string;
  pitfall: string;
  refs: string[];
}

export interface FactorDetailsFile {
  generated_at: string;
  note?: string;
  factors: Record<string, FactorDetail>;
}

export interface FactorLinenoFile {
  generated_at: string;
  source_file: string;
  note?: string;
  lineno: Record<string, number>;
}
