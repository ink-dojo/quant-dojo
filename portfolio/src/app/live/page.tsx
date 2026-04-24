import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import { SITE, projectWeek } from "@/lib/constants";
import type {
  LiveDashboard,
  LiveRunSummary,
  PaperTradeState,
} from "@/lib/types";

export const metadata = {
  title: "Paper-Trade · Live · QuantDojo",
  description:
    "Week 6 paper-trade status (DSR #30 BB-only, spec v3) + research-side backtest activity. 5% 模拟资金, 不是真钱.",
};

export default async function LivePage() {
  const [dashboard, ptState] = await Promise.all([
    readData<LiveDashboard>("live/dashboard.json"),
    readDataOrNull<PaperTradeState>("paper_trade/state.json"),
  ]);

  const { week, dateStr } = projectWeek();

  return (
    <>
      <PageHeader
        eyebrow={`Week ${week} · ${dateStr}`}
        title="Paper-Trade · 模拟盘"
        subtitle={
          ptState
            ? `${ptState.strategy_id ?? "—"} · spec ${ptState.spec_version} · Day ${ptState.kill.running_days}`
            : "等待第一次 EOD 跑"
        }
        description="这里展示的是当前正在跑的 paper-trade 状态 — 5% 模拟资金, 不是真钱. 实盘代码从 2026-04-17 (Week 6 Day 1) 开始每日 EOD 生成 signal → 下单 → 风控 → 归档. 上面的研究页是这一次 paper-trade 背后的推理过程."
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />

      {ptState ? (
        <LiveSnapshot state={ptState} />
      ) : (
        <EmptyLiveState />
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/30 p-5">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
            Why BB-only, not the RIAD combo
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-3">
            Week 6 写了 spec v4 (RIAD + DSR#30 BB-only 50/50 合成), backtest 显示 SR 1.87 · DSR 0.920.
            但 filtered universe (真实融券约束) 下 RIAD OOS 2025 Sharpe −0.59,
            walk-forward 最近一折 −1.56. 合成的 4/5 gate 是在 baseline (不可执行) 版本上过的.
            否决 v4, 先上 v3 BB-only 单腿 — 证据更硬 (8-yr 4/5), 6 个月后再评估是否加 RIAD leg.
          </p>
          <div className="flex flex-wrap gap-x-5 gap-y-1.5 text-xs font-mono text-[var(--text-tertiary)]">
            <span>spec: paper_trade_spec_v3_bb_only_20260422.md</span>
            <span>v4 否决: paper_trade_spec_v4_riad_dsr30_combo_20260422.md</span>
          </div>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="flex items-baseline justify-between gap-3 mb-2">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Production face (research) · {dashboard.production_face}
          </h2>
          <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
            multi-factor — 未进 live
          </span>
        </div>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-3xl mb-4">
          {dashboard.note ?? ""}
        </p>
        <div className="flex flex-wrap gap-2 text-xs font-mono">
          <Link
            href={`/strategy#${dashboard.production_face}`}
            className="px-3 py-1.5 rounded border border-[var(--green)]/35 bg-[var(--green)]/[0.05] text-[var(--green)] hover:bg-[var(--green)]/[0.1] transition-colors"
          >
            {dashboard.production_face} 详情 →
          </Link>
          <Link
            href={`/strategy#${dashboard.candidate}`}
            className="px-3 py-1.5 rounded border border-[var(--gold)]/35 bg-[var(--gold)]/[0.05] text-[var(--gold)] hover:bg-[var(--gold)]/[0.1] transition-colors"
          >
            候选 {dashboard.candidate} →
          </Link>
          <Link
            href="/validation"
            className="px-3 py-1.5 rounded border border-[var(--red)]/35 bg-[var(--red)]/[0.05] text-[var(--red)] hover:bg-[var(--red)]/[0.1] transition-colors"
          >
            为什么不 promote 到 live →
          </Link>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Research · Recent backtest runs
        </h2>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed max-w-3xl mb-4">
          {SITE.title} 的每次回测都通过统一 runner 落库, 方便事后审计选择偏差.
          v11-v21 是 Week 5 因子挖掘 session 的一次性搜索, 并非 live 活动 —
          从中挑 sharpe 最高的 v16 作 candidate, 但同期还在
          {" "}<Link href="/validation" className="text-[var(--red)] hover:underline">
            过 walk-forward / admission gate
          </Link>.
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Version</th>
                <th className="text-left px-4 py-3 font-normal">Created</th>
                <th className="text-right px-4 py-3 font-normal">Annual</th>
                <th className="text-right px-4 py-3 font-normal">Sharpe</th>
                <th className="text-right px-4 py-3 font-normal">MaxDD</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.recent_runs.slice(0, 10).map((r) => (
                <RunRow key={r.run_id} run={r} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function EmptyLiveState() {
  return (
    <section className="max-w-content mx-auto px-6 pb-16">
      <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-6">
        <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          No state snapshot
        </p>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          <code className="font-mono text-xs text-[var(--text-primary)]">
            paper_trade/state.json
          </code>{" "}
          不存在 — 可能 EOD cron 还没跑完, 或 portfolio/scripts/export_data.py 尚未同步.
        </p>
      </div>
    </section>
  );
}

function LiveSnapshot({ state }: { state: PaperTradeState }) {
  const killTone: "good" | "warn" | "bad" | "neutral" =
    state.kill.action === "halt"
      ? "bad"
      : state.kill.action === "warn" ||
          state.kill.action === "halve" ||
          state.kill.action === "cool_off" ||
          state.kill.action === "do_not_upgrade"
        ? "warn"
        : state.kill.action === "ok"
          ? "good"
          : "neutral";

  const cumTone: "good" | "bad" | "neutral" =
    state.cum_return > 0 ? "good" : state.cum_return < 0 ? "bad" : "neutral";
  const pnlTone: "good" | "bad" | "neutral" =
    state.pnl_today > 0 ? "good" : state.pnl_today < 0 ? "bad" : "neutral";

  return (
    <section className="max-w-content mx-auto px-6 pb-12">
      <div className="rounded-lg border border-[var(--green)]/30 bg-[var(--green)]/[0.04] p-5 mb-6">
        <div className="flex flex-wrap items-baseline gap-3 mb-4">
          <span className="inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--green)]">
            <span
              className={`w-2 h-2 rounded-full bg-[var(--green)] ${state.enabled ? "animate-pulse" : ""}`}
            />
            {state.enabled ? "Live · paper" : "Disabled"}
          </span>
          <span className="text-sm font-semibold text-[var(--text-primary)]">
            {state.strategy_id ?? "paper-trade"}
          </span>
          <span className="text-xs font-mono text-[var(--text-tertiary)]">
            Day {state.kill.running_days} · started {state.started_at ?? "—"}
          </span>
          <Link
            href="/live/paper-trade"
            className="ml-auto text-xs font-mono text-[var(--blue)] hover:underline"
          >
            完整 paper-trade 页 →
          </Link>
        </div>

        <MetricGrid
          metrics={[
            {
              label: "NAV",
              value: fmtNum(state.last_nav, 0),
              hint: `init ${fmtNum(state.initial_capital, 0)}`,
            },
            {
              label: "Cum Return",
              value: fmtPct(state.cum_return),
              tone: cumTone,
            },
            {
              label: "PnL Today",
              value:
                (state.pnl_today >= 0 ? "+" : "") +
                fmtNum(state.pnl_today, 0),
              tone: pnlTone,
            },
            {
              label: "Positions",
              value: String(state.positions.length),
              hint: `${state.open_entries_count} entries`,
            },
            {
              label: "Gross",
              value: fmtPct(state.daily_summary.gross_weight, 1),
            },
            {
              label: "Risk",
              value: state.kill.action.toUpperCase(),
              tone: killTone,
              hint: `× ${state.kill.position_scale.toFixed(1)}`,
            },
          ]}
        />

        {state.kill.warnings.length > 0 && (
          <div className="mt-4 text-[11px] font-mono text-[var(--gold)]">
            warnings: {state.kill.warnings.join(" · ")}
          </div>
        )}
      </div>
    </section>
  );
}

function RunRow({ run }: { run: LiveRunSummary }) {
  const version = run.strategy_id?.replace(/^multi_factor_/, "") ?? "?";
  return (
    <tr className="border-b border-[var(--border-soft)] last:border-b-0">
      <td className="px-4 py-3 font-mono font-semibold text-[var(--text-primary)]">
        {version}
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
    </tr>
  );
}
