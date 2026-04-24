import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import { projectWeek } from "@/lib/constants";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
  StatusPill,
  TextLink,
} from "@/components/layout/Primitives";
import type { LiveDashboard, LiveRunSummary, PaperTradeState } from "@/lib/types";

export const metadata = {
  title: "Paper-Trade · Live · QuantDojo",
  description: "Current paper-trade state, risk action, positions, and run audit.",
};

export default async function LivePage() {
  const [dashboard, state] = await Promise.all([
    readData<LiveDashboard>("live/dashboard.json"),
    readDataOrNull<PaperTradeState>("paper_trade/state.json"),
  ]);

  const { week, dateStr } = projectWeek();

  return (
    <>
      <PageHeader
        eyebrow={`Week ${week} · ${dateStr}`}
        title="Paper-trade state"
        subtitle={
          state
            ? `${state.strategy_id ?? "paper-trade"} · spec ${state.spec_version} · Day ${state.kill.running_days}`
            : "No EOD snapshot exported"
        }
        description="This page is operational state only. Research candidates and rejected specs stay below the fold unless opened."
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />

      {state ? <StateOverview state={state} /> : <EmptyState />}

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow="Details"
          title="Open the audit trail"
          body="The default view stays compact. Expand rows for trades, positions, risk messages, and research context."
        />
        {state && (
          <div className="space-y-3">
            <DisclosurePanel
              tone={state.kill.action === "ok" ? "green" : "gold"}
              title="Risk action and kill-switch inputs"
              summary={`Action ${state.kill.action.toUpperCase()} · DD ${fmtPct(state.kill.cum_drawdown, 2)} · monthly MDD ${fmtPct(state.kill.monthly_mdd, 2)}`}
            >
              <MetricGrid
                metrics={[
                  { label: "30d SR", value: fmtNum(state.kill.rolling_sr_30d, 2) },
                  { label: "Live Sharpe", value: fmtNum(state.kill.live_sharpe, 2) },
                  { label: "Scale", value: `× ${state.kill.position_scale.toFixed(1)}` },
                  { label: "Warnings", value: String(state.kill.warnings.length) },
                ]}
              />
              {(state.kill.reasons.length > 0 || state.kill.warnings.length > 0) && (
                <ul className="mt-4 space-y-1 text-xs text-[var(--text-secondary)]">
                  {[...state.kill.reasons, ...state.kill.warnings].map((w, i) => (
                    <li key={i}>· {w}</li>
                  ))}
                </ul>
              )}
            </DisclosurePanel>

            <DisclosurePanel
              tone="blue"
              title="Positions and entries"
              summary={`${state.positions.length} holdings · ${state.open_entries_count} open entries`}
            >
              {state.positions.length === 0 ? (
                <p>No active positions.</p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
                  <table className="w-full text-sm">
                    <thead className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                      <tr className="border-b border-[var(--border-soft)]">
                        <th className="px-4 py-3 text-left font-normal">Symbol</th>
                        <th className="px-4 py-3 text-right font-normal">Shares</th>
                        <th className="px-4 py-3 text-right font-normal">Cost</th>
                        <th className="px-4 py-3 text-right font-normal">Current</th>
                        <th className="px-4 py-3 text-right font-normal">PnL</th>
                      </tr>
                    </thead>
                    <tbody className="font-mono">
                      {state.positions.map((p) => (
                        <tr key={p.symbol} className="border-b border-[var(--border-soft)] last:border-b-0">
                          <td className="px-4 py-3 text-[var(--text-primary)]">{p.symbol}</td>
                          <td className="px-4 py-3 text-right text-[var(--text-secondary)]">{p.shares}</td>
                          <td className="px-4 py-3 text-right text-[var(--text-secondary)]">{fmtNum(p.cost_price, 2)}</td>
                          <td className="px-4 py-3 text-right text-[var(--text-secondary)]">{fmtNum(p.current_price, 2)}</td>
                          <td
                            className="px-4 py-3 text-right"
                            style={{ color: p.pnl_pct >= 0 ? "var(--green)" : "var(--red)" }}
                          >
                            {fmtPct(p.pnl_pct, 2)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </DisclosurePanel>

            <DisclosurePanel
              tone="neutral"
              title="Daily orders"
              summary={`${state.daily_summary.n_buys} buys · ${state.daily_summary.n_sells} sells · turnover ${fmtPct(state.daily_summary.turnover, 2)}`}
            >
              {state.today_trades.length === 0 ? (
                <p>No trades in the exported day.</p>
              ) : (
                <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                  {state.today_trades.map((t, i) => (
                    <div key={`${t.symbol}-${i}`} className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/35 p-3 text-xs font-mono">
                      <span className={t.action === "buy" ? "text-[var(--green)]" : "text-[var(--red)]"}>
                        {t.action.toUpperCase()}
                      </span>
                      <span className="ml-3 text-[var(--text-primary)]">{t.symbol}</span>
                      <span className="ml-3 text-[var(--text-tertiary)]">
                        {t.shares} @ {fmtNum(t.price, 2)}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </DisclosurePanel>
          </div>
        )}
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel eyebrow="Context" title="Research context is separate" />
        <div className="space-y-3">
          <DisclosurePanel
            tone="red"
            title="Why the RIAD combo is not marked as running"
            summary="The executable RIAD version did not preserve the baseline result."
          >
            <p>
              The combo spec is kept as a validation case, not as current live
              state. The paper-trade state on this page remains BB-only until a
              new executable leg passes the gates.
            </p>
            <div className="mt-3">
              <TextLink href="/validation">Open validation case</TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="blue"
            title={`Multi-factor research face: ${dashboard.production_face}`}
            summary="Research benchmark only. It is not the current paper-trade strategy."
          >
            <p>{dashboard.note}</p>
            <div className="mt-3 flex flex-wrap gap-3">
              <TextLink href={`/strategy#${dashboard.production_face}`}>Open strategy card</TextLink>
              <TextLink href="/strategy/candidates">Open candidate pool</TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <SectionLabel
          eyebrow="Recent runs"
          title="Backtests remain auditable"
          body="These are research-side runs, not live trading activity."
        />
        <div className="overflow-x-auto rounded-xl border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-soft)] text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                <th className="px-4 py-3 text-left font-normal">Version</th>
                <th className="px-4 py-3 text-left font-normal">Created</th>
                <th className="px-4 py-3 text-right font-normal">Annual</th>
                <th className="px-4 py-3 text-right font-normal">Sharpe</th>
                <th className="px-4 py-3 text-right font-normal">MaxDD</th>
              </tr>
            </thead>
            <tbody>
              {dashboard.recent_runs.slice(0, 8).map((r) => (
                <RunRow key={r.run_id} run={r} />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function StateOverview({ state }: { state: PaperTradeState }) {
  const riskTone =
    state.kill.action === "ok"
      ? "green"
      : state.kill.action === "halt"
        ? "red"
        : "gold";

  return (
    <section className="max-w-content mx-auto px-6 pb-14">
      <div className="mb-4 flex flex-wrap gap-2">
        <StatusPill tone={state.enabled ? "green" : "gold"}>
          {state.enabled ? "enabled" : "disabled"}
        </StatusPill>
        <StatusPill tone={riskTone}>{state.kill.action}</StatusPill>
        <StatusPill tone="neutral">last day {state.last_trading_day}</StatusPill>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <EvidenceCard
          tone="green"
          label="NAV"
          value={fmtNum(state.last_nav, 0)}
          detail={`initial ${fmtNum(state.initial_capital, 0)}`}
        />
        <EvidenceCard
          tone={state.cum_return >= 0 ? "green" : "red"}
          label="Cumulative"
          value={fmtPct(state.cum_return, 2)}
          detail={`today ${(state.pnl_today >= 0 ? "+" : "") + fmtNum(state.pnl_today, 0)}`}
        />
        <EvidenceCard
          tone="blue"
          label="Exposure"
          value={fmtPct(state.daily_summary.gross_weight, 1)}
          detail={`${state.positions.length} positions · ${state.open_entries_count} entries`}
        />
        <EvidenceCard
          tone={riskTone}
          label="Risk"
          value={state.kill.action.toUpperCase()}
          detail={`position scale ×${state.kill.position_scale.toFixed(1)}`}
        />
      </div>
      <div className="mt-4">
        <Link
          href="/live/paper-trade"
          className="text-xs font-mono text-[var(--blue)] hover:underline"
        >
          Open full paper-trade archive →
        </Link>
      </div>
    </section>
  );
}

function EmptyState() {
  return (
    <section className="max-w-content mx-auto px-6 pb-14">
      <div className="rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 p-5">
        <p className="text-sm text-[var(--text-secondary)]">
          <code className="font-mono text-xs text-[var(--text-primary)]">
            paper_trade/state.json
          </code>{" "}
          was not exported. Run the portfolio data export after the next EOD snapshot.
        </p>
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
      <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
        {fmtPct(run.annualized_return, 1)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
        {fmtNum(run.sharpe, 3)}
      </td>
      <td className="px-4 py-3 text-right font-mono text-[var(--text-secondary)]">
        {fmtPct(run.max_drawdown, 1)}
      </td>
    </tr>
  );
}
