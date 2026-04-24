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
import { Lang } from "@/components/layout/LanguageText";
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
        title={<Lang zh="模拟盘状态" en="Paper-trade state" />}
        subtitle={
          state
            ? `${state.strategy_id ?? "paper-trade"} · spec ${state.spec_version} · Day ${state.kill.running_days}`
            : <Lang zh="没有 EOD 快照" en="No EOD snapshot exported" />
        }
        description={<Lang zh="这页只展示运行状态。研究候选和否决 spec 默认折叠，避免和当前模拟盘混在一起。" en="This page is operational state only. Research candidates and rejected specs stay below the fold unless opened." />}
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />

      {state ? <StateOverview state={state} /> : <EmptyState />}

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow={<Lang zh="细节" en="Details" />}
          title={<Lang zh="展开审计轨迹" en="Open the audit trail" />}
          body={<Lang zh="默认视图保持紧凑；交易、持仓、风险消息和研究上下文都放在折叠区。" en="The default view stays compact. Expand rows for trades, positions, risk messages, and research context." />}
        />
        {state && (
          <div className="space-y-3">
            <DisclosurePanel
              tone={state.kill.action === "ok" ? "green" : "gold"}
              title={<Lang zh="风控动作和 kill-switch 输入" en="Risk action and kill-switch inputs" />}
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
              title={<Lang zh="持仓和未到期 entry" en="Positions and entries" />}
              summary={<Lang zh={`${state.positions.length} 个持仓 · ${state.open_entries_count} 个未到期 entry`} en={`${state.positions.length} holdings · ${state.open_entries_count} open entries`} />}
            >
              {state.positions.length === 0 ? (
                <p><Lang zh="当前没有活跃持仓。" en="No active positions." /></p>
              ) : (
                <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
                  <table className="w-full text-sm">
                    <thead className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                      <tr className="border-b border-[var(--border-soft)]">
                        <th className="px-4 py-3 text-left font-normal"><Lang zh="代码" en="Symbol" /></th>
                        <th className="px-4 py-3 text-right font-normal"><Lang zh="股数" en="Shares" /></th>
                        <th className="px-4 py-3 text-right font-normal"><Lang zh="成本" en="Cost" /></th>
                        <th className="px-4 py-3 text-right font-normal"><Lang zh="现价" en="Current" /></th>
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
              title={<Lang zh="当日订单" en="Daily orders" />}
              summary={<Lang zh={`${state.daily_summary.n_buys} 买入 · ${state.daily_summary.n_sells} 卖出 · 换手 ${fmtPct(state.daily_summary.turnover, 2)}`} en={`${state.daily_summary.n_buys} buys · ${state.daily_summary.n_sells} sells · turnover ${fmtPct(state.daily_summary.turnover, 2)}`} />}
            >
              {state.today_trades.length === 0 ? (
                <p><Lang zh="导出日没有交易。" en="No trades in the exported day." /></p>
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
        <SectionLabel eyebrow={<Lang zh="上下文" en="Context" />} title={<Lang zh="研究上下文单独折叠" en="Research context is separate" />} />
        <div className="space-y-3">
          <DisclosurePanel
            tone="red"
            title={<Lang zh="为什么 RIAD 组合没有标记为运行中" en="Why the RIAD combo is not marked as running" />}
            summary={<Lang zh="可执行 RIAD 版本没有保住 baseline 结果。" en="The executable RIAD version did not preserve the baseline result." />}
          >
            <p>
              <Lang
                zh="组合 spec 只作为 validation case 保留，不作为当前运行状态展示。在新的可执行腿通过 gate 之前，本页模拟盘状态仍是 BB-only。"
                en="The combo spec is kept as a validation case, not as current live state. The paper-trade state on this page remains BB-only until a new executable leg passes the gates."
              />
            </p>
            <div className="mt-3">
              <TextLink href="/validation"><Lang zh="查看 validation case" en="Open validation case" /></TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="blue"
            title={<Lang zh={`多因子研究基线：${dashboard.production_face}`} en={`Multi-factor research face: ${dashboard.production_face}`} />}
            summary={<Lang zh="仅作为研究基准，不是当前模拟盘策略。" en="Research benchmark only. It is not the current paper-trade strategy." />}
          >
            <p>{dashboard.note}</p>
            <div className="mt-3 flex flex-wrap gap-3">
              <TextLink href={`/strategy#${dashboard.production_face}`}><Lang zh="查看策略卡片" en="Open strategy card" /></TextLink>
              <TextLink href="/strategy/candidates"><Lang zh="查看候选池" en="Open candidate pool" /></TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <SectionLabel
          eyebrow={<Lang zh="最近运行" en="Recent runs" />}
          title={<Lang zh="回测仍然可审计" en="Backtests remain auditable" />}
          body={<Lang zh="这些是研究侧 run，不是 live trading 活动。" en="These are research-side runs, not live trading activity." />}
        />
        <div className="overflow-x-auto rounded-xl border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border-soft)] text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                <th className="px-4 py-3 text-left font-normal"><Lang zh="版本" en="Version" /></th>
                <th className="px-4 py-3 text-left font-normal"><Lang zh="创建时间" en="Created" /></th>
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
          {state.enabled ? <Lang zh="已启用" en="enabled" /> : <Lang zh="已关闭" en="disabled" />}
        </StatusPill>
        <StatusPill tone={riskTone}>{state.kill.action}</StatusPill>
        <StatusPill tone="neutral"><Lang zh={`最近交易日 ${state.last_trading_day}`} en={`last day ${state.last_trading_day}`} /></StatusPill>
      </div>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
        <EvidenceCard
          tone="green"
          label="NAV"
          value={fmtNum(state.last_nav, 0)}
          detail={<Lang zh={`初始 ${fmtNum(state.initial_capital, 0)}`} en={`initial ${fmtNum(state.initial_capital, 0)}`} />}
        />
        <EvidenceCard
          tone={state.cum_return >= 0 ? "green" : "red"}
          label={<Lang zh="累计收益" en="Cumulative" />}
          value={fmtPct(state.cum_return, 2)}
          detail={<Lang zh={`今日 ${(state.pnl_today >= 0 ? "+" : "") + fmtNum(state.pnl_today, 0)}`} en={`today ${(state.pnl_today >= 0 ? "+" : "") + fmtNum(state.pnl_today, 0)}`} />}
        />
        <EvidenceCard
          tone="blue"
          label={<Lang zh="敞口" en="Exposure" />}
          value={fmtPct(state.daily_summary.gross_weight, 1)}
          detail={<Lang zh={`${state.positions.length} 持仓 · ${state.open_entries_count} entries`} en={`${state.positions.length} positions · ${state.open_entries_count} entries`} />}
        />
        <EvidenceCard
          tone={riskTone}
          label={<Lang zh="风控" en="Risk" />}
          value={state.kill.action.toUpperCase()}
          detail={<Lang zh={`仓位缩放 ×${state.kill.position_scale.toFixed(1)}`} en={`position scale ×${state.kill.position_scale.toFixed(1)}`} />}
        />
      </div>
      <div className="mt-4">
        <Link
          href="/live/paper-trade"
          className="text-xs font-mono text-[var(--blue)] hover:underline"
        >
          <Lang zh="打开完整模拟盘归档 →" en="Open full paper-trade archive →" />
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
          <Lang zh=" 尚未导出。下一次 EOD 快照后运行 portfolio 数据导出。" en=" was not exported. Run the portfolio data export after the next EOD snapshot." />
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
