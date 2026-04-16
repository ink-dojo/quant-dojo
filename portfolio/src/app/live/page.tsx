import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  LiveDashboard,
  LiveRunSummary,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function LivePage() {
  const [dashboard, versionsFile, v16Curve] = await Promise.all([
    readData<LiveDashboard>("live/dashboard.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
    readDataOrNull<EquityCurveFile>("strategy/equity_v16.json"),
  ]);

  const active = versionsFile.versions.find(
    (v) => v.id === dashboard.active_strategy
  );
  const activeMetrics = active?.metrics;

  return (
    <>
      <PageHeader
        eyebrow="Live · 实盘"
        title="Paper Trading Operations"
        subtitle={`${dashboard.active_strategy ?? "—"} · state updated ${dashboard.state_updated_at?.slice(0, 10) ?? "—"}`}
        description="当前生产策略的实盘运作记录 — signal / snapshot 生成节奏、recent run 历史、equity curve。本站不展示 real money 持仓，只展示 paper trading 的可复现 audit trail。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />

      {active && (
        <section className="max-w-content mx-auto px-6 pb-10">
          <div className="rounded-lg border border-[var(--green)]/40 bg-[var(--green)]/[0.05] p-5">
            <div className="flex flex-wrap items-center gap-3 mb-3">
              <span className="inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--green)]">
                <span className="w-2 h-2 rounded-full bg-[var(--green)] animate-pulse" />
                Live Active
              </span>
              <span className="text-sm font-semibold text-[var(--text-primary)]">
                {active.id} · {active.name_en}
              </span>
              <span className="text-xs font-mono text-[var(--text-tertiary)]">
                {active.factors.length} factors
              </span>
            </div>
            {dashboard.active_note && (
              <p className="text-xs font-mono text-[var(--text-secondary)] break-all leading-relaxed">
                {dashboard.active_note}
              </p>
            )}
            {activeMetrics && (
              <div className="mt-4 pt-4 border-t border-[var(--green)]/20">
                <MetricGrid
                  metrics={[
                    {
                      label: "Annual Return",
                      value: fmtPct(activeMetrics.annualized_return, 2),
                      tone: "good",
                    },
                    {
                      label: "Sharpe",
                      value: fmtNum(activeMetrics.sharpe, 3),
                      tone: "good",
                    },
                    {
                      label: "Max Drawdown",
                      value: fmtPct(activeMetrics.max_drawdown, 1),
                      tone: "warn",
                    },
                    {
                      label: "Win Rate",
                      value: fmtPct(activeMetrics.win_rate, 1),
                      tone: "neutral",
                    },
                  ]}
                />
              </div>
            )}
          </div>
        </section>
      )}

      {v16Curve && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Equity Curve — v16 since 2022
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            Paper trading equity curve，{v16Curve.points.length} 个交易日。2025 年
            OOS 段仍保持向上 — 是 v10 没能做到的。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart
              series={[
                {
                  id: "v16",
                  label: "v16 · 生产",
                  color: "var(--green)",
                  curve: v16Curve,
                },
              ]}
              height={360}
              stride={3}
            />
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PipelinePanel
          title="Signal Cadence · 最近 signal"
          subtitle="每日收盘后：因子快照 → 组合权重计算 → signals/{date}.json"
          dates={dashboard.signal_dates}
          emptyMsg="暂无 signal 文件"
        />
        <PipelinePanel
          title="Factor Snapshot · 最近快照"
          subtitle="每日收盘后的因子值副本（可重放）"
          dates={dashboard.snapshot_dates}
          emptyMsg="快照文件暂未归档到 portfolio 可读路径"
        />
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Recent Runs — 最近 {dashboard.recent_runs.length} 次 backtest
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4">
          因子挖掘迭代历史 — v10-v21 是一轮完整的搜索循环，最终 v16 胜出并上 live。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Version</th>
                <th className="text-left px-4 py-3 font-normal">Run ID</th>
                <th className="text-left px-4 py-3 font-normal">Created</th>
                <th className="text-right px-4 py-3 font-normal">Annual</th>
                <th className="text-right px-4 py-3 font-normal">Sharpe</th>
                <th className="text-right px-4 py-3 font-normal">MaxDD</th>
                <th className="text-left px-4 py-3 font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.recent_runs.map((r) => (
                <RunRow
                  key={r.run_id}
                  run={r}
                  isActive={r.strategy_id === `multi_factor_${active?.id}`}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function PipelinePanel({
  title,
  subtitle,
  dates,
  emptyMsg,
}: {
  title: string;
  subtitle: string;
  dates: string[];
  emptyMsg: string;
}) {
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
      <h3 className="text-sm font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-1">
        {title}
      </h3>
      <p className="text-xs text-[var(--text-secondary)] mb-4 leading-relaxed">
        {subtitle}
      </p>
      {dates.length === 0 ? (
        <p className="text-xs font-mono text-[var(--text-tertiary)] italic">
          {emptyMsg}
        </p>
      ) : (
        <ul className="space-y-1.5 font-mono text-xs">
          {dates.map((d, i) => (
            <li
              key={d}
              className="flex items-center gap-2 text-[var(--text-secondary)]"
            >
              <span
                className="inline-block w-1.5 h-1.5 rounded-full"
                style={{
                  background:
                    i === 0 ? "var(--green)" : "var(--text-tertiary)",
                }}
              />
              <span>{d}</span>
              {i === 0 && (
                <span className="text-[10px] text-[var(--green)] uppercase tracking-[0.15em]">
                  latest
                </span>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function RunRow({
  run,
  isActive,
}: {
  run: LiveRunSummary;
  isActive: boolean;
}) {
  const version = run.strategy_id?.replace(/^multi_factor_/, "") ?? "?";
  return (
    <tr
      className={`border-b border-[var(--border-soft)] last:border-b-0 ${
        isActive ? "bg-[var(--green)]/[0.05]" : ""
      }`}
    >
      <td className="px-4 py-3 font-mono font-semibold text-[var(--text-primary)]">
        {version}
        {isActive && (
          <span className="ml-2 text-[10px] text-[var(--green)] uppercase tracking-[0.15em]">
            live
          </span>
        )}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-[var(--text-tertiary)] truncate max-w-[240px]">
        {run.run_id}
      </td>
      <td className="px-4 py-3 font-mono text-xs text-[var(--text-tertiary)]">
        {run.created_at?.slice(0, 10)}
      </td>
      <td
        className="px-4 py-3 text-right font-mono"
        style={{
          color:
            (run.annualized_return ?? 0) >= 0.2
              ? "var(--green)"
              : (run.annualized_return ?? 0) >= 0.1
              ? "var(--gold)"
              : "var(--text-secondary)",
        }}
      >
        {fmtPct(run.annualized_return, 1)}
      </td>
      <td
        className="px-4 py-3 text-right font-mono"
        style={{
          color:
            (run.sharpe ?? 0) >= 0.7
              ? "var(--green)"
              : (run.sharpe ?? 0) >= 0.5
              ? "var(--gold)"
              : "var(--text-secondary)",
        }}
      >
        {fmtNum(run.sharpe, 3)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
        {fmtPct(run.max_drawdown, 1)}
      </td>
      <td className="px-4 py-3 text-xs font-mono">
        <span
          style={{
            color:
              run.status === "success" ? "var(--green)" : "var(--red)",
          }}
        >
          {run.status}
        </span>
      </td>
    </tr>
  );
}
