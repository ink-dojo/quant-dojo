import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/PageHeader";
import { readData } from "@/lib/data";
import type {
  StrategyTimelineFile,
  TimelineEra,
  TimelineVersion,
  TimelineVersionStatus,
} from "@/lib/types";

interface PageParams {
  params: { version: string };
}

const STATUS_STYLE: Record<
  TimelineVersionStatus,
  { label: string; color: string; bg: string }
> = {
  legacy: { label: "Legacy", color: "var(--text-tertiary)", bg: "rgba(148,163,184,0.12)" },
  production: { label: "Production", color: "var(--green)", bg: "rgba(34,197,94,0.12)" },
  rejected: { label: "Rejected", color: "var(--red)", bg: "rgba(239,68,68,0.1)" },
  "mining-round": { label: "Mining Round", color: "var(--gold)", bg: "rgba(234,179,8,0.12)" },
  candidate: { label: "Candidate", color: "var(--gold)", bg: "rgba(234,179,8,0.12)" },
  active: { label: "Active", color: "var(--purple)", bg: "rgba(168,85,247,0.12)" },
};

function flattenVersions(
  timeline: StrategyTimelineFile,
): { era: TimelineEra; version: TimelineVersion }[] {
  const out: { era: TimelineEra; version: TimelineVersion }[] = [];
  for (const era of timeline.eras) {
    for (const v of era.versions) {
      out.push({ era, version: v });
    }
  }
  return out;
}

export async function generateStaticParams(): Promise<{ version: string }[]> {
  const timeline = await readData<StrategyTimelineFile>("strategy/timeline.json");
  return flattenVersions(timeline).map(({ version }) => ({ version: version.id }));
}

export async function generateMetadata({
  params,
}: PageParams): Promise<Metadata> {
  const timeline = await readData<StrategyTimelineFile>("strategy/timeline.json");
  const match = flattenVersions(timeline).find(
    (x) => x.version.id === decodeURIComponent(params.version),
  );
  if (!match) return { title: "Version not found" };
  const { version } = match;
  return {
    title: `${version.name_en} · QuantDojo`,
    description: version.motivation.slice(0, 160),
  };
}

export default async function VersionDetailPage({ params }: PageParams) {
  const timeline = await readData<StrategyTimelineFile>("strategy/timeline.json");
  const flat = flattenVersions(timeline);
  const id = decodeURIComponent(params.version);
  const idx = flat.findIndex((x) => x.version.id === id);
  if (idx < 0) notFound();

  const { era, version } = flat[idx]!;
  const prev = idx > 0 ? flat[idx - 1] : null;
  const next = idx < flat.length - 1 ? flat[idx + 1] : null;
  const style = STATUS_STYLE[version.status];

  return (
    <>
      <PageHeader
        eyebrow={`Strategy · Multi-Factor · ${era.era_label}`}
        title={version.name_en}
        subtitle={`${version.id} · ${version.name_zh}`}
        description={version.motivation}
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Strategy", href: "/strategy" },
          { label: "Multi-Factor", href: "/strategy/multi-factor" },
          { label: version.id },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-8">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span
            className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
            style={{ color: style.color, background: style.bg }}
          >
            {style.label}
          </span>
          <span className="font-mono text-[var(--text-tertiary)]">{version.date}</span>
          <span className="font-mono text-[var(--text-tertiary)] ml-auto">{era.era_label}</span>
        </div>
      </section>

      <Section title="Motivation · 动机">
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {version.motivation}
        </p>
      </Section>

      <Section title="Method · 方法">
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {version.method}
        </p>
      </Section>

      <Section title="Result · 结果">
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {version.result}
        </p>
      </Section>

      {version.lessons.length > 0 && (
        <Section title="Lessons · 教训">
          <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1.5">
            {version.lessons.map((l, i) => (
              <li key={i}>{l}</li>
            ))}
          </ul>
        </Section>
      )}

      {version.next_trigger && (
        <Section title="Next Trigger · 触发下一版本的原因">
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {version.next_trigger}
          </p>
        </Section>
      )}

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="flex justify-between items-center gap-4 pt-8 border-t border-[var(--border-soft)]">
          {prev ? (
            <Link
              href={`/strategy/multi-factor/${encodeURIComponent(prev.version.id)}`}
              className="group flex flex-col gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                ← Prev
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
                {prev.version.name_en}
              </span>
            </Link>
          ) : (
            <span />
          )}
          <Link
            href="/strategy/multi-factor"
            className="text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--text-primary)] shrink-0"
          >
            All versions →
          </Link>
          {next ? (
            <Link
              href={`/strategy/multi-factor/${encodeURIComponent(next.version.id)}`}
              className="group flex flex-col items-end gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                Next →
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
                {next.version.name_en}
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
    <section className="max-w-content mx-auto px-6 pb-8">
      <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
        {title}
      </h2>
      {children}
    </section>
  );
}
