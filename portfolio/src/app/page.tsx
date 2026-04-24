import Link from "next/link";
import { SITE, projectWeek } from "@/lib/constants";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
  StatusPill,
  TextLink,
} from "@/components/layout/Primitives";
import type {
  EquityCurveFile,
  FactorIndex,
  Meta,
  PaperTradeState,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function Home() {
  const [meta, index, versions, paper] = await Promise.all([
    readData<Meta>("meta.json"),
    readData<FactorIndex>("factors/index.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
    readDataOrNull<PaperTradeState>("paper_trade/state.json"),
  ]);

  const { week, dateStr } = projectWeek();
  const face = versions.versions.find((v) => v.id === versions.production_face);
  const candidate = versions.versions.find((v) => v.id === versions.candidate);
  const rejected = versions.versions.find((v) => v.status === "rejected");

  const curveIds = [face, rejected, candidate]
    .filter((v): v is NonNullable<typeof v> => Boolean(v?.equity_file))
    .map((v) => ({ id: v.id, file: v.equity_file!, status: v.status, name: v.name_zh }));

  const curves = await Promise.all(
    curveIds.map(async (c) => ({
      ...c,
      curve: await readDataOrNull<EquityCurveFile>(`strategy/${c.file}`),
    }))
  );

  const seriesColor: Record<string, string> = {
    v9: "var(--green)",
    v10: "var(--red)",
    v16: "var(--gold)",
    v25: "var(--gold)",
  };

  const series = curves
    .filter((c) => c.curve !== null)
    .map((c) => ({
      id: c.id,
      label: `${c.id} · ${c.name}`,
      color: seriesColor[c.id] ?? "var(--cyan)",
      dashed: c.status === "rejected" || c.status === "candidate",
      curve: c.curve!,
    }));

  return (
    <div className="max-w-content mx-auto px-6">
      <section className="pt-20 pb-12">
        <div className="mb-8 flex flex-wrap items-center gap-2">
          <StatusPill tone="blue">Week {week}</StatusPill>
          <StatusPill tone="neutral">{dateStr}</StatusPill>
          <StatusPill tone={paper?.enabled ? "green" : "gold"}>
            {paper?.enabled ? "paper-trade running" : "paper-trade unavailable"}
          </StatusPill>
        </div>

        <h1 className="max-w-4xl text-4xl font-semibold tracking-[-0.035em] text-[var(--text-primary)] md:text-6xl">
          A research ledger for A-share strategies.
        </h1>
        <p className="mt-6 max-w-2xl text-base leading-relaxed text-[var(--text-secondary)] md:text-lg">
          A-share strategy workbench with pre-registered tests, rejection records,
          paper-trade state, and source-linked evidence. The default view shows
          status; details stay one click away.
        </p>
      </section>

      <section className="pb-16">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard
            tone={paper?.kill.action === "ok" ? "green" : paper ? "gold" : "neutral"}
            label="Paper trade"
            value={paper ? paper.strategy_id?.replace(/_/g, " ") ?? "active" : "No snapshot"}
            detail={
              paper
                ? `spec ${paper.spec_version} · Day ${paper.kill.running_days} · risk ${paper.kill.action.toUpperCase()}`
                : "Waiting for exported EOD state"
            }
            href="/live"
          />
          <EvidenceCard
            tone="blue"
            label="Factor library"
            value={`${index.total} scanned`}
            detail={`${index.with_ic_stats} with IC stats · ${index.with_research_folder} research folders`}
            href="/research"
          />
          <EvidenceCard
            tone="green"
            label="Research face"
            value={face?.id ?? versions.production_face}
            detail={
              face?.metrics
                ? `Sharpe ${fmtNum(face.metrics.sharpe, 2)} · DD ${fmtPct(face.metrics.max_drawdown, 1)}`
                : "WF-validated multi-factor line"
            }
            href="/strategy"
          />
          <EvidenceCard
            tone="red"
            label="Latest hard reject"
            value="RIAD combo"
            detail="Executable universe broke the baseline result; keep BB-only live."
            href="/validation"
          />
        </div>
      </section>

      <section className="pb-16">
        <SectionLabel
          eyebrow="Current map"
          title="What is running, what is research, what is blocked"
          body="The site now separates operational state from research artifacts. Open the row if you need the reasoning or source path."
        />
        <div className="space-y-3">
          <DisclosurePanel
            tone="green"
            title="Running: DSR #30 BB-only paper-trade"
            summary={
              paper
                ? `NAV ${fmtNum(paper.last_nav, 0)} · Cum ${fmtPct(paper.cum_return, 2)} · ${paper.positions.length} positions`
                : "No exported paper-trade snapshot found."
            }
          >
            <p>
              This is the only operational paper-trade line shown as running.
              It uses spec v3 BB-only with 5% simulated capital. The live page
              carries the ledger snapshot, kill switch state, positions, and
              daily trade summary.
            </p>
            <div className="mt-3">
              <TextLink href="/live">Open live state</TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="blue"
            title="Research: factor library and multi-factor versions"
            summary={`${index.total} factor candidates, ${index.with_ic_stats} with statistics, ${face?.id ?? "v9"} as the multi-factor research face.`}
          >
            <p>
              Multi-factor versions are research artifacts unless explicitly
              marked as paper-trade. The useful record is the sequence of
              gates: v9 survives walk-forward, v10 fails OOS, and mining
              candidates remain candidates until validated.
            </p>
            <div className="mt-3 flex flex-wrap gap-3">
              <TextLink href="/research">Open factor library</TextLink>
              <TextLink href="/strategy">Open strategy versions</TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="red"
            title="Blocked: RIAD + DSR #30 combo"
            summary="Baseline backtest looked good; executable constraints did not."
          >
            <p>
              The combo is not presented as running. The issue is not the
              headline Sharpe; it is the gap between baseline construction and
              executable short/universe constraints. Validation keeps this as a
              case file, not a promotion story.
            </p>
            <div className="mt-3">
              <TextLink href="/validation">Open rejection file</TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      {series.length > 0 && (
        <section className="pb-16">
          <SectionLabel
            eyebrow="Optional detail"
            title="Equity curves are supporting evidence"
            body="Charts are useful after the status is clear. They are no longer the hero of the page."
          />
          <DisclosurePanel
            tone="neutral"
            title="Open multi-factor equity overlay"
            summary="v9 face, rejected stop-loss variant, and current candidate on one axis."
          >
            <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/40 p-4">
              <EquityChart series={series} height={380} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              {face && (
                <MiniNote
                  tone="green"
                  label={`${face.id} · research face`}
                  body="Walk-forward survived. This is a research benchmark, not the current paper-trade line."
                />
              )}
              {rejected && (
                <MiniNote
                  tone="red"
                  label={`${rejected.id} · rejected`}
                  body="The stop-loss layer improved one view of drawdown and damaged OOS behavior."
                />
              )}
              {candidate && (
                <MiniNote
                  tone="gold"
                  label={`${candidate.id} · candidate`}
                  body="Kept visible because it is tempting, not because it is approved."
                />
              )}
            </div>
          </DisclosurePanel>
        </section>
      )}

      <section className="pb-20">
        <SectionLabel
          eyebrow="Reading path"
          title="Start broad. Open only what you need."
        />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <PathCard href="/live" n="01" title="Live" body="Current paper-trade state, risk action, positions, and daily summary." />
          <PathCard href="/validation" n="02" title="Validation" body="Case files for rejected strategies, killed factors, and blocked specs." />
          <PathCard href="/research" n="03" title="Research" body="Factor library, category filter, and deep dives for selected factors." />
          <PathCard href="/strategy" n="04" title="Strategy" body="Multi-factor versions, gates, candidates, and equity overlays." />
          <PathCard href="/journey" n="05" title="Journey" body="Chronological project record with scope, output, and lessons." />
          <PathCard href="/infrastructure" n="06" title="Infra" body="Actual repo layers, data export path, and build metadata." />
        </div>
      </section>

      <footer className="border-t border-[var(--border-soft)] py-8 text-[11px] font-mono text-[var(--text-tertiary)]">
        <div className="flex flex-wrap justify-between gap-3">
          <span>{SITE.title} · started {SITE.started_at}</span>
          <span>build {meta.git.short ?? "dirty"} · {meta.git.subject}</span>
          <span>data {meta.coverage_generated_at.slice(0, 10)}</span>
        </div>
      </footer>
    </div>
  );
}

function PathCard({
  href,
  n,
  title,
  body,
}: {
  href: string;
  n: string;
  title: string;
  body: string;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/28 p-4 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-surface)]/50"
    >
      <p className="mb-4 text-[10px] font-mono text-[var(--text-tertiary)]">{n}</p>
      <h3 className="text-base font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
        {title}
      </h3>
      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">{body}</p>
    </Link>
  );
}

function MiniNote({
  tone,
  label,
  body,
}: {
  tone: "green" | "red" | "gold";
  label: string;
  body: string;
}) {
  const color =
    tone === "green" ? "var(--green)" : tone === "red" ? "var(--red)" : "var(--gold)";
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 p-3">
      <p className="text-[10px] font-mono uppercase tracking-[0.14em]" style={{ color }}>
        {label}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">{body}</p>
    </div>
  );
}
