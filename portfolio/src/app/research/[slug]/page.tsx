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
import type {
  HeroDetailFile,
  HeroFactor,
  HeroFactorsFile,
} from "@/lib/types";

/**
 * Hardcoded LaTeX for the 8 hero factors. Python source code has the math
 * inline as comments — copying it here keeps the page self-contained and
 * avoids building a .py → LaTeX extractor for 8 fixed cases.
 */
const FORMULAS: Record<string, { latex: string; caption?: string }> = {
  enhanced_momentum: {
    latex:
      "F_t = \\text{rank}\\!\\left(\\frac{P_{t-21}}{P_{t-252}} - 1\\right) \\times \\text{sign}(\\text{IC}_{60d})",
    caption: "11-month momentum skipping the most recent month (reversal guard), rank-standardized",
  },
  bp_factor: {
    latex: "F_t = \\frac{\\text{Book Value}_t}{\\text{Market Cap}_t} = \\frac{1}{PB_t}",
    caption: "Book-to-price = inverse of price-to-book ratio",
  },
  low_vol_20d: {
    latex:
      "F_t = -\\,\\sigma\\!\\left(\\frac{r_{t-19}, \\ldots, r_t}{\\sqrt{20}}\\right)",
    caption: "Negative 20-day realized volatility (low-vol anomaly, higher is safer)",
  },
  roe_factor: {
    latex: "F_t = \\text{ROE}_t = \\frac{1/PE_t}{1/PB_t} = \\frac{PB_t}{PE_t}",
    caption: "Proxied ROE from PB/PE ratios — noisy proxy, honest failure case",
  },
  team_coin: {
    latex:
      "F_t = \\text{turnover}_t \\cdot \\sqrt{\\mathbb{E}[r_t^2]} \\cdot \\frac{|r_t^{20}|}{\\sigma_t^{60}}",
    caption: "Retail coordination proxy: turnover × realized vol × directional persistence",
  },
  cgo: {
    latex:
      "F_t = \\frac{P_t - \\bar{P}_t^{RP}}{P_t}, \\quad \\bar{P}_t^{RP} = \\sum_{\\tau} w_\\tau P_\\tau",
    caption: "Capital Gains Overhang — price gap vs turnover-weighted reference price",
  },
  amihud_illiquidity: {
    latex: "F_t = \\frac{1}{N}\\sum_{i=1}^{N} \\frac{|r_{t-i}|}{V_{t-i}}",
    caption: "Amihud (2002) illiquidity — average |return| / dollar volume",
  },
  momentum_6m_skip1m: {
    latex: "F_t = \\frac{P_{t-21}}{P_{t-126}} - 1",
    caption: "6-month momentum, skip most-recent month to dodge short-term reversal",
  },
};

interface PageParams {
  params: { slug: string };
}

export async function generateStaticParams(): Promise<{ slug: string }[]> {
  const heroes = await readData<HeroFactorsFile>("factors/hero.json");
  return heroes.factors.map((h) => ({ slug: h.name }));
}

export async function generateMetadata({
  params,
}: PageParams): Promise<Metadata> {
  const heroes = await readData<HeroFactorsFile>("factors/hero.json");
  const hero = heroes.factors.find((h) => h.name === params.slug);
  if (!hero) return { title: "Factor not found" };
  return {
    title: `${hero.title_en} · QuantDojo`,
    description: hero.pitch,
  };
}

export default async function HeroDetailPage({ params }: PageParams) {
  const [heroes, detail] = await Promise.all([
    readData<HeroFactorsFile>("factors/hero.json"),
    readDataOrNull<HeroDetailFile>("factors/hero_detail.json"),
  ]);

  const heroIdx = heroes.factors.findIndex((h) => h.name === params.slug);
  if (heroIdx < 0) notFound();
  const hero = heroes.factors[heroIdx]!;
  const prev = heroIdx > 0 ? heroes.factors[heroIdx - 1] : null;
  const next = heroIdx < heroes.factors.length - 1 ? heroes.factors[heroIdx + 1] : null;

  const entry = detail?.factors?.[hero.name];
  const hasDeepData =
    entry !== undefined &&
    !("error" in entry && entry.error) &&
    entry?.ic?.summary.n !== undefined &&
    entry.ic.summary.n > 0;

  const icSummary = entry?.ic?.summary;
  const monthly = entry?.ic?.monthly ?? [];
  const decay = entry?.decay;
  const quintile = entry?.quintile;
  const formula = FORMULAS[hero.name];

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
          <span className="font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
            {hero.tier}
          </span>
          {hero.verdict && (
            <span
              className="font-mono px-2 py-0.5 rounded"
              style={{
                color: "var(--green)",
                background: "rgba(34,197,94,0.1)",
              }}
            >
              {hero.verdict}
            </span>
          )}
          {hero.in_v7 && (
            <span className="font-mono text-[var(--purple)]">in v7</span>
          )}
          {hero.in_v16 && (
            <span className="font-mono text-[var(--blue)]">in v16</span>
          )}
          <span className="font-mono text-[var(--text-tertiary)] ml-auto">
            utils/alpha_factors.py:{hero.lineno}
          </span>
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
          {formula && (
            <>
              <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] pt-4">
                Formula
              </h2>
              <FormulaDisplay latex={formula.latex} caption={formula.caption} />
            </>
          )}
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
            IC Summary · {detail?.window.analysis_start} → {detail?.window.analysis_end}
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
                  tone:
                    (quintile.ls_stats.ann_return ?? 0) > 0 ? "good" : "bad",
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
                {prev.title_en}
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
                {next.title_en}
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
