import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  LiveDashboard,
  LiveRunSummary,
  StrategyVersion,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function LivePage() {
  const [dashboard, versionsFile, v9Curve] = await Promise.all([
    readData<LiveDashboard>("live/dashboard.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
    readDataOrNull<EquityCurveFile>("strategy/equity_v9.json"),
  ]);

  const face = versionsFile.versions.find(
    (v) => v.id === dashboard.production_face
  );
  const candidate = versionsFile.versions.find(
    (v) => v.id === dashboard.candidate
  );
  const declared = versionsFile.versions.find(
    (v) => v.id === dashboard.declared_active
  );
  const lastSignal = versionsFile.versions.find(
    (v) => v.id === dashboard.last_signal_strategy
  );

  const declaredNeFace =
    dashboard.declared_active !== null &&
    dashboard.declared_active !== dashboard.production_face;

  const signalNeDeclared =
    dashboard.last_signal_strategy !== null &&
    dashboard.last_signal_strategy !== dashboard.declared_active;

  return (
    <>
      <PageHeader
        title="Live · 实盘"
        subtitle="Paper trading · state reconciliation"
        description="不展示 real money 持仓；只展示 paper trading 的可复现 audit trail。重点：声明的 active、实际 face、最近 signal 使用的策略 — 这三者是否一致。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          State Reconciliation · 三者对齐情况
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-3xl leading-relaxed">
          一个诚实的 control plane 必须区分三件事：
          <span className="text-[var(--text-primary)]">&ldquo;我们声明哪个在 active&rdquo;</span>、
          <span className="text-[var(--text-primary)]">&ldquo;WF 验证过的 face 是哪个&rdquo;</span>、
          <span className="text-[var(--text-primary)]">&ldquo;最近一次 signal 实际使用哪个&rdquo;</span>。
          三者一致是理想状态；不一致就要写明白为什么。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <StateCard
            tag="Production face"
            subtitle="WF validated · 4 条 gate 都过"
            version={face}
            tone="green"
          />
          <StateCard
            tag="Declared active"
            subtitle={`state file · ${dashboard.state_updated_at?.slice(0, 10) ?? "—"}`}
            version={declared}
            tone={declaredNeFace ? "gold" : "green"}
            footnote={
              declaredNeFace
                ? `declared ${dashboard.declared_active} ≠ face ${dashboard.production_face}`
                : undefined
            }
          />
          <StateCard
            tag="Last signal used"
            subtitle={
              dashboard.signal_dates[0]
                ? `latest ${dashboard.signal_dates[0]}`
                : "no recent signals"
            }
            version={lastSignal}
            tone={signalNeDeclared ? "red" : "green"}
            footnote={
              signalNeDeclared
                ? `signal ${dashboard.last_signal_strategy} ≠ declared ${dashboard.declared_active}`
                : undefined
            }
          />
        </div>
        {(declaredNeFace || signalNeDeclared) && (
          <div className="mt-5 rounded-lg border border-[var(--gold)]/35 bg-[var(--gold)]/[0.05] p-4 text-sm leading-relaxed text-[var(--text-secondary)]">
            <p className="font-semibold text-[var(--gold)] mb-2 text-xs font-mono uppercase tracking-[0.15em]">
              不一致的诚实说明
            </p>
            {declaredNeFace && (
              <p className="mb-2">
                · <span className="font-mono">{dashboard.declared_active}</span>{" "}
                被写进 <code className="font-mono text-xs">state/active.json</code>{" "}
                是因子挖掘会话的&ldquo;最高 sharpe&rdquo;候选；但它还没跑完 WF 17 窗口，
                也没过 admission gate 的回撤红线 —
                所以真正配得上&ldquo;生产门面&rdquo;的仍是{" "}
                <span className="font-mono text-[var(--green)]">
                  {dashboard.production_face}
                </span>
                。见{" "}
                <Link href="/validation" className="text-[var(--red)] hover:underline">
                  为什么 v16 不能直接上 production
                </Link>
                。
              </p>
            )}
            {signalNeDeclared && (
              <p>
                · 最近 signal 文件使用的是{" "}
                <span className="font-mono">{dashboard.last_signal_strategy}</span>{" "}
                的因子列表，说明 pipeline 的&ldquo;声明 active&rdquo;和&ldquo;signal 生成器读的 factor 列表&rdquo;
                还没打通 — 需要修 <code className="font-mono text-xs">pipeline/signal_gen.py</code>。
              </p>
            )}
          </div>
        )}
        {dashboard.declared_note && (
          <p className="mt-4 text-xs font-mono text-[var(--text-tertiary)] break-all leading-relaxed">
            state note: {dashboard.declared_note}
          </p>
        )}
      </section>

      {v9Curve && face && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Face Equity — {face.id} since 2022
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
            这条是 production face 的 paper trading equity curve，
            {v9Curve.points.length} 个交易日。
            2025 OOS 段继续上行，是 WF 中位 0.53 的现实体现。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart
              series={[
                {
                  id: "v9",
                  label: `${face.id} · face`,
                  color: "var(--green)",
                  curve: v9Curve,
                },
              ]}
              height={320}
              stride={3}
            />
          </div>
          {face.metrics && (
            <div className="mt-4">
              <MetricGrid
                metrics={[
                  {
                    label: "Annual",
                    value: fmtPct(face.metrics.annualized_return, 2),
                    tone: "good",
                  },
                  {
                    label: "Sharpe",
                    value: fmtNum(face.metrics.sharpe, 3),
                    tone: (face.metrics.sharpe ?? 0) >= 0.8 ? "good" : "warn",
                    hint: "WF median 0.53",
                  },
                  {
                    label: "Max DD",
                    value: fmtPct(face.metrics.max_drawdown, 1),
                    tone: "neutral",
                  },
                  {
                    label: "Win Rate",
                    value: fmtPct(face.metrics.win_rate, 1),
                    tone: "neutral",
                  },
                ]}
              />
            </div>
          )}
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16 grid grid-cols-1 lg:grid-cols-2 gap-6">
        <PipelinePanel
          title="Signal Cadence · 最近 signal"
          subtitle={`每日收盘后：因子快照 → 组合权重计算 → signals/{date}.json · 最近文件使用 ${dashboard.last_signal_strategy ?? "—"} 的因子列表`}
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

      <section className="max-w-content mx-auto px-6 pb-16">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <h3 className="text-sm font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-2">
            Candidate queue
          </h3>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
            下一次可能晋升的候选 — 必须先过 WF 17 窗口 + admission gate 才能替换
            face。
          </p>
          {candidate && <CandidateRow version={candidate} />}
          <p className="mt-3 text-[10px] font-mono text-[var(--text-tertiary)]">
            完整候选池 ·{" "}
            <Link
              href="/strategy/candidates"
              className="hover:text-[var(--gold)]"
            >
              /strategy/candidates →
            </Link>
          </p>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Recent Runs — 最近 {dashboard.recent_runs.length} 次 backtest
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          因子挖掘会话的 run 历史 — v11-v21 是 2026-04-14 一轮完整搜索循环的产物。
          挑 sharpe 最高的候选（v16）上 live 前，必须先跑 WF — 目前还没。
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
                  isCandidate={r.strategy_id === `multi_factor_${candidate?.id}`}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function StateCard({
  tag,
  subtitle,
  version,
  tone,
  footnote,
}: {
  tag: string;
  subtitle: string;
  version: StrategyVersion | undefined;
  tone: "green" | "gold" | "red";
  footnote?: string;
}) {
  const toneColor =
    tone === "green"
      ? "var(--green)"
      : tone === "gold"
      ? "var(--gold)"
      : "var(--red)";
  return (
    <div
      className="rounded-lg border p-4 bg-[var(--bg-surface)]/40"
      style={{
        borderColor: `color-mix(in srgb, ${toneColor} 30%, transparent)`,
      }}
    >
      <div className="flex items-center gap-2 mb-1">
        <span
          className="w-2 h-2 rounded-full"
          style={{ background: toneColor }}
        />
        <span
          className="text-[10px] font-mono uppercase tracking-[0.15em]"
          style={{ color: toneColor }}
        >
          {tag}
        </span>
      </div>
      <p className="text-[10px] font-mono text-[var(--text-tertiary)] mb-3">
        {subtitle}
      </p>
      <p className="font-mono text-lg font-semibold text-[var(--text-primary)]">
        {version?.id ?? "—"}
      </p>
      {version?.name_zh && (
        <p className="text-xs text-[var(--text-secondary)] mt-0.5">
          {version.name_zh}
        </p>
      )}
      {footnote && (
        <p
          className="mt-3 pt-3 border-t text-[10px] font-mono leading-relaxed"
          style={{
            borderColor: `color-mix(in srgb, ${toneColor} 20%, transparent)`,
            color: toneColor,
          }}
        >
          {footnote}
        </p>
      )}
    </div>
  );
}

function CandidateRow({ version }: { version: StrategyVersion }) {
  const m = version.metrics;
  return (
    <div className="flex flex-wrap items-center gap-3 text-sm">
      <span
        className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
        style={{
          color: "var(--gold)",
          background: "color-mix(in srgb, var(--gold) 12%, transparent)",
        }}
      >
        candidate
      </span>
      <span className="font-mono font-semibold text-[var(--text-primary)]">
        {version.id}
      </span>
      <span className="text-xs text-[var(--text-secondary)]">
        {version.name_zh}
      </span>
      {m && (
        <span className="text-xs font-mono text-[var(--text-tertiary)] ml-auto">
          年化 {fmtPct(m.annualized_return, 1)} · Sharpe {fmtNum(m.sharpe, 2)} ·
          DD {fmtPct(m.max_drawdown, 1)}
        </span>
      )}
    </div>
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
  isCandidate,
}: {
  run: LiveRunSummary;
  isCandidate: boolean;
}) {
  const version = run.strategy_id?.replace(/^multi_factor_/, "") ?? "?";
  return (
    <tr
      className={`border-b border-[var(--border-soft)] last:border-b-0 ${
        isCandidate ? "bg-[var(--gold)]/[0.05]" : ""
      }`}
    >
      <td className="px-4 py-3 font-mono font-semibold text-[var(--text-primary)]">
        {version}
        {isCandidate && (
          <span className="ml-2 text-[10px] text-[var(--gold)] uppercase tracking-[0.15em]">
            candidate
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
