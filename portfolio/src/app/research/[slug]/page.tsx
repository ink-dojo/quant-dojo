import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/PageHeader";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { GaugeRing } from "@/components/viz/GaugeRing";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { ICTrendChart } from "@/components/viz/ICTrendChart";
import { DecayChart } from "@/components/viz/DecayChart";
import { QuintileChart } from "@/components/viz/QuintileChart";
import { FormulaDisplay } from "@/components/viz/FormulaDisplay";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import { FACTOR_CATEGORIES } from "@/lib/constants";
import type {
  FactorDetailsFile,
  FactorIndex,
  FactorIndexItem,
  FactorLinenoFile,
  HeroDetailFile,
  HeroFactor,
  HeroFactorsFile,
} from "@/lib/types";

interface PageParams {
  params: { slug: string };
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  const index = await readData<FactorIndex>("factors/index.json");
  return index.factors.map((f) => ({ slug: f.name }));
}

export async function generateMetadata({
  params,
}: PageParams): Promise<Metadata> {
  const [heroes, index] = await Promise.all([
    readData<HeroFactorsFile>("factors/hero.json"),
    readData<FactorIndex>("factors/index.json"),
  ]);
  const hero = heroes.factors.find((h) => h.name === params.slug);
  if (hero) {
    return {
      title: `${hero.title_en} · QuantDojo`,
      description: hero.pitch,
    };
  }
  const item = index.factors.find((f) => f.name === params.slug);
  if (!item) return { title: "Factor not found" };
  return {
    title: `${item.name} · QuantDojo`,
    description: item.docstring.slice(0, 160),
  };
}

export default async function FactorDetailPage({ params }: PageParams) {
  const [heroes, index, details, lineno, heroDetail] = await Promise.all([
    readData<HeroFactorsFile>("factors/hero.json"),
    readData<FactorIndex>("factors/index.json"),
    readDataOrNull<FactorDetailsFile>("factors/details.json"),
    readDataOrNull<FactorLinenoFile>("factors/lineno.json"),
    readDataOrNull<HeroDetailFile>("factors/hero_detail.json"),
  ]);

  const slug = params.slug;
  const hero = heroes.factors.find((h) => h.name === slug) ?? null;
  const item = index.factors.find((f) => f.name === slug) ?? null;

  if (!hero && !item) notFound();

  const detail = details?.details?.[slug];
  const lineNumber = lineno?.lineno?.[slug] ?? hero?.lineno ?? null;

  const sortedIdx = [...index.factors].sort((a, b) => a.name.localeCompare(b.name));
  const pos = sortedIdx.findIndex((f) => f.name === slug);
  const prev = pos > 0 ? sortedIdx[pos - 1] : null;
  const next = pos < sortedIdx.length - 1 ? sortedIdx[pos + 1] : null;

  if (hero) {
    return (
      <HeroFactorView
        hero={hero}
        heroDetail={heroDetail}
        detail={detail ?? null}
        lineNumber={lineNumber}
        prev={prev}
        next={next}
      />
    );
  }

  return (
    <LibraryFactorView
      item={item!}
      detail={detail ?? null}
      lineNumber={lineNumber}
      prev={prev}
      next={next}
    />
  );
}

function HeroFactorView({
  hero,
  heroDetail,
  detail,
  lineNumber,
  prev,
  next,
}: {
  hero: HeroFactor;
  heroDetail: HeroDetailFile | null;
  detail: FactorDetailsFile["details"][string] | null;
  lineNumber: number | null;
  prev: FactorIndexItem | null;
  next: FactorIndexItem | null;
}) {
  const entry = heroDetail?.factors?.[hero.name];
  const hasDeepData =
    entry !== undefined &&
    !("error" in entry && entry.error) &&
    entry?.ic?.summary.n !== undefined &&
    entry.ic.summary.n > 0;

  const icSummary = entry?.ic?.summary;
  const monthly = entry?.ic?.monthly ?? [];
  const decay = entry?.decay;
  const quintile = entry?.quintile;

  return (
    <>
      <PageHeader
        eyebrow={`Research · ${hero.tier === "core" ? "Core 4" : "Experimental 4"}`}
        title={hero.title_en}
        subtitle={`${hero.name} · ${hero.title_zh}`}
        description={hero.pitch}
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: hero.name },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <CategoryBadge category={hero.category} />
          <Link
            href={`/research/category/${hero.category}`}
            className="text-[10px] font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)]"
          >
            → category overview
          </Link>
          <span className="font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
            {hero.tier}
          </span>
          {hero.verdict && (
            <span
              className="font-mono px-2 py-0.5 rounded"
              style={{ color: "var(--green)", background: "rgba(34,197,94,0.1)" }}
            >
              {hero.verdict}
            </span>
          )}
          {hero.in_v7 && <span className="font-mono text-[var(--purple)]">in v7</span>}
          {hero.in_v16 && <span className="font-mono text-[var(--blue)]">in v16</span>}
          {lineNumber !== null && (
            <span className="font-mono text-[var(--text-tertiary)] ml-auto">
              utils/alpha_factors.py:{lineNumber}
            </span>
          )}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12 grid grid-cols-1 lg:grid-cols-[1fr_auto] gap-8 items-start">
        <div className="min-w-0 space-y-4">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            Docstring
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
            {hero.docstring}
          </p>
          {detail?.formula_latex && (
            <>
              <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] pt-4">
                Formula
              </h2>
              <FormulaDisplay
                latex={detail.formula_latex}
                caption={detail.formula_caption ?? undefined}
              />
            </>
          )}
          {detail && <EncyclopediaBlocks detail={detail} />}
        </div>
        <div className="shrink-0 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <GaugeRing
            value={hero.icir}
            label="ICIR"
            sublabel={`IC ${fmtNum(hero.ic_mean, 3)}`}
            size={140}
          />
        </div>
      </section>

      {hasDeepData && icSummary && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
            IC Summary · {heroDetail?.window.analysis_start} → {heroDetail?.window.analysis_end}
          </h2>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <MetricGrid
              metrics={[
                {
                  label: "IC Mean",
                  value: fmtNum(icSummary.ic_mean, 4),
                  tone:
                    icSummary.ic_mean !== null && Math.abs(icSummary.ic_mean) >= 0.03
                      ? "good"
                      : "neutral",
                },
                {
                  label: "ICIR",
                  value: fmtNum(icSummary.icir, 3),
                  tone:
                    icSummary.icir !== null && Math.abs(icSummary.icir) >= 0.3
                      ? "good"
                      : "warn",
                },
                {
                  label: "Fama-MacBeth t",
                  value: fmtNum(icSummary.t_stat, 2),
                  tone:
                    icSummary.t_stat !== null && Math.abs(icSummary.t_stat) >= 2
                      ? "good"
                      : "warn",
                },
                {
                  label: "IC>0 Days",
                  value: fmtPct(icSummary.pct_pos, 1),
                  tone: "neutral",
                  hint: `${icSummary.n} days`,
                },
              ]}
            />
          </div>
        </section>
      )}

      {hasDeepData && monthly.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            IC Trend — Monthly
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            {monthly.length} 个月度 IC 点。持续在零线之上 → 单调预测性；来回穿越 → regime 切换或噪声。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <ICTrendChart points={monthly} factorName={hero.name} />
          </div>
        </section>
      )}

      {hasDeepData && decay && decay.ic_by_lag.some((d) => d.ic !== null) && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Factor Decay · fwd 1d → 20d
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            因子 IC 随持有期衰减速度。半衰期{" "}
            {decay.half_life_days !== null
              ? `t½ ≈ ${decay.half_life_days.toFixed(1)} 天`
              : "无法拟合"}{" "}
            · 推荐调仓周期 {decay.recommended_rebalance_freq}。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <DecayChart decay={decay} />
          </div>
        </section>
      )}

      {hasDeepData && quintile && quintile.cum_monthly.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Quintile Backtest
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            按因子值 5 分组累计收益。理想的单调因子：Q1 - Q5 逐层递进。long-short = {quintile.direction}.
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <QuintileChart points={quintile.cum_monthly} />
          </div>
          <div className="mt-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <MetricGrid
              metrics={[
                {
                  label: "LS Ann Return",
                  value: fmtPct(quintile.ls_stats.ann_return ?? null, 1),
                  tone: (quintile.ls_stats.ann_return ?? 0) > 0 ? "good" : "bad",
                },
                {
                  label: "LS Sharpe",
                  value: fmtNum(quintile.ls_stats.sharpe ?? null, 2),
                  tone:
                    quintile.ls_stats.sharpe !== null &&
                    quintile.ls_stats.sharpe !== undefined &&
                    quintile.ls_stats.sharpe >= 0.8
                      ? "good"
                      : "warn",
                },
                {
                  label: "LS Max DD",
                  value: fmtPct(quintile.ls_stats.max_drawdown ?? null, 1),
                  tone: "bad",
                },
                {
                  label: "N Days",
                  value: String(quintile.ls_stats.n_days ?? "—"),
                  tone: "neutral",
                },
              ]}
            />
          </div>
        </section>
      )}

      {!hasDeepData && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <div className="rounded-lg border border-dashed border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-8 text-center">
            <p className="text-sm font-mono text-[var(--text-tertiary)]">
              深度分析暂无数据（n=0） — 该因子在 2020-2024 分析窗口构建失败
            </p>
            <p className="text-xs text-[var(--text-tertiary)] mt-2">
              scripts/deep_analysis_hero_factors.py · {hero.name}
            </p>
          </div>
        </section>
      )}

      <FactorNav prev={prev} next={next} />
    </>
  );
}

function LibraryFactorView({
  item,
  detail,
  lineNumber,
  prev,
  next,
}: {
  item: FactorIndexItem;
  detail: FactorDetailsFile["details"][string] | null;
  lineNumber: number | null;
  prev: FactorIndexItem | null;
  next: FactorIndexItem | null;
}) {
  const catLabel = FACTOR_CATEGORIES[item.category]?.label ?? item.category;
  const subtitle = detail?.intuition
    ? `${item.name} · ${catLabel}`
    : `${item.name} · ${catLabel}`;

  return (
    <>
      <PageHeader
        eyebrow="Research · Full Library"
        title={item.name}
        subtitle={subtitle}
        description={item.docstring.split("\n")[0] ?? item.docstring}
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: item.name },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-8">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <CategoryBadge category={item.category} />
          <Link
            href={`/research/category/${item.category}`}
            className="text-[10px] font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)]"
          >
            → category overview
          </Link>
          {item.verdict && (
            <span className="font-mono text-[var(--text-tertiary)]">{item.verdict}</span>
          )}
          {item.in_v7 && <span className="font-mono text-[var(--purple)]">in v7</span>}
          {item.in_v16 && <span className="font-mono text-[var(--blue)]">in v16</span>}
          {lineNumber !== null && (
            <span className="font-mono text-[var(--text-tertiary)] ml-auto">
              utils/alpha_factors.py:{lineNumber}
            </span>
          )}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <MetricGrid
            metrics={[
              {
                label: "IC Mean",
                value: fmtNum(item.ic_mean, 4),
                tone:
                  item.ic_mean !== null && Math.abs(item.ic_mean) >= 0.03
                    ? "good"
                    : "neutral",
              },
              {
                label: "ICIR",
                value: fmtNum(item.icir, 3),
                tone:
                  item.icir !== null && Math.abs(item.icir) >= 0.3 ? "good" : "warn",
              },
              {
                label: "FM t-stat",
                value: fmtNum(item.fm_t_stat, 2),
                tone:
                  item.fm_t_stat !== null && Math.abs(item.fm_t_stat) >= 2
                    ? "good"
                    : "warn",
              },
              {
                label: "Coverage",
                value: `${item.coverage_score}/4`,
                tone: item.coverage_score >= 3 ? "good" : "neutral",
              },
            ]}
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-10 space-y-6">
        <div>
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
            Docstring
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed whitespace-pre-wrap">
            {item.docstring}
          </p>
        </div>

        {detail?.formula_latex && (
          <div>
            <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
              Formula
            </h2>
            <FormulaDisplay
              latex={detail.formula_latex}
              caption={detail.formula_caption ?? undefined}
            />
          </div>
        )}

        {detail ? (
          <EncyclopediaBlocks detail={detail} />
        ) : (
          <div className="rounded-lg border border-dashed border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <p className="text-xs font-mono text-[var(--text-tertiary)]">
              encyclopedia entry not yet written · factors/details.json does not contain {item.name}
            </p>
          </div>
        )}
      </section>

      <FactorNav prev={prev} next={next} />
    </>
  );
}

function EncyclopediaBlocks({
  detail,
}: {
  detail: FactorDetailsFile["details"][string];
}) {
  return (
    <div className="space-y-6">
      {detail.intuition && (
        <div>
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Intuition · 直觉
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {detail.intuition}
          </p>
        </div>
      )}
      {detail.a_share && (
        <div>
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            A-Share Context · A 股特点
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {detail.a_share}
          </p>
        </div>
      )}
      {detail.pitfall && (
        <div>
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Pitfall · 坑点
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            {detail.pitfall}
          </p>
        </div>
      )}
      {detail.refs && detail.refs.length > 0 && (
        <div>
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            References
          </h2>
          <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1">
            {detail.refs.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function FactorNav({
  prev,
  next,
}: {
  prev: FactorIndexItem | null;
  next: FactorIndexItem | null;
}) {
  return (
    <section className="max-w-content mx-auto px-6 pb-24">
      <div className="flex justify-between items-center gap-4 pt-8 border-t border-[var(--border-soft)]">
        {prev ? (
          <Link
            href={`/research/${prev.name}`}
            className="group flex flex-col gap-1 min-w-0"
          >
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
              ← Prev
            </span>
            <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
              {prev.name}
            </span>
          </Link>
        ) : (
          <span />
        )}
        <Link
          href="/research"
          className="text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--text-primary)] shrink-0"
        >
          All factors →
        </Link>
        {next ? (
          <Link
            href={`/research/${next.name}`}
            className="group flex flex-col items-end gap-1 min-w-0"
          >
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
              Next →
            </span>
            <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)] truncate">
              {next.name}
            </span>
          </Link>
        ) : (
          <span />
        )}
      </div>
    </section>
  );
}
