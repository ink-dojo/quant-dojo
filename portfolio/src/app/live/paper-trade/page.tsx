import { PageHeader } from "@/components/layout/PageHeader";
import { Lang } from "@/components/layout/LanguageText";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { readDataOrNull } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import { projectWeek } from "@/lib/constants";
import type { PaperTradeState } from "@/lib/types";
import { NavCurve } from "./NavCurve";

// spec v3 允许的 phase / kill 显示 — 本地映射, 不依赖外部.
const KILL_TONE: Record<string, "good" | "bad" | "warn" | "neutral"> = {
  ok: "good",
  warn: "warn",
  halve: "warn",
  cool_off: "warn",
  do_not_upgrade: "warn",
  halt: "bad",
};

const PHASE_LABEL: Record<string, string> = {
  pre_live: "Pre-Live",
  live_phase1: "Phase 1 (5%)",
  live_phase2: "Phase 2 (15%)",
  live_phase3: "Phase 3 (50%)",
};

export default async function PaperTradePage() {
  const state = await readDataOrNull<PaperTradeState>(
    "paper_trade/state.json",
  );

  if (!state) {
    return (
      <>
        <PageHeader
          eyebrow="Live · paper"
          title="DSR #30 BB-only Paper Trade"
          subtitle={<Lang zh="等待第一次 EOD 跑" en="Waiting for the first EOD run" />}
          description={
            <Lang
              zh="还没有 state snapshot：paper_trade/state.json 不存在。运行 scripts/paper_trade_daily.py 之后这里会填满。"
              en="No state snapshot yet: paper_trade/state.json does not exist. This page will populate after scripts/paper_trade_daily.py runs."
            />
          }
          crumbs={[
            { label: "Home", href: "/" },
            { label: "Live", href: "/live" },
            { label: "Paper Trade" },
          ]}
        />
      </>
    );
  }

  const kill = state.kill;
  const killTone = KILL_TONE[kill.action] ?? "neutral";
  const phaseLabel = PHASE_LABEL[state.phase ?? ""] ?? state.phase ?? "—";
  const { week, dateStr } = projectWeek();

  const pnlToneValue = state.pnl_today;
  const pnlTone: "good" | "bad" | "neutral" =
    pnlToneValue > 0 ? "good" : pnlToneValue < 0 ? "bad" : "neutral";

  const cumTone: "good" | "bad" | "neutral" =
    state.cum_return > 0 ? "good" : state.cum_return < 0 ? "bad" : "neutral";

  return (
    <>
      <PageHeader
        eyebrow={`Week ${week} · ${dateStr} · spec ${state.spec_version.toUpperCase()} · Day ${kill.running_days}`}
        title={<Lang zh="DSR #30 BB-only · 模拟盘" en="DSR #30 BB-only · Paper trade" />}
        subtitle={
          <Lang
            zh={`${phaseLabel} · 开始 ${state.started_at ?? "—"} · 最近运行 ${state.last_run_ts.slice(0, 10)}`}
            en={`${phaseLabel} · started ${state.started_at ?? "—"} · last run ${state.last_run_ts.slice(0, 10)}`}
          />
        }
        description={
          <Lang
            zh="DSR #30 主板 rescaled BB-only (spec v3)。每个交易日 EOD 生成信号、下单、风控、产出报告。本页直接读取 paper_trade/state.json，不额外加工。"
            en="DSR #30 main-board rescaled BB-only (spec v3). Each trading day runs EOD signal generation, orders, risk checks, and reporting. This page reads paper_trade/state.json directly."
          />
        }
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Live", href: "/live" },
          { label: "Paper Trade" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5 mb-6">
          <div className="flex flex-wrap items-center gap-3 mb-4">
            <span
              className={`inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.2em] ${
                state.enabled ? "text-[var(--green)]" : "text-[var(--text-tertiary)]"
              }`}
            >
              <span
                className={`w-2 h-2 rounded-full ${
                  state.enabled
                    ? "bg-[var(--green)] animate-pulse"
                    : "bg-[var(--text-tertiary)]"
                }`}
              />
              {state.enabled ? <Lang zh="模拟盘运行中" en="Paper running" /> : <Lang zh="已关闭" en="Disabled" />}
            </span>
            <span className="text-sm font-semibold text-[var(--text-primary)]">
              {state.strategy_id ?? "paper-trade"}
            </span>
            <span className="text-xs font-mono text-[var(--text-tertiary)]">
              <Lang zh={`运行第 ${kill.running_days} 天`} en={`running day ${kill.running_days}`} />
            </span>
          </div>

          <MetricGrid
            metrics={[
              {
                label: <Lang zh="最新 NAV" en="Last NAV" />,
                value: fmtNum(state.last_nav, 0),
                hint: <Lang zh={`初始 ${fmtNum(state.initial_capital, 0)}`} en={`init ${fmtNum(state.initial_capital, 0)}`} />,
              },
              {
                label: <Lang zh="累计收益" en="Cum Return" />,
                value: fmtPct(state.cum_return),
                tone: cumTone,
              },
              {
                label: <Lang zh="今日盈亏" en="PnL Today" />,
                value:
                  (state.pnl_today >= 0 ? "+" : "") +
                  fmtNum(state.pnl_today, 0),
                tone: pnlTone,
              },
              {
                label: <Lang zh="总权重" en="Gross Weight" />,
                value: fmtPct(state.daily_summary.gross_weight, 1),
                hint: <Lang zh={`现金 ${fmtNum(state.daily_summary.cash_after, 0)}`} en={`cash ${fmtNum(state.daily_summary.cash_after, 0)}`} />,
              },
              {
                label: <Lang zh="持仓数" en="Positions" />,
                value: String(state.positions.length),
                hint: <Lang zh={`${state.open_entries_count} 个 entry 未平`} en={`${state.open_entries_count} entries open`} />,
              },
              {
                label: <Lang zh="今日换手" en="Turnover Today" />,
                value: fmtPct(state.daily_summary.turnover),
              },
              {
                label: <Lang zh="30日滚动 SR" en="30d Rolling SR" />,
                value:
                  kill.rolling_sr_30d == null
                    ? "n/a"
                    : fmtNum(kill.rolling_sr_30d, 2),
              },
              {
                label: <Lang zh="风控" en="Risk" />,
                value: kill.action.toUpperCase(),
                tone: killTone,
                hint: <Lang zh={`仓位倍数 × ${kill.position_scale.toFixed(1)}`} en={`scale × ${kill.position_scale.toFixed(1)}`} />,
              },
            ]}
          />
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5 mb-6">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
            <Lang zh="NAV 曲线 · 自索引" en="NAV curve · self-indexed" />
          </h2>
          <NavCurve points={state.nav_series} initial={state.initial_capital} />
          <p className="text-[11px] font-mono text-[var(--text-tertiary)] mt-3">
            <Lang
              zh={`${state.nav_series.length} 天 · 从 ${state.started_at} 起 · 初始本金 ${fmtNum(state.initial_capital, 0)}`}
              en={`${state.nav_series.length} days · since ${state.started_at} · initial capital ${fmtNum(state.initial_capital, 0)}`}
            />
          </p>
        </div>

        {(kill.reasons.length > 0 || kill.warnings.length > 0) && (
          <div
            className={`rounded-lg border p-5 mb-6 ${
              killTone === "bad"
                ? "border-[var(--red)]/50 bg-[var(--red)]/[0.05]"
                : killTone === "warn"
                  ? "border-[var(--gold)]/50 bg-[var(--gold)]/[0.05]"
                  : "border-[var(--border)] bg-[var(--surface-1)]"
            }`}
          >
            <h2 className="text-sm font-mono uppercase tracking-[0.2em] mb-3 text-[var(--text-tertiary)]">
              <Lang zh="风控状态" en="Risk status" /> · {kill.action.toUpperCase()}
            </h2>
            {kill.reasons.length > 0 && (
              <div className="mb-3">
                <div className="text-[11px] font-mono uppercase text-[var(--text-tertiary)] mb-1">
                  <Lang zh="原因" en="Reasons" />
                </div>
                <ul className="text-xs font-mono text-[var(--text-primary)] space-y-1">
                  {kill.reasons.map((r, i) => (
                    <li key={i}>· {r}</li>
                  ))}
                </ul>
              </div>
            )}
            {kill.warnings.length > 0 && (
              <div>
                <div className="text-[11px] font-mono uppercase text-[var(--text-tertiary)] mb-1">
                  <Lang zh="软警告" en="Soft warnings" />
                </div>
                <ul className="text-xs font-mono text-[var(--text-secondary)] space-y-1">
                  {kill.warnings.map((w, i) => (
                    <li key={i}>· {w}</li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}

        <div className="grid grid-cols-1 lg:grid-cols-2 gap-6 mb-6">
          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5">
            <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
              <Lang zh="今日交易" en="Today's trades" /> · {state.today_trades.length}
            </h2>
            {state.today_trades.length === 0 ? (
              <p className="text-xs font-mono text-[var(--text-tertiary)]">
                <Lang
                  zh={`无交易：BB 腿在 ${state.last_trading_day} 前一交易日无合格信号`}
                  en={`No trades: the BB leg had no eligible signal before ${state.last_trading_day}`}
                />
              </p>
            ) : (
              <table className="w-full text-xs font-mono">
                <thead className="text-[10px] uppercase text-[var(--text-tertiary)] border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left py-2">Action</th>
                    <th className="text-left py-2">Symbol</th>
                    <th className="text-right py-2">Shares</th>
                    <th className="text-right py-2">Price</th>
                    <th className="text-right py-2">Cost</th>
                  </tr>
                </thead>
                <tbody>
                  {state.today_trades.map((t, i) => (
                    <tr
                      key={i}
                      className="border-b border-[var(--border)]/40 last:border-0"
                    >
                      <td
                        className={`py-2 ${
                          t.action === "buy"
                            ? "text-[var(--green)]"
                            : "text-[var(--red)]"
                        }`}
                      >
                        {t.action.toUpperCase()}
                      </td>
                      <td className="py-2 text-[var(--text-primary)]">
                        {t.symbol}
                      </td>
                      <td className="py-2 text-right">
                        {fmtNum(t.shares, 0)}
                      </td>
                      <td className="py-2 text-right">
                        {fmtNum(t.price, 2)}
                      </td>
                      <td className="py-2 text-right text-[var(--text-tertiary)]">
                        {fmtNum(t.cost, 2)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5">
            <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
              <Lang zh="当前持仓" en="Active positions" /> · {state.positions.length}
            </h2>
            {state.positions.length === 0 ? (
              <p className="text-xs font-mono text-[var(--text-tertiary)]">
                <Lang zh="无持仓" en="No positions" />
              </p>
            ) : (
              <table className="w-full text-xs font-mono">
                <thead className="text-[10px] uppercase text-[var(--text-tertiary)] border-b border-[var(--border)]">
                  <tr>
                    <th className="text-left py-2">Symbol</th>
                    <th className="text-right py-2">Shares</th>
                    <th className="text-right py-2">Cost</th>
                    <th className="text-right py-2">Mkt</th>
                    <th className="text-right py-2">P&amp;L %</th>
                  </tr>
                </thead>
                <tbody>
                  {state.positions
                    .slice()
                    .sort((a, b) => b.pnl_pct - a.pnl_pct)
                    .map((p, i) => (
                      <tr
                        key={i}
                        className="border-b border-[var(--border)]/40 last:border-0"
                      >
                        <td className="py-2 text-[var(--text-primary)]">
                          {p.symbol}
                        </td>
                        <td className="py-2 text-right">
                          {fmtNum(p.shares, 0)}
                        </td>
                        <td className="py-2 text-right text-[var(--text-tertiary)]">
                          {fmtNum(p.cost_price, 2)}
                        </td>
                        <td className="py-2 text-right">
                          {fmtNum(p.current_price, 2)}
                        </td>
                        <td
                          className={`py-2 text-right ${
                            p.pnl_pct > 0
                              ? "text-[var(--green)]"
                              : p.pnl_pct < 0
                                ? "text-[var(--red)]"
                                : ""
                          }`}
                        >
                          {fmtPct(p.pnl_pct)}
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            )}
          </div>
        </div>

        <div className="rounded-lg border border-[var(--border)] bg-[var(--surface-1)] p-5">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
            <Lang zh="预注册配置" en="Pre-registered config" /> (spec {state.spec_version})
          </h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
            <div>
              <div className="text-[10px] uppercase text-[var(--text-tertiary)] mb-1">
                <Lang zh="启用腿" en="Legs enabled" />
              </div>
              <div className="text-[var(--text-primary)]">
                {state.legs_enabled
                  ? Object.entries(state.legs_enabled)
                      .filter(([, v]) => v)
                      .map(([k]) => k.toUpperCase())
                      .join(" + ") || "NONE"
                  : "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-[var(--text-tertiary)] mb-1">
                <Lang zh="组合权重" en="Ensemble mix" />
              </div>
              <div className="text-[var(--text-primary)]">
                {state.ensemble_mix
                  ? Object.entries(state.ensemble_mix)
                      .map(([k, v]) => `${k}:${v.toFixed(1)}`)
                      .join(" / ")
                  : "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-[var(--text-tertiary)] mb-1">
                <Lang zh="总资金占比上限" en="Cap % of total" />
              </div>
              <div className="text-[var(--text-primary)]">
                {state.initial_capital_pct_of_total != null
                  ? fmtPct(state.initial_capital_pct_of_total, 0)
                  : "—"}
              </div>
            </div>
            <div>
              <div className="text-[10px] uppercase text-[var(--text-tertiary)] mb-1">
                <Lang zh="开始时间" en="Started" />
              </div>
              <div className="text-[var(--text-primary)]">
                {state.started_at ?? "—"}
              </div>
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
