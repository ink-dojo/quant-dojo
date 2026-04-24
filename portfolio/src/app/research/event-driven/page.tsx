import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { EquityChart } from "@/components/viz/EquityChart";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { DisclosurePanel, EvidenceCard, SectionLabel } from "@/components/layout/Primitives";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import type { DSRStrategiesFile, EquityCurveFile } from "@/lib/types";

interface Trial {
  id: number;
  name: string;
  factor: string;
  n_pass: number;
  ann: number;
  sharpe: number;
  mdd: number;
  psr: number;
  ci_low: number;
  status: "candidate" | "fail" | "falsified";
}

interface Gates {
  ann_ge_15pct: boolean;
  sharpe_ge_08: boolean;
  mdd_gt_neg30pct: boolean;
  psr_ge_95pct: boolean;
  ci_low_ge_05: boolean;
}

interface CandidateBlock {
  ann_return: number;
  sharpe: number;
  max_drawdown: number;
  psr: number;
  sharpe_ci_low: number;
  sharpe_ci_high: number;
  n_obs: number;
  gates: Gates;
  n_pass: number;
}

interface EnsembleBlock extends CandidateBlock {
  correlation: number;
}

interface TrialsFile {
  generated_at: string;
  n_trials_conservative: number;
  n_pass_4_of_5: number;
  candidates: string[];
  ensemble_50_50: EnsembleBlock;
  dsr30: CandidateBlock;
  dsr33: CandidateBlock;
  trials: Trial[];
}

interface WFSummary {
  label: string;
  n_windows: number;
  window_years: number;
  step_months: number;
  sharpe_median: number;
  sharpe_q25: number;
  sharpe_q75: number;
  sharpe_min: number;
  sharpe_max: number;
  ann_median: number;
  mdd_median: number;
  mdd_worst: number;
  gate_median_gt_05: boolean;
  gate_q25_gt_0: boolean;
}

interface RegimeBlock {
  label: string;
  regimes: Record<
    string,
    { n_obs: number; ann: number; sharpe: number; mdd: number }
  >;
  gate_2of3_pass: boolean;
  n_pass: number;
}

interface YearRow {
  year: number;
  n_obs: number;
  ann: number;
  ret_total: number;
  sharpe: number;
  mdd: number;
}

interface TradeLevel {
  n_trades: number;
  win_rate: number;
  avg_pnl: number;
  median_pnl: number;
  pnl_p05: number;
  pnl_p95: number;
  avg_holding_days: number;
  top5_contribution_share: number;
  gate_win_rate_gt_45: boolean;
  gate_top5_concentration_lt_20pct: boolean;
}

interface CostRow {
  cost_one_side: number;
  ann: number;
  sharpe: number;
  mdd: number;
  n_obs: number;
}

interface WFStressFile {
  generated_at: string;
  wf: { dsr30: WFSummary; dsr33: WFSummary; ensemble: WFSummary };
  regime: { dsr30: RegimeBlock; dsr33: RegimeBlock; ensemble: RegimeBlock };
  cost_sensitivity_dsr33: Record<string, CostRow>;
  year_by_year_ensemble: YearRow[];
  year_by_year_dsr30: YearRow[];
  year_by_year_dsr33: YearRow[];
  trade_level_dsr33: TradeLevel;
  production_verdict: { gates: Record<string, boolean>; n_pass: number };
}

export default async function EventDrivenPage() {
  const [trials, eq30, eq33, eqEns, wf, catalog] = await Promise.all([
    readData<TrialsFile>("event_driven/trials.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr30_bb.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr33_lhb_decline.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr30_33_ensemble.json"),
    readData<WFStressFile>("event_driven/wf_stress.json"),
    readDataOrNull<DSRStrategiesFile>("event_driven/strategies.json"),
  ]);

  const byStatus = {
    candidate: trials.trials.filter((t) => t.status === "candidate"),
    falsified: trials.trials.filter((t) => t.status === "falsified"),
    fail: trials.trials.filter((t) => t.status === "fail"),
  };

  const series = [
    { id: "dsr30", label: "#30 BB 主板 rescaled (4/5)", color: "var(--blue)", curve: eq30, dashed: false },
    { id: "dsr33", label: "#33 LHB 跌幅 contrarian (4/5)", color: "var(--gold)", curve: eq33, dashed: false },
    { id: "ens", label: "50/50 ensemble (5/5)", color: "var(--green)", curve: eqEns, dashed: false },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Research · Event-driven"
        title="Event-driven trials"
        subtitle={`${trials.trials.length} tabulated trials · ${trials.n_pass_4_of_5} single-leg 4/5 · one 5/5 ensemble`}
        description="Corporate-action and order-flow hypotheses are tracked as case files. The summary shows gate outcomes; details open below."
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: "Event-Driven" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard tone="blue" label="Trials" value={String(trials.trials.length)} detail={`DSR penalty n=${trials.n_trials_conservative}`} />
          <EvidenceCard tone="gold" label="Single legs" value={`${trials.n_pass_4_of_5} × 4/5`} detail="No standalone leg passed all gates" />
          <EvidenceCard tone="green" label="Ensemble" value="5/5" detail={`corr ${fmtNum(trials.ensemble_50_50.correlation, 2)}`} />
          <EvidenceCard tone="red" label="Failure files" value={String(byStatus.fail.length + byStatus.falsified.length)} detail="kept in the trial table" />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-10">
        <DisclosurePanel
          tone="green"
          title="Why the ensemble passed"
          summary="DSR #30 failed CI_low; DSR #33 failed MDD. The combination reduced the separate failure modes."
        >
          <p>
            The combination rule is fixed at 50/50. It is shown here as a
            research outcome, while the live page remains the source of truth
            for what is actually running.
          </p>
        </DisclosurePanel>
      </section>

      {catalog && catalog.strategies.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <SectionLabel
            eyebrow="Catalog"
            title="Open a strategy file"
            body="Each file contains event definition, universe, holding window, gates, failure modes, decay evidence, and paper-trade spec if applicable."
          />
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
            {catalog.strategies.map((s) => (
              <Link
                key={s.id}
                href={`/research/event-driven/${s.id}`}
                className="group block p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
              >
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
                    {s.name_en}
                  </span>
                  <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] shrink-0">
                    {s.gates_5.n_pass}/5
                  </span>
                </div>
                <div className="text-[10px] font-mono text-[var(--text-tertiary)] mb-2">
                  {s.id} · {s.name_zh}
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                  {s.tagline}
                </p>
                <div className="mt-2 flex flex-wrap gap-3 text-[10px] font-mono text-[var(--text-tertiary)]">
                  <span>SR={fmtNum(s.metrics_8yr.sharpe, 2)}</span>
                  <span>MDD={fmtPct(s.metrics_8yr.max_drawdown, 1)}</span>
                  <span>24m={fmtNum(s.recent_24m_sharpe, 2)}</span>
                </div>
              </Link>
            ))}
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          50/50 Ensemble · 5/5 PASS
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          零 DoF combination (1/2 · #30 + 1/2 · #33), 主板 only, 成本 15bps/side,
          gross cap 1.0 已施加于每个 sleeve。图为 log-equity (Y 轴为 log(1+累计收益))
          — 因为 #33 单独 8 年累计 55×，线性坐标会把其他两条压成直线。
          <span className="text-[var(--green)] font-semibold"> 观察组合曲线尾部浅于两成分</span>
          但上行斜率稳于 #30。
        </p>
        <div className="rounded-lg border border-[var(--green)]/30 bg-[var(--green)]/[0.05] p-4 mb-6">
          <EquityChart series={series} height={400} logScale />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <EnsembleMetricCard
            tag="5/5 gate"
            headline={`${fmtPct(trials.ensemble_50_50.ann_return, 1)}`}
            subline={`ann · SR ${fmtNum(trials.ensemble_50_50.sharpe, 2)}`}
            body={`MDD ${fmtPct(trials.ensemble_50_50.max_drawdown, 1)} < -30% 红线；Bootstrap CI_low ${fmtNum(trials.ensemble_50_50.sharpe_ci_low, 2)} >> 0.5 gate.`}
            tone="green"
          />
          <EnsembleMetricCard
            tag="Diversification"
            headline={`ρ = ${fmtNum(trials.ensemble_50_50.correlation, 2)}`}
            subline={`独立失败模式`}
            body={`#30 tail 稳 CI 弱 · #33 CI 超强 tail 失控。Equal-weight 把两条曲线的缺陷抵消。`}
            tone="blue"
          />
          <EnsembleMetricCard
            tag="PSR · DSR-aware"
            headline={`${fmtPct(trials.ensemble_50_50.psr, 1)}`}
            subline={`vs zero, n = ${trials.ensemble_50_50.n_obs}`}
            body={`从 ${trials.n_trials_conservative} 个 pre-reg trials 里挑 2 个做 ensemble — 选择偏差已在 DSR penalty 层面 bookkeep.`}
            tone="gold"
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <div className="flex items-baseline gap-3 mb-1">
          <h2 className="text-xl font-semibold text-[var(--text-primary)]">
            Admission gate · {wf.production_verdict.n_pass}/5 PASS
          </h2>
          <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--green)]">
            WF · Regime · Cost · Trade
          </span>
        </div>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          单样本 5/5 只是入场券 — 真正决定能不能上 paper-trade 的是
          <span className="text-[var(--text-primary)]"> walk-forward 中位 Sharpe / 牛熊分区 / 成本冲击 / 交易级集中度</span>。
          五条都过, 才能进入 paper-trade review。
        </p>
        <div className="rounded-lg border border-[var(--green)]/35 bg-[var(--green)]/[0.06] p-5 mb-6">
          <ul className="grid grid-cols-1 md:grid-cols-2 gap-y-2 gap-x-6 text-sm">
            {Object.entries(wf.production_verdict.gates).map(([name, pass]) => (
              <li key={name} className="flex items-start gap-2 font-mono">
                <span style={{ color: pass ? "var(--green)" : "var(--red)" }}>
                  {pass ? "✓" : "✗"}
                </span>
                <span className="text-[var(--text-secondary)]">{name}</span>
              </li>
            ))}
          </ul>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-6">
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
              Walk-forward · rolling {wf.wf.ensemble.window_years}yr / step {wf.wf.ensemble.step_months}mo
            </h3>
            <p className="text-xs text-[var(--text-tertiary)] mb-3">
              {wf.wf.ensemble.n_windows} 独立窗口, 每窗样本外 Sharpe
            </p>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                  <th className="text-left py-2 font-normal">策略</th>
                  <th className="text-right py-2 font-normal">median SR</th>
                  <th className="text-right py-2 font-normal">Q25 SR</th>
                  <th className="text-right py-2 font-normal">min / max</th>
                  <th className="text-right py-2 font-normal">worst MDD</th>
                </tr>
              </thead>
              <tbody className="text-[var(--text-secondary)]">
                {[
                  { k: "dsr30", label: "#30 BB", d: wf.wf.dsr30 },
                  { k: "dsr33", label: "#33 LHB", d: wf.wf.dsr33 },
                  { k: "ens", label: "ensemble", d: wf.wf.ensemble },
                ].map((r) => (
                  <tr key={r.k} className="border-b border-[var(--border-soft)] last:border-b-0">
                    <td className="py-2 text-[var(--text-primary)]">{r.label}</td>
                    <td
                      className="py-2 text-right"
                      style={{ color: r.d.sharpe_median >= 0.5 ? "var(--green)" : "var(--red)" }}
                    >
                      {fmtNum(r.d.sharpe_median, 2)}
                    </td>
                    <td
                      className="py-2 text-right"
                      style={{ color: r.d.sharpe_q25 > 0 ? "var(--green)" : "var(--red)" }}
                    >
                      {fmtNum(r.d.sharpe_q25, 2)}
                    </td>
                    <td className="py-2 text-right text-[var(--text-tertiary)]">
                      {fmtNum(r.d.sharpe_min, 1)} / {fmtNum(r.d.sharpe_max, 1)}
                    </td>
                    <td className="py-2 text-right text-[var(--red)]">
                      {fmtPct(r.d.mdd_worst, 1)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
              Regime split · 牛 / 熊 / 震荡
            </h3>
            <p className="text-xs text-[var(--text-tertiary)] mb-3">
              按 CSI300 年度方向切三期, 2018 / 2022 为熊
            </p>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                  <th className="text-left py-2 font-normal">Regime</th>
                  <th className="text-right py-2 font-normal">#30</th>
                  <th className="text-right py-2 font-normal">#33</th>
                  <th className="text-right py-2 font-normal">ensemble</th>
                </tr>
              </thead>
              <tbody className="text-[var(--text-secondary)]">
                {(["bull", "bear", "sideways"] as const).map((rg) => (
                  <tr key={rg} className="border-b border-[var(--border-soft)] last:border-b-0">
                    <td className="py-2 text-[var(--text-primary)]">
                      {rg === "bull" ? "牛" : rg === "bear" ? "熊" : "震荡"}
                      <span className="text-[10px] text-[var(--text-tertiary)] ml-1">
                        (n={wf.regime.ensemble.regimes[rg].n_obs})
                      </span>
                    </td>
                    {(["dsr30", "dsr33", "ensemble"] as const).map((k) => {
                      const r = wf.regime[k].regimes[rg];
                      return (
                        <td
                          key={k}
                          className="py-2 text-right"
                          style={{ color: r.sharpe > 0.5 ? "var(--green)" : r.sharpe > 0 ? "var(--text-secondary)" : "var(--red)" }}
                        >
                          SR {fmtNum(r.sharpe, 2)}
                          <span className="text-[10px] text-[var(--text-tertiary)] ml-1">
                            ({fmtPct(r.ann, 0)})
                          </span>
                        </td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-[var(--text-tertiary)] mt-3 leading-relaxed">
              #30 在熊市 SR 0.01 (近 flat), #33 在熊市反而 SR +6.26 (reversion 逻辑在恐慌里最有效), ensemble 三期全过 — 这是组合 diversification 的最直接证据。
            </p>
          </div>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-5 mb-6">
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
              Cost sensitivity · DSR #33 重跑
            </h3>
            <p className="text-xs text-[var(--text-tertiary)] mb-3">
              按单边 bps 横扫, 找到 Sharpe 0.8 break-even
            </p>
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                  <th className="text-left py-2 font-normal">单边</th>
                  <th className="text-right py-2 font-normal">ann</th>
                  <th className="text-right py-2 font-normal">Sharpe</th>
                  <th className="text-right py-2 font-normal">MDD</th>
                </tr>
              </thead>
              <tbody className="text-[var(--text-secondary)]">
                {Object.entries(wf.cost_sensitivity_dsr33).map(([bps, c]) => (
                  <tr key={bps} className="border-b border-[var(--border-soft)] last:border-b-0">
                    <td className="py-2 text-[var(--text-primary)]">{bps}</td>
                    <td
                      className="py-2 text-right"
                      style={{ color: c.ann >= 0.15 ? "var(--green)" : c.ann > 0 ? "var(--text-secondary)" : "var(--red)" }}
                    >
                      {fmtPct(c.ann, 1)}
                    </td>
                    <td
                      className="py-2 text-right"
                      style={{ color: c.sharpe >= 0.8 ? "var(--green)" : c.sharpe > 0 ? "var(--text-secondary)" : "var(--red)" }}
                    >
                      {fmtNum(c.sharpe, 2)}
                    </td>
                    <td
                      className="py-2 text-right"
                      style={{ color: c.mdd > -0.3 ? "var(--green)" : "var(--red)" }}
                    >
                      {fmtPct(c.mdd, 0)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-[10px] text-[var(--text-tertiary)] mt-3 leading-relaxed">
              至 75bps (pre-reg 的 5× 强假设) ann 仍 +37%. 100bps 以上 MDD 快速失控 — paper-trade 必须盯住 execution slippage。
            </p>
          </div>

          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-1">
              Trade-level · DSR #33 per-event
            </h3>
            <p className="text-xs text-[var(--text-tertiary)] mb-3">
              {wf.trade_level_dsr33.n_trades.toLocaleString()} 笔独立事件分解
            </p>
            <dl className="grid grid-cols-2 gap-y-2 text-xs font-mono">
              <dt className="text-[var(--text-tertiary)]">win rate</dt>
              <dd className="text-right" style={{ color: wf.trade_level_dsr33.gate_win_rate_gt_45 ? "var(--green)" : "var(--red)" }}>
                {fmtPct(wf.trade_level_dsr33.win_rate, 1)}
              </dd>
              <dt className="text-[var(--text-tertiary)]">avg P&L / trade</dt>
              <dd className="text-right text-[var(--green)]">
                {fmtPct(wf.trade_level_dsr33.avg_pnl, 2)}
              </dd>
              <dt className="text-[var(--text-tertiary)]">median P&L</dt>
              <dd className="text-right text-[var(--text-secondary)]">
                {fmtPct(wf.trade_level_dsr33.median_pnl, 2)}
              </dd>
              <dt className="text-[var(--text-tertiary)]">p05 / p95</dt>
              <dd className="text-right text-[var(--text-secondary)]">
                {fmtPct(wf.trade_level_dsr33.pnl_p05, 1)} / {fmtPct(wf.trade_level_dsr33.pnl_p95, 1)}
              </dd>
              <dt className="text-[var(--text-tertiary)]">avg holding</dt>
              <dd className="text-right text-[var(--text-secondary)]">
                {fmtNum(wf.trade_level_dsr33.avg_holding_days, 1)}d
              </dd>
              <dt className="text-[var(--text-tertiary)]">top-5 concentration</dt>
              <dd className="text-right" style={{ color: wf.trade_level_dsr33.gate_top5_concentration_lt_20pct ? "var(--green)" : "var(--red)" }}>
                {fmtPct(wf.trade_level_dsr33.top5_contribution_share, 1)}
              </dd>
            </dl>
            <p className="text-[10px] text-[var(--text-tertiary)] mt-3 leading-relaxed">
              54% 胜率 · top-5 仅占 6% — 说明 alpha 不依赖极少数爆仓股,
              收益分布厚尾但不极度偏. 这是 reversion 策略应有的 profile。
            </p>
          </div>
        </div>

        <div className="rounded-lg border border-[var(--gold)]/30 bg-[var(--gold)]/[0.05] p-5">
          <div className="flex items-baseline gap-3 mb-2">
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--gold)]">
              Caveat · alpha decay
            </span>
            <span className="text-xs text-[var(--text-tertiary)]">negative results retained</span>
          </div>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
            5/5 admission gate 通过, 但 ensemble
            <span className="text-[var(--text-primary)]"> 年度收益随时间单调衰减</span> —
            2018 年 SR +6.43 到 2024 年 SR -0.31.
            可能原因: 龙虎榜数据披露规则 2020+ 有调整 / 私募席位行为改变 / 北向资金主导流动性后席位净买入的信号强度稀释。
            这是为什么下一步必须 paper-trade 验证而不是直接推规模。
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-xs font-mono">
              <thead>
                <tr className="text-[10px] uppercase tracking-[0.12em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                  <th className="text-left py-2 font-normal">year</th>
                  {wf.year_by_year_ensemble.map((y) => (
                    <th key={y.year} className="text-right py-2 px-2 font-normal">
                      {y.year}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="text-[var(--text-secondary)]">
                <tr className="border-b border-[var(--border-soft)]">
                  <td className="py-2 text-[var(--text-primary)]">ret</td>
                  {wf.year_by_year_ensemble.map((y) => (
                    <td
                      key={y.year}
                      className="py-2 px-2 text-right"
                      style={{ color: y.ret_total >= 0.15 ? "var(--green)" : y.ret_total < 0 ? "var(--red)" : "var(--text-secondary)" }}
                    >
                      {fmtPct(y.ret_total, 0)}
                    </td>
                  ))}
                </tr>
                <tr className="border-b border-[var(--border-soft)]">
                  <td className="py-2 text-[var(--text-primary)]">SR</td>
                  {wf.year_by_year_ensemble.map((y) => (
                    <td
                      key={y.year}
                      className="py-2 px-2 text-right"
                      style={{ color: y.sharpe >= 0.8 ? "var(--green)" : y.sharpe < 0 ? "var(--red)" : "var(--text-secondary)" }}
                    >
                      {fmtNum(y.sharpe, 2)}
                    </td>
                  ))}
                </tr>
                <tr>
                  <td className="py-2 text-[var(--text-primary)]">MDD</td>
                  {wf.year_by_year_ensemble.map((y) => (
                    <td
                      key={y.year}
                      className="py-2 px-2 text-right"
                      style={{ color: y.mdd > -0.15 ? "var(--text-secondary)" : "var(--red)" }}
                    >
                      {fmtPct(y.mdd, 0)}
                    </td>
                  ))}
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
          两个 4/5 成分 · 失败模式互补
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <CandidateDeep
            slug="dsr30-bb"
            tag="DSR #30"
            title="BB-only 主板 rescaled"
            thesis="A 股版 Ikenberry 1995 — 上市公司自愿回购后 T+1 ~ T+20 drift. 主板过滤去掉小盘噪声, UNIT rescale 把 mean gross 提到 0.80."
            failMode="仅 CI_low 0.20 < 0.5 gate — 8 年样本对 Sharpe 稳定性估计不足"
            m={trials.dsr30}
          />
          <CandidateDeep
            slug="dsr33-lhb-decline"
            tag="DSR #33"
            title="LHB 跌幅 contrarian · 席位净买入"
            thesis="DeBondt-Thaler 1985 短期 reversion + informed-flow 筛选 — 股票日跌幅 7% 上榜（散户恐慌抛售）, 若 LHB 席位反而净买入, 是 institutional informed confidence signal. T+1 ~ T+5 捕捉 reversion."
            failMode="仅 MDD -55.9% 未过 — 统计置信极强 (CI_low 1.31) 但集中性尾风险未对冲"
            m={trials.dsr33}
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          DSR #32 / #34 · falsification 而非浪费
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          DSR #33 通过了 4/5, 但 "seat 净买入" 这个信号是不是只在跌幅场景 work?
          同一份 LHB 数据, 换 category 各跑一遍 —
          <span className="text-[var(--red)] font-semibold"> 0/5 两次</span>。
          这 falsification 反而加固 #33 假设: alpha 来自
          &ldquo;跌幅 × 席位净买入&rdquo; 的 conditional informed-flow,
          不是泛泛 seat 信号。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[...byStatus.falsified, byStatus.candidate.find((c) => c.id === 33)!]
            .filter(Boolean)
            .map((t) => (
              <FalsifyCard key={t.id} trial={t} />
            ))}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          完整 trial 表 · tabulated {trials.trials.length} / DSR n = {trials.n_trials_conservative}
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          按 n_pass 降序 — 除 2 个 4/5 候选外, 其余全部 ≤ 3/5。
          这份负结果表本身是重要产出: 说明
          <span className="text-[var(--text-primary)]"> 主板 long-only 单因子事件 alpha 普遍薄</span>
          , 优势只出现在 ensemble 层。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-3 py-3 font-normal w-14">#</th>
                <th className="text-left px-3 py-3 font-normal">假设</th>
                <th className="text-left px-3 py-3 font-normal">因子类</th>
                <th className="text-right px-3 py-3 font-normal">ann</th>
                <th className="text-right px-3 py-3 font-normal">Sharpe</th>
                <th className="text-right px-3 py-3 font-normal">MDD</th>
                <th className="text-right px-3 py-3 font-normal">PSR</th>
                <th className="text-right px-3 py-3 font-normal">CI_low</th>
                <th className="text-center px-3 py-3 font-normal">Gate</th>
              </tr>
            </thead>
            <tbody>
              {[...trials.trials]
                .sort((a, b) => b.n_pass - a.n_pass || b.sharpe - a.sharpe)
                .map((t) => (
                  <TrialRow key={t.id} t={t} />
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Takeaway
            title="Protocol: fixed rule + full trial accounting"
            body="每个 DSR trial 开工前写 pre-reg spec (数据源 / 信号 / 方向 / 窗口 / UNIT / gross cap 全固定), 跑完把结果钉到 journal, 不再修参。这意味着表里的 17 个 fail 不能藏。从 21 个 trial 里挑 best-Sharpe 再做 ensemble = 天然有选择偏差 — DSR penalty 负责 bookkeep。"
          />
          <Takeaway
            title="发现: gross-cap bug 修正"
            body="Phase 3 期间发现早期 Sharpe 偏高是因为 UNIT × 事件聚集期位置数 > gross cap 1.0 → 被悄悄放大杠杆。加入 apply_gross_cap 后, 原 3 真 alpha 两个退回 ~10% ann, 一个 Sharpe 从 0.91 降到 0.64。这条修正是 Phase 3.5 的核心产出, 也是为什么需要 UNIT rescale 重跑 (#30)。"
          />
          <Takeaway
            title="A 股 event-driven 的真相"
            body="单因子 long-only alpha 普遍薄 & 方差大, 8 年样本不足以穿过 CI_low 0.5 gate。但 DSR #30 + #33 的正交失败模式支撑了 ensemble 层 5/5 — 说明 A 股 alpha 不是不存在, 只是需要多因子组合 & 风险互补才稳。"
          />
          <Takeaway
            title="下一步 · paper-trade 现状 (2024 衰减已纳入预期)"
            body="5/5 admission gate (WF median SR 2.67 · regime 3/3 · cost 75bps 仍 +37% · win 54% · top5 6%) 支持 ensemble 进 paper-trade. 但实际 live 2026-04-17 起跑的是 DSR #30 BB-only 单腿 spec v3 (5% 初始规模), 不是 ensemble — LHB #33 腿尾部风险 (MDD -56%) 未对冲, 先保守. 纪律线: 若 forward 6mo live SR < 0.5, 立即降规模并回研究阶段补充数据源 (北向资金 / 分钟频席位追踪). 追求 live 曲线印证 WF 分布, 不追求规模."
          />
        </div>
        <div className="mt-6 text-xs text-[var(--text-tertiary)]">
          数据: <code className="font-mono">data/raw/events/_all_*.parquet</code> · 计算:
          <code className="font-mono"> research/event_driven/dsr3*_*.py</code> ·
          methodology: pre-reg spec + deflated Sharpe + bootstrap CI.
        </div>
      </section>
    </>
  );
}

function EnsembleMetricCard({
  tag,
  headline,
  subline,
  body,
  tone,
}: {
  tag: string;
  headline: string;
  subline: string;
  body: string;
  tone: "green" | "blue" | "gold";
}) {
  const color =
    tone === "green" ? "var(--green)" : tone === "blue" ? "var(--blue)" : "var(--gold)";
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] mb-1" style={{ color }}>
        {tag}
      </p>
      <p className="text-2xl font-mono font-semibold" style={{ color }}>
        {headline}
      </p>
      <p className="text-xs font-mono text-[var(--text-tertiary)] mb-2">{subline}</p>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}

function CandidateDeep({
  slug,
  tag,
  title,
  thesis,
  failMode,
  m,
}: {
  slug: string;
  tag: string;
  title: string;
  thesis: string;
  failMode: string;
  m: CandidateBlock;
}) {
  return (
    <article className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--gold)]">
          {tag} · 4/5
        </span>
      </div>
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-4">{thesis}</p>
      <MetricGrid
        metrics={[
          { label: "年化", value: fmtPct(m.ann_return, 1), tone: m.gates.ann_ge_15pct ? "good" : "warn" },
          { label: "Sharpe", value: fmtNum(m.sharpe, 2), tone: m.gates.sharpe_ge_08 ? "good" : "warn" },
          { label: "Max DD", value: fmtPct(m.max_drawdown, 1), tone: m.gates.mdd_gt_neg30pct ? "good" : "bad" },
          { label: "CI_low", value: fmtNum(m.sharpe_ci_low, 2), tone: m.gates.ci_low_ge_05 ? "good" : "bad" },
        ]}
      />
      <div className="mt-3 rounded-md border border-[var(--red)]/20 bg-[var(--red)]/[0.04] p-3">
        <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--red)] mb-1">
          唯一 fail gate
        </p>
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{failMode}</p>
      </div>
    </article>
  );
}

function FalsifyCard({ trial }: { trial: Trial }) {
  const isPass = trial.status === "candidate";
  const color = isPass ? "var(--green)" : "var(--red)";
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: `color-mix(in srgb, ${color} 25%, transparent)`,
        background: `color-mix(in srgb, ${color} 4%, transparent)`,
      }}
    >
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] mb-1" style={{ color }}>
        DSR #{trial.id} · {isPass ? "4/5 PASS" : "0/5 FAIL"}
      </p>
      <p className="text-sm font-semibold text-[var(--text-primary)] mb-2">{trial.name}</p>
      <div className="text-xs font-mono text-[var(--text-secondary)] space-y-0.5">
        <p>ann: {fmtPct(trial.ann, 1)}</p>
        <p>Sharpe: {fmtNum(trial.sharpe, 2)}</p>
        <p>MDD: {fmtPct(trial.mdd, 1)}</p>
      </div>
    </div>
  );
}

function TrialRow({ t }: { t: Trial }) {
  const rowBg =
    t.status === "candidate"
      ? "bg-[var(--gold)]/[0.06]"
      : t.status === "falsified"
      ? "bg-[var(--red)]/[0.04]"
      : "";
  return (
    <tr className={`border-b border-[var(--border-soft)] last:border-b-0 ${rowBg}`}>
      <td className="px-3 py-2.5 font-mono text-[var(--text-tertiary)]">#{t.id}</td>
      <td className="px-3 py-2.5 text-[var(--text-primary)]">
        <span className="text-sm">{t.name}</span>
      </td>
      <td className="px-3 py-2.5">
        <span className="text-[10px] font-mono uppercase text-[var(--text-tertiary)]">
          {t.factor}
        </span>
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.ann >= 0.15 ? "var(--green)" : t.ann < 0 ? "var(--red)" : "var(--text-secondary)" }}
      >
        {fmtPct(t.ann, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.sharpe >= 0.8 ? "var(--green)" : t.sharpe < 0 ? "var(--red)" : "var(--text-secondary)" }}
      >
        {fmtNum(t.sharpe, 2)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.mdd > -0.3 ? "var(--green)" : "var(--red)" }}
      >
        {fmtPct(t.mdd, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono text-xs"
        style={{ color: t.psr >= 0.95 ? "var(--green)" : "var(--text-secondary)" }}
      >
        {fmtPct(t.psr, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono text-xs"
        style={{ color: t.ci_low >= 0.5 ? "var(--green)" : "var(--text-secondary)" }}
      >
        {fmtNum(t.ci_low, 2)}
      </td>
      <td className="px-3 py-2.5 text-center font-mono text-xs">
        <span
          style={{
            color:
              t.n_pass === 4 ? "var(--gold)" : t.n_pass === 5 ? "var(--green)" : t.n_pass === 0 ? "var(--red)" : "var(--text-secondary)",
          }}
        >
          {t.n_pass}/5
        </span>
      </td>
    </tr>
  );
}

function Takeaway({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}
