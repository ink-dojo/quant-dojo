import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import type {
  DSRStrategiesFile,
  DSRStrategy,
  EquityCurveFile,
} from "@/lib/types";

interface PageParams {
  params: { id: string };
}

const STATUS_TONE: Record<string, string> = {
  paper_trade_candidate: "var(--green)",
  active: "var(--green)",
  component: "var(--blue)",
  retired: "var(--text-tertiary)",
  failed: "var(--red)",
  archived: "var(--text-tertiary)",
};

const STATUS_LABEL_ZH: Record<string, string> = {
  paper_trade_candidate: "paper-trade 候选",
  active: "paper running",
  component: "ensemble 成分",
  retired: "已退役",
  failed: "已证伪",
  archived: "已归档",
};

export async function generateStaticParams(): Promise<{ id: string }[]> {
  const f = await readData<DSRStrategiesFile>("event_driven/strategies.json");
  return f.strategies.map((s) => ({ id: s.id }));
}

export async function generateMetadata({
  params,
}: PageParams): Promise<Metadata> {
  const f = await readData<DSRStrategiesFile>("event_driven/strategies.json");
  const s = f.strategies.find((x) => x.id === params.id);
  if (!s) return { title: "Strategy not found" };
  return { title: `${s.name_en} · QuantDojo`, description: s.tagline };
}

export default async function DSRDetailPage({ params }: PageParams) {
  const f = await readData<DSRStrategiesFile>("event_driven/strategies.json");
  const idx = f.strategies.findIndex((s) => s.id === params.id);
  if (idx < 0) notFound();
  const s = f.strategies[idx]!;

  const equity = s.equity_file
    ? await readDataOrNull<EquityCurveFile>(`event_driven/${s.equity_file}`)
    : null;

  const prev = idx > 0 ? f.strategies[idx - 1] : null;
  const next = idx < f.strategies.length - 1 ? f.strategies[idx + 1] : null;

  return (
    <>
      <PageHeader
        eyebrow="Event-Driven · DSR Deep-Dive"
        title={s.name_en}
        subtitle={`${s.id} · ${s.name_zh}`}
        description={s.tagline}
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: "Event-Driven", href: "/research/event-driven" },
          { label: s.id },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-8">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span
            className="font-mono px-2 py-0.5 rounded uppercase tracking-[0.15em]"
            style={{
              color: STATUS_TONE[s.status] ?? "var(--text-secondary)",
              background: "var(--bg-surface)",
            }}
          >
            {STATUS_LABEL_ZH[s.status] ?? s.status}
          </span>
          <span className="font-mono text-[var(--text-tertiary)]">
            {s.category} · {s.direction}
          </span>
          <span className="font-mono text-[var(--text-tertiary)]">
            hold: {s.hold_window}
          </span>
          <span className="font-mono text-[var(--text-tertiary)] ml-auto">
            unit {s.sizing.unit} · gross≤{s.sizing.gross_cap}
          </span>
        </div>
        {s.status_note && (
          <p className="text-sm text-[var(--text-secondary)] mt-3 leading-relaxed">
            {s.status_note}
          </p>
        )}
      </section>

      <section className="max-w-content mx-auto px-6 pb-10">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
          8-Year Metrics
        </h2>
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <MetricGrid
            metrics={[
              {
                label: "Ann Return",
                value: fmtPct(s.metrics_8yr.ann_return, 2),
                tone:
                  s.metrics_8yr.ann_return !== null && s.metrics_8yr.ann_return >= 0.15
                    ? "good"
                    : s.metrics_8yr.ann_return !== null && s.metrics_8yr.ann_return < 0
                    ? "bad"
                    : "warn",
              },
              {
                label: "Sharpe",
                value: fmtNum(s.metrics_8yr.sharpe, 2),
                tone:
                  s.metrics_8yr.sharpe !== null && s.metrics_8yr.sharpe >= 0.8
                    ? "good"
                    : s.metrics_8yr.sharpe !== null && s.metrics_8yr.sharpe < 0
                    ? "bad"
                    : "warn",
              },
              {
                label: "Max DD",
                value: fmtPct(s.metrics_8yr.max_drawdown, 2),
                tone:
                  s.metrics_8yr.max_drawdown !== null &&
                  s.metrics_8yr.max_drawdown > -0.3
                    ? "good"
                    : "bad",
              },
              {
                label: "PSR",
                value: fmtPct(s.metrics_8yr.psr, 1),
                tone:
                  s.metrics_8yr.psr !== null && s.metrics_8yr.psr >= 0.95
                    ? "good"
                    : "warn",
              },
              {
                label: "SR CI Low",
                value: fmtNum(s.metrics_8yr.sharpe_ci_low, 2),
                tone:
                  s.metrics_8yr.sharpe_ci_low !== null &&
                  s.metrics_8yr.sharpe_ci_low >= 0.5
                    ? "good"
                    : "warn",
              },
              {
                label: "N obs",
                value: String(s.metrics_8yr.n_obs ?? "—"),
                tone: "neutral",
              },
            ]}
          />
        </div>
        <p className="text-xs font-mono text-[var(--text-tertiary)] mt-3">
          最近 24 月 Sharpe: {fmtNum(s.recent_24m_sharpe, 2)} ·{" "}
          {s.recent_24m_sharpe !== null && s.recent_24m_sharpe > s.metrics_8yr.sharpe!
            ? "无 alpha 衰减"
            : s.recent_24m_sharpe !== null && s.recent_24m_sharpe < 0
            ? "近期主动亏钱 — alpha 已死"
            : "待观察"}
        </p>
      </section>

      <section className="max-w-content mx-auto px-6 pb-10">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
          5-Gate Admission Check
        </h2>
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <ul className="space-y-2 text-sm font-mono">
            <GateRow
              label="ann_return ≥ 15%"
              pass={s.gates_5.ann_ge_15pct}
              actual={fmtPct(s.metrics_8yr.ann_return, 2)}
            />
            <GateRow
              label="sharpe ≥ 0.8"
              pass={s.gates_5.sharpe_ge_08}
              actual={fmtNum(s.metrics_8yr.sharpe, 2)}
            />
            <GateRow
              label="max_dd > -30%"
              pass={s.gates_5.mdd_gt_neg30pct}
              actual={fmtPct(s.metrics_8yr.max_drawdown, 2)}
            />
            <GateRow
              label="PSR ≥ 95%"
              pass={s.gates_5.psr_ge_95pct}
              actual={fmtPct(s.metrics_8yr.psr, 1)}
            />
            <GateRow
              label="SR CI low ≥ 0.5"
              pass={s.gates_5.ci_low_ge_05}
              actual={fmtNum(s.metrics_8yr.sharpe_ci_low, 2)}
            />
          </ul>
          <p className="text-xs font-mono text-[var(--text-tertiary)] mt-4 pt-3 border-t border-[var(--border-soft)]">
            {s.gates_5.n_pass}/5 gates passed
          </p>
        </div>
      </section>

      <Section title="Event Source & Universe · 事件源和股票池">
        <dl className="grid grid-cols-1 md:grid-cols-2 gap-3 text-xs font-mono">
          <InfoKV k="event_source" v={s.event_source} />
          <InfoKV k="universe_filter" v={s.universe_filter} />
          <InfoKV k="hold_window" v={s.hold_window} />
          <InfoKV k="direction" v={s.direction} />
          <InfoKV k="unit" v={s.sizing.unit} />
          <InfoKV k="gross_cap" v={String(s.sizing.gross_cap)} />
        </dl>
      </Section>

      <Section title="Theory · 理论基础">
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">{s.theory}</p>
      </Section>

      {equity && equity.points.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-10">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Equity Curve
          </h2>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart
              series={[
                {
                  id: s.id,
                  label: s.name_en,
                  color: "var(--green)",
                  curve: equity,
                },
              ]}
            />
          </div>
        </section>
      )}

      {s.highlights && s.highlights.length > 0 && (
        <Section title="Highlights · 要点">
          <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1.5">
            {s.highlights.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </Section>
      )}

      {s.failure_modes && s.failure_modes.length > 0 && (
        <Section title="Failure Modes · 失败模式">
          <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1.5">
            {s.failure_modes.map((h, i) => (
              <li key={i}>{h}</li>
            ))}
          </ul>
        </Section>
      )}

      {s.decay_evidence && (
        <Section title="Decay Evidence · 衰减证据">
          <p className="text-sm font-mono text-[var(--text-secondary)]">{s.decay_evidence}</p>
        </Section>
      )}

      {s.paper_trade_spec && (
        <Section title="Paper Trade Spec">
          <p className="text-sm font-mono text-[var(--text-secondary)]">{s.paper_trade_spec}</p>
        </Section>
      )}

      {s.refs && s.refs.length > 0 && (
        <Section title="References">
          <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1">
            {s.refs.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </Section>
      )}

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="flex justify-between items-center gap-4 pt-8 border-t border-[var(--border-soft)]">
          {prev ? (
            <Link
              href={`/research/event-driven/${prev.id}`}
              className="group flex flex-col gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                ← Prev
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
                {prev.name_en}
              </span>
            </Link>
          ) : (
            <span />
          )}
          <Link
            href="/research/event-driven"
            className="text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--text-primary)] shrink-0"
          >
            All DSR trials →
          </Link>
          {next ? (
            <Link
              href={`/research/event-driven/${next.id}`}
              className="group flex flex-col items-end gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                Next →
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
                {next.name_en}
              </span>
            </Link>
          ) : (
            <span />
          )}
        </div>
      </section>
    </>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="max-w-content mx-auto px-6 pb-10">
      <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}

function GateRow({
  label,
  pass,
  actual,
}: {
  label: string;
  pass: boolean | null;
  actual: string;
}) {
  const icon = pass === null ? "—" : pass ? "✓" : "✗";
  const color =
    pass === null ? "var(--text-tertiary)" : pass ? "var(--green)" : "var(--red)";
  return (
    <li className="flex items-center justify-between gap-3 text-sm">
      <span className="text-[var(--text-secondary)]">{label}</span>
      <span className="flex items-center gap-3">
        <span className="text-[var(--text-tertiary)]">{actual}</span>
        <span className="w-4 text-right" style={{ color }}>
          {icon}
        </span>
      </span>
    </li>
  );
}

function InfoKV({ k, v }: { k: string; v: string }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-[0.2em] text-[var(--text-tertiary)]">{k}</dt>
      <dd className="text-[var(--text-secondary)] mt-0.5">{v}</dd>
    </div>
  );
}
