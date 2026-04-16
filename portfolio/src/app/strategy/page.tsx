import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  StrategyStatus,
  StrategyVersion,
  StrategyVersionsFile,
} from "@/lib/types";

const STATUS_STYLE: Record<StrategyStatus, { label: string; color: string; bg: string }> = {
  legacy: {
    label: "Legacy",
    color: "var(--text-tertiary)",
    bg: "rgba(148,163,184,0.12)",
  },
  "research-face": {
    label: "Research Face",
    color: "var(--blue)",
    bg: "rgba(59,130,246,0.12)",
  },
  candidate: {
    label: "Candidate",
    color: "var(--gold)",
    bg: "rgba(234,179,8,0.12)",
  },
  rejected: {
    label: "Rejected",
    color: "var(--red)",
    bg: "rgba(239,68,68,0.1)",
  },
  production: {
    label: "Production",
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
  v9: "var(--blue)",
  v10: "var(--red)",
  v16: "var(--green)",
};

export default async function StrategyPage() {
  const versionsFile = await readData<StrategyVersionsFile>(
    "strategy/versions.json"
  );

  const equityFiles = await Promise.all(
    versionsFile.versions.map(async (v) =>
      v.equity_file
        ? { id: v.id, curve: await readDataOrNull<EquityCurveFile>(`strategy/${v.equity_file}`) }
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
      dashed: v.status === "rejected",
      curve: equityById.get(v.id)!,
    }));

  const activeVersion = versionsFile.versions.find((v) => v.is_active);

  return (
    <>
      <PageHeader
        eyebrow="Strategy · 策略"
        title="Multi-Factor Strategy Construction"
        subtitle={`Research face ${versionsFile.research_face} · Production face ${versionsFile.production_face}`}
        description="四代策略串起来的叙事：v7 手工权重基线 → v9 ICIR 学习研究门面 → v10 加止损被诚实否决 → v16 因子挖掘 9 因子生产门面。每一代的失败都留在记录里。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Strategy" }]}
      />

      {activeVersion && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <ActiveBanner version={activeVersion} note={versionsFile.active_note} />
        </section>
      )}

      {series.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Equity Curves — {series[0]!.curve.points[0]?.date?.slice(0, 7)} → {series[0]!.curve.points.at(-1)?.date?.slice(0, 7)}
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            v9 / v10 / v16 共同起点，cumulative return 叠加。v10 虚线 = 已否决（OOS 表现证伪）。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart series={series} height={360} />
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Version Timeline — 四代演化
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          按时间排列。每个版本卡片包含：因子清单、admission gate 指标、同期 v7 对照。
        </p>
        <ol className="relative border-l border-[var(--border-soft)] ml-2 space-y-6">
          {versionsFile.versions.map((v) => (
            <VersionCard key={v.id} version={v} />
          ))}
        </ol>
      </section>
    </>
  );
}

function ActiveBanner({
  version,
  note,
}: {
  version: StrategyVersion;
  note: string | null;
}) {
  return (
    <div className="rounded-lg border border-[var(--green)]/40 bg-[var(--green)]/[0.06] p-5 flex items-start gap-4">
      <div className="shrink-0 mt-1">
        <span className="inline-block w-2 h-2 rounded-full bg-[var(--green)] animate-pulse" />
      </div>
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--green)]">
          <span>Live Active</span>
          <span className="text-[var(--text-tertiary)]">· {version.id}</span>
        </div>
        <h3 className="mt-1 text-lg font-semibold text-[var(--text-primary)]">
          {version.name_en} · {version.name_zh}
        </h3>
        {note && (
          <p className="mt-2 text-xs font-mono text-[var(--text-tertiary)] break-all">
            {note}
          </p>
        )}
      </div>
    </div>
  );
}

function VersionCard({ version }: { version: StrategyVersion }) {
  const s = STATUS_STYLE[version.status];
  const m = version.metrics;
  const rejected = version.status === "rejected";

  return (
    <li className="ml-5 relative">
      <span
        className="absolute -left-[27px] top-2 w-3 h-3 rounded-full border-2"
        style={{
          background: rejected ? "var(--bg-base)" : s.color,
          borderColor: s.color,
        }}
      />
      <article
        className={`rounded-lg border bg-[var(--bg-surface)]/40 p-5 ${
          rejected
            ? "border-[var(--red)]/30"
            : version.is_active
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
                  ? "text-[var(--text-secondary)] line-through decoration-[var(--red)]/50 decoration-1"
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
                  label: "Annualized",
                  value: fmtPct(m.annualized_return, 2),
                  tone:
                    m.annualized_return !== null && m.annualized_return >= 0.15
                      ? "good"
                      : rejected
                      ? "bad"
                      : "warn",
                },
                {
                  label: "Sharpe",
                  value: fmtNum(m.sharpe, 3),
                  tone:
                    m.sharpe !== null && m.sharpe >= 0.8
                      ? "good"
                      : rejected
                      ? "bad"
                      : "warn",
                  hint: rejected ? "IS 0.84 但 OOS 仅 0.27" : undefined,
                },
                {
                  label: "Max Drawdown",
                  value: fmtPct(m.max_drawdown, 1),
                  tone:
                    m.max_drawdown !== null && m.max_drawdown > -0.3
                      ? "good"
                      : "bad",
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
                <span className="text-[var(--text-tertiary)] shrink-0">›</span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
          <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-2">
            Factor Composition · {version.factors.length}
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

        {(version.run_id || version.eval_report) && (
          <div className="mt-3 text-[10px] font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-4 gap-y-1">
            {version.run_id && (
              <span>run_id: {version.run_id}</span>
            )}
            {version.eval_report && (
              <Link
                href={`/validation`}
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
