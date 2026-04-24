import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { GaugeRing } from "@/components/viz/GaugeRing";
import { FactorLibrary } from "@/components/research/FactorLibrary";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
  TextLink,
} from "@/components/layout/Primitives";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtNum } from "@/lib/formatters";
import { FACTOR_CATEGORIES, type FactorCategory } from "@/lib/constants";
import type {
  CategoriesFile,
  FactorDetailsFile,
  FactorIndex,
  HeroFactorsFile,
} from "@/lib/types";

const CATEGORY_KEYS = Object.keys(FACTOR_CATEGORIES) as FactorCategory[];

export default async function ResearchPage() {
  const [index, heroes, cats, details] = await Promise.all([
    readData<FactorIndex>("factors/index.json"),
    readData<HeroFactorsFile>("factors/hero.json"),
    readDataOrNull<CategoriesFile>("categories.json"),
    readDataOrNull<FactorDetailsFile>("factors/details.json"),
  ]);

  const coreHeroes = heroes.factors.filter((f) => f.tier === "core");
  const expHeroes = heroes.factors.filter((f) => f.tier === "experimental");

  const intros: Record<string, string> = {};
  if (details?.factors) {
    for (const [name, d] of Object.entries(details.factors)) {
      if (d.intuition) intros[name] = d.intuition;
    }
  }

  return (
    <>
      <PageHeader
        eyebrow="Research"
        title="Factor funnel"
        subtitle={`${index.total} scanned · ${index.with_ic_stats} with IC stats · ${heroes.factors.length} deep dives`}
        description="The factor page is an index first. Summary cards show coverage; categories and selected factors open on demand."
        crumbs={[{ label: "Home", href: "/" }, { label: "Research" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard
            tone="blue"
            label="Scanned"
            value={String(index.total)}
            detail="all registered alpha functions"
          />
          <EvidenceCard
            tone="green"
            label="With stats"
            value={String(index.with_ic_stats)}
            detail="IC / ICIR / Fama-MacBeth available"
          />
          <EvidenceCard
            tone="gold"
            label="Deep dives"
            value={String(heroes.factors.length)}
            detail="quintile, decay, and factor page"
          />
          <EvidenceCard
            tone="red"
            label="Not promoted"
            value={String(Math.max(index.total - heroes.factors.length, 0))}
            detail="kept as ablation context"
          />
        </div>
      </section>

      {cats && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <SectionLabel
            eyebrow="Categories"
            title="Open by question, not by page length"
            body="Each category page carries intuition, A-share specifics, representative factors, and pitfalls."
          />
          <DisclosurePanel
            tone="blue"
            title="Browse 7 factor categories"
            summary="Technical, fundamental, microstructure, behavioral, chip, liquidity, and extended factors."
          >
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3">
              {CATEGORY_KEYS.map((key) => {
                const meta = cats.categories[key];
                const count = index.by_category_counts[key] ?? 0;
                if (!meta) return null;
                return (
                  <Link
                    key={key}
                    href={`/research/category/${key}`}
                    className="group block rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/35 p-4 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-surface)]/60"
                  >
                    <div className="mb-2 flex items-baseline justify-between gap-2">
                      <CategoryBadge category={key} />
                      <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                        {count} factors
                      </span>
                    </div>
                    <h3 className="mb-1 text-sm font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
                      {meta.label_zh} · {meta.label_en}
                    </h3>
                    <p className="text-xs leading-relaxed text-[var(--text-secondary)]">
                      {meta.one_liner}
                    </p>
                  </Link>
                );
              })}
            </div>
          </DisclosurePanel>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow="Selected factors"
          title="Deep dives"
          body="The cards are entry points. The full evidence sits in each factor page."
        />
        <div className="space-y-3">
          <DisclosurePanel
            tone="green"
            title="Core set"
            summary="Classic momentum, value, quality, and low-volatility baselines."
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {coreHeroes.map((h) => (
                <HeroCard key={h.name} hero={h} />
              ))}
            </div>
          </DisclosurePanel>
          <DisclosurePanel
            tone="gold"
            title="Experimental set"
            summary="Behavioral, liquidity, and structural variants kept separate from textbook baselines."
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {expHeroes.map((h) => (
                <HeroCard key={h.name} hero={h} />
              ))}
            </div>
          </DisclosurePanel>
          <DisclosurePanel
            tone="green"
            title="Event-driven track"
            summary="Corporate-action and order-flow event tests live outside the cross-sectional factor library."
          >
            <p>
              Event-driven strategies are tracked as pre-registered trials with
              separate gates, equity curves, and paper-trade specs.
            </p>
            <div className="mt-3">
              <TextLink href="/research/event-driven">Open event-driven research</TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="mb-6">
          <SectionLabel
            eyebrow="Full library"
            title={`${index.total} factors`}
            body="Filter, search, sort, then click into detail only when needed."
          />
        </div>
        <FactorLibrary
          index={index}
          heroSlugs={new Set(heroes.factors.map((h) => h.name))}
          intros={intros}
        />
      </section>
    </>
  );
}

function HeroCard({ hero }: { hero: HeroFactorsFile["factors"][number] }) {
  return (
    <Link
      href={`/research/${hero.name}`}
      className="group block p-5 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
    >
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <CategoryBadge category={hero.category} />
            <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
              {hero.tier === "core" ? "Core" : "Experimental"}
            </span>
          </div>
          <h3 className="text-lg font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)] transition-colors">
            {hero.title_en}
          </h3>
          <p className="text-xs font-mono text-[var(--text-tertiary)] mt-0.5">
            {hero.name} · {hero.title_zh}
          </p>
          <p className="mt-3 text-sm text-[var(--text-secondary)] leading-relaxed">
            {hero.pitch}
          </p>
          <div className="mt-3 flex flex-wrap gap-3 text-[11px] font-mono text-[var(--text-tertiary)]">
            <span>IC={fmtNum(hero.ic_mean, 3)}</span>
            <span>FM t={fmtNum(hero.fm_t_stat, 2)}</span>
            {hero.verdict && (
              <span className="text-[var(--green)]">{hero.verdict}</span>
            )}
            {hero.in_v7 && <span className="text-[var(--purple)]">v7</span>}
            {hero.in_v16 && <span className="text-[var(--blue)]">v16</span>}
          </div>
        </div>
        <GaugeRing value={hero.icir} label="ICIR" size={88} />
      </div>
    </Link>
  );
}
