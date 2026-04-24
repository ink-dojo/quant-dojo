import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
  TextLink,
} from "@/components/layout/Primitives";
import { Lang } from "@/components/layout/LanguageText";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  GateCheck,
  StrategyStatus,
  StrategyVersion,
  StrategyVersionsFile,
} from "@/lib/types";

const STATUS_STYLE: Record<
  StrategyStatus,
  { label: string; color: string; bg: string }
> = {
  legacy: {
    label: "Legacy",
    color: "var(--text-tertiary)",
    bg: "rgba(148,163,184,0.12)",
  },
  "research-face": {
    label: "Research face",
    color: "var(--blue)",
    bg: "rgba(59,130,246,0.12)",
  },
  candidate: {
    label: "Candidate · pending WF",
    color: "var(--gold)",
    bg: "rgba(234,179,8,0.12)",
  },
  rejected: {
    label: "Rejected",
    color: "var(--red)",
    bg: "rgba(239,68,68,0.1)",
  },
  production: {
    label: "Research face (WF validated)",
    color: "var(--green)",
    bg: "rgba(34,197,94,0.12)",
  },
  running: {
    label: "Running",
    color: "var(--purple)",
    bg: "rgba(168,85,247,0.12)",
  },
};

const SERIES_COLORS: Record<string, string> = {
  v7: "var(--text-tertiary)",
  v9: "var(--green)",
  v10: "var(--red)",
  v16: "var(--gold)",
};

export default async function StrategyPage() {
  const versionsFile = await readData<StrategyVersionsFile>(
    "strategy/versions.json"
  );

  const equityFiles = await Promise.all(
    versionsFile.versions.map(async (v) =>
      v.equity_file
        ? {
            id: v.id,
            curve: await readDataOrNull<EquityCurveFile>(
              `strategy/${v.equity_file}`
            ),
          }
        : { id: v.id, curve: null }
    )
  );
  const equityById = new Map(
    equityFiles.filter((e) => e.curve !== null).map((e) => [e.id, e.curve!])
  );

  const series = versionsFile.versions
    .filter((v) => equityById.has(v.id))
    .map((v) => ({
      id: v.id,
      label: `${v.id} · ${v.name_zh}`,
      color: SERIES_COLORS[v.id] ?? "var(--cyan)",
      dashed: v.status === "rejected" || v.status === "candidate",
      curve: equityById.get(v.id)!,
    }));

  const face = versionsFile.versions.find(
    (v) => v.id === versionsFile.production_face
  );
  const candidate = versionsFile.versions.find(
    (v) => v.id === versionsFile.candidate
  );
  const rejected = versionsFile.versions.find((v) => v.status === "rejected");

  return (
    <>
      <PageHeader
        eyebrow="Strategy"
        title={<Lang zh="多因子研究线" en="Multi-factor line" />}
        subtitle={<Lang zh="这里只是研究版本 · 模拟盘状态以 /live 为准" en="Research versions only · paper-trade lives under /live" />}
        description={<Lang zh="这页追踪版本化研究产物。除非 Live 页明确说明，否则任何版本都不代表正在运行。" en="This page tracks versioned research artifacts. It does not imply that a version is running unless the live page says so." />}
        crumbs={[{ label: "Home", href: "/" }, { label: "Strategy" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <EvidenceCard
            tone="green"
            label={<Lang zh="研究基线" en="Research face" />}
            value={face?.id ?? "—"}
            detail={<Lang zh="这条线的 WF 验证基准" en="WF-validated benchmark for this line" />}
            href={face ? `#${face.id}` : undefined}
          />
          <EvidenceCard
            tone="red"
            label={<Lang zh="已否决" en="Rejected" />}
            value={rejected?.id ?? "—"}
            detail={<Lang zh="止损层在 OOS 表现失败" en="Stop-loss layer failed OOS behavior" />}
            href="/validation"
          />
          <EvidenceCard
            tone="gold"
            label={<Lang zh="候选" en="Candidate" />}
            value={candidate?.id ?? "—"}
            detail={<Lang zh="保留用于审计，未晋级" en="Visible for audit; not promoted" />}
            href={candidate ? `#${candidate.id}` : undefined}
          />
        </div>
      </section>

      {face && (
        <section className="max-w-content mx-auto px-6 pb-10">
          <FaceBanner version={face} />
          <p className="mt-3 text-xs text-[var(--text-tertiary)] leading-relaxed max-w-3xl">
            {versionsFile.face_note}
          </p>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-10">
        <DisclosurePanel
          tone="blue"
          title={<Lang zh="版本时间线" en="Version timeline" />}
          summary={<Lang zh="需要看演化顺序时再打开完整 v7 → v25。" en="Open the full v7 → v25 evolution only when you need chronology." />}
        >
          <p>
            <Lang zh="时间线记录每个版本的动机、方法、结果、教训和下一步触发点。" en="The timeline records motivation, method, result, lesson, and the next trigger for every version." />
          </p>
          <div className="mt-3">
            <TextLink href="/strategy/multi-factor"><Lang zh="打开多因子时间线" en="Open multi-factor timeline" /></TextLink>
          </div>
        </DisclosurePanel>
      </section>

      {series.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <DisclosurePanel
            tone="neutral"
            title={<Lang zh="净值对比" en="Equity overlay" />}
            summary={<Lang zh="先看状态标签，再打开图表；高收益不等于批准。" en="Open the chart after reading the status labels; high return does not equal approval." />}
          >
            <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/40 p-4">
              <EquityChart series={series} height={380} />
            </div>
          </DisclosurePanel>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <DisclosurePanel
          tone="green"
          title={<Lang zh="Admission gate 表" en="Admission gate table" />}
          summary={<Lang zh="打开 gate 矩阵查看逐项指标对比。" en="Open the gate matrix for exact metric-by-metric comparison." />}
        >
          <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-soft)] text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                  <th className="px-4 py-3 text-left font-normal">Gate</th>
                  <th className="px-4 py-3 text-left font-normal"><Lang zh="门槛" en="Threshold" /></th>
                  <th className="px-4 py-3 text-right font-normal"><Lang zh="基线" en="Face" /></th>
                  <th className="px-4 py-3 text-right font-normal"><Lang zh="已否决" en="Rejected" /></th>
                  <th className="px-4 py-3 text-right font-normal"><Lang zh="候选" en="Candidate" /></th>
                </tr>
              </thead>
              <tbody className="font-mono">
                <GateRow
                  label="Annual"
                  threshold="> 15%"
                  v9={face?.metrics?.annualized_return ?? null}
                  v10={rejected?.metrics?.annualized_return ?? null}
                  v16={candidate?.metrics?.annualized_return ?? null}
                  format="pct"
                  pass={(v) => (v ?? 0) >= 0.15}
                />
                <GateRow
                  label="Sharpe"
                  threshold="> 0.8"
                  v9={face?.metrics?.sharpe ?? null}
                  v10={rejected?.metrics?.sharpe ?? null}
                  v16={candidate?.metrics?.sharpe ?? null}
                  format="num"
                  pass={(v) => (v ?? 0) >= 0.8}
                />
                <GateRow
                  label="Max DD"
                  threshold="> -30%"
                  v9={face?.metrics?.max_drawdown ?? null}
                  v10={rejected?.metrics?.max_drawdown ?? null}
                  v16={candidate?.metrics?.max_drawdown ?? null}
                  format="pct"
                  pass={(v) => (v ?? 0) > -0.3}
                />
              </tbody>
            </table>
          </div>
        </DisclosurePanel>
      </section>

      <section id="versions" className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow={<Lang zh="版本卡片" en="Version cards" />}
          title={<Lang zh="按版本排序的研究产物" en="Open source artifacts, ordered by version" />}
          body={<Lang zh="每张卡片包含状态、指标、因子和 gate 备注。" en="Each card carries status, metrics, factors, and gate notes." />}
        />
        <ol className="relative border-l border-[var(--border-soft)] ml-2 space-y-6">
          {versionsFile.versions.map((v) => (
            <VersionCard key={v.id} version={v} />
          ))}
        </ol>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="rounded-lg border border-[var(--gold)]/30 bg-[var(--gold)]/[0.04] p-5">
          <h3 className="text-sm font-semibold text-[var(--gold)] mb-2">
            想看 v16 是怎么从 11 个候选里挑出来的？
          </h3>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
            2026-04-14 的因子挖掘会话生成了 v11–v21 共 11 个多因子策略。把它们全部
            sharpe 排序后，你会发现 v16
            并不是孤立的最优解，而是 best-in-sample — 这正是 v10 当初被否决的同一类陷阱。
          </p>
          <Link
            href="/strategy/candidates"
            className="inline-block text-xs font-mono text-[var(--gold)] hover:underline"
          >
            看完整的 11 个候选对比 →
          </Link>
        </div>
      </section>
    </>
  );
}

function FaceBanner({ version }: { version: StrategyVersion }) {
  const m = version.metrics;
  return (
    <div className="rounded-lg border border-[var(--green)]/40 bg-[var(--green)]/[0.05] p-5">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <span className="inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.18em] text-[var(--green)]">
          <span className="w-2 h-2 rounded-full bg-[var(--green)]" />
          Research face · WF validated
        </span>
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          {version.id} · {version.name_en}
        </span>
        <span className="text-xs font-mono text-[var(--text-tertiary)]">
          {version.factors.length} factors · WF validated
        </span>
      </div>
      {m && (
        <div className="mt-3">
          <MetricGrid
            metrics={[
              {
                label: "年化",
                value: fmtPct(m.annualized_return, 1),
                tone: "good",
              },
              {
                label: "Sharpe",
                value: fmtNum(m.sharpe, 3),
                tone: (m.sharpe ?? 0) >= 0.8 ? "good" : "warn",
                hint: "WF 中位 0.53",
              },
              {
                label: "Max DD",
                value: fmtPct(m.max_drawdown, 1),
                tone: (m.max_drawdown ?? 0) > -0.3 ? "good" : "warn",
              },
              {
                label: "Win Rate",
                value: fmtPct(m.win_rate, 1),
                tone: "neutral",
              },
            ]}
          />
        </div>
      )}
    </div>
  );
}

function ReadingHint({
  color,
  title,
  body,
}: {
  color: string;
  title: string;
  body: string;
}) {
  return (
    <div
      className="rounded-md p-3 border"
      style={{
        borderColor: `color-mix(in srgb, ${color} 28%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <p className="font-semibold mb-1" style={{ color }}>
        {title}
      </p>
      <p className="text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}

function GateRow({
  label,
  threshold,
  v9,
  v10,
  v16,
  format,
  pass,
}: {
  label: string;
  threshold: string;
  v9: number | null;
  v10: number | null;
  v16: number | null;
  format: "pct" | "num";
  pass: (v: number | null) => boolean;
}) {
  const fmt = (v: number | null) =>
    v === null ? "—" : format === "pct" ? fmtPct(v, 1) : fmtNum(v, 3);
  const cell = (v: number | null, key: string) => (
    <td
      key={key}
      className="px-4 py-3 text-right"
      style={{ color: pass(v) ? "var(--green)" : "var(--red)" }}
    >
      {pass(v) ? "✓ " : "✗ "}
      {fmt(v)}
    </td>
  );
  return (
    <tr className="border-t border-[var(--border-soft)]">
      <td className="px-4 py-3 text-[var(--text-primary)]">{label}</td>
      <td className="px-4 py-3 text-[var(--text-tertiary)]">{threshold}</td>
      {cell(v9, "v9")}
      {cell(v10, "v10")}
      {cell(v16, "v16")}
    </tr>
  );
}

function VersionCard({ version }: { version: StrategyVersion }) {
  const s = STATUS_STYLE[version.status];
  const m = version.metrics;
  const rejected = version.status === "rejected";
  const isCandidate = version.status === "candidate";
  const isFace = version.status === "production";

  return (
    <li id={version.id} className="ml-5 relative scroll-mt-24">
      <span
        className="absolute -left-[27px] top-2 w-3 h-3 rounded-full border-2"
        style={{
          background: rejected || isCandidate ? "var(--bg-base)" : s.color,
          borderColor: s.color,
        }}
      />
      <article
        className={`rounded-lg border bg-[var(--bg-surface)]/40 p-5 ${
          rejected
            ? "border-[var(--red)]/30"
            : isCandidate
            ? "border-[var(--gold)]/35"
            : isFace
            ? "border-[var(--green)]/40"
            : "border-[var(--border-soft)]"
        }`}
      >
        <header className="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
                style={{ color: s.color, background: s.bg }}
              >
                {s.label}
              </span>
              <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                {version.era_start}
              </span>
            </div>
            <h3
              className={`text-lg font-semibold ${
                rejected
                  ? "text-[var(--text-secondary)] line-through decoration-[var(--red)]/50"
                  : "text-[var(--text-primary)]"
              }`}
            >
              <span className="font-mono mr-2">{version.id}</span>
              {version.name_en}
            </h3>
            <p className="text-xs font-mono text-[var(--text-tertiary)] mt-0.5">
              {version.name_zh}
            </p>
            <p className="mt-2 text-sm text-[var(--text-secondary)] leading-relaxed">
              {version.tagline}
            </p>
          </div>
        </header>

        {m && (
          <div className="mt-4 mb-4">
            <MetricGrid
              metrics={[
                {
                  label: "年化",
                  value: fmtPct(m.annualized_return, 2),
                  tone: rejected
                    ? "bad"
                    : (m.annualized_return ?? 0) >= 0.15
                    ? "good"
                    : "warn",
                },
                {
                  label: "Sharpe",
                  value: fmtNum(m.sharpe, 3),
                  tone: rejected
                    ? "bad"
                    : (m.sharpe ?? 0) >= 0.8
                    ? "good"
                    : "warn",
                  hint: rejected
                    ? "IS 0.63 但 OOS 仅 0.27"
                    : isCandidate
                    ? "未达 0.8 门槛"
                    : undefined,
                },
                {
                  label: "Max DD",
                  value: fmtPct(m.max_drawdown, 1),
                  tone: (m.max_drawdown ?? 0) > -0.3 ? "good" : "bad",
                  hint: isCandidate ? "超 30% 红线" : undefined,
                },
                {
                  label: "Win Rate",
                  value: fmtPct(m.win_rate, 1),
                  tone: "neutral",
                },
              ]}
            />
          </div>
        )}

        {version.highlights && version.highlights.length > 0 && (
          <ul className="mt-3 space-y-1.5 text-xs text-[var(--text-secondary)]">
            {version.highlights.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className="shrink-0"
                  style={{
                    color: rejected
                      ? "var(--red)"
                      : isCandidate
                      ? "var(--gold)"
                      : "var(--text-tertiary)",
                  }}
                >
                  ›
                </span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
          <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-2">
            因子 · {version.factors.length}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {version.factors.map((f) => (
              <span
                key={f}
                className="text-[11px] font-mono px-2 py-0.5 rounded border border-[var(--border-soft)] text-[var(--text-secondary)]"
              >
                {f}
              </span>
            ))}
          </div>
        </div>

        {isCandidate && version.gate_check && (
          <GateCheckPanel check={version.gate_check} />
        )}

        {(version.run_id || version.eval_report) && (
          <div className="mt-3 text-[10px] font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-4 gap-y-1">
            {version.run_id && <span>run_id: {version.run_id}</span>}
            {version.eval_report && (
              <Link
                href="/validation"
                className="text-[var(--red)] hover:underline"
              >
                见否决报告 →
              </Link>
            )}
          </div>
        )}
      </article>
    </li>
  );
}

function GateCheckPanel({ check }: { check: Record<string, GateCheck> }) {
  const entries = Object.entries(check);
  return (
    <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--gold)] mb-2">
        Admission Gate Check
      </p>
      <ul className="space-y-1 text-xs font-mono">
        {entries.map(([k, v]) => (
          <li key={k} className="flex items-center gap-2">
            <span style={{ color: v.pass ? "var(--green)" : "var(--red)" }}>
              {v.pass ? "✓" : "✗"}
            </span>
            <span className="text-[var(--text-secondary)] min-w-[140px]">{k}</span>
            <span
              className="text-[var(--text-primary)]"
              style={{ color: v.pass ? "var(--text-primary)" : "var(--red)" }}
            >
              {typeof v.value === "boolean" ? String(v.value) : v.value}
            </span>
            <span className="text-[var(--text-tertiary)]">
              / threshold{" "}
              {typeof v.threshold === "boolean"
                ? String(v.threshold)
                : v.threshold}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
