import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { GaugeRing } from "@/components/viz/GaugeRing";
import { FactorLibrary } from "@/components/research/FactorLibrary";
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
        eyebrow="Research · Week 3-6"
        title="Alpha Factor Library"
        subtitle={`${index.total} 因子 · ${index.with_ic_stats} 带 IC 统计 · ${heroes.factors.length} 带深度分析`}
        description={`66 factor 扫 IC 三件套 (IC / ICIR / Fama-MacBeth t-stat), 18 个过 t-stat 门, 8 个做分层 / 衰减 / 中性化深度分析. 48 个被筛掉 — 那些也留在库里作 ablation 对照.`}
        crumbs={[{ label: "Home", href: "/" }, { label: "Research" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <Link
          href="/research/event-driven"
          className="block rounded-lg border border-[var(--green)]/35 bg-[var(--green)]/[0.05] p-5 hover:bg-[var(--green)]/[0.08] transition-colors"
        >
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--green)]">
              Event-driven · Week 4-6
            </span>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">31 pre-reg trials</span>
          </div>
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-1">
            50/50 ensemble of BB × LHB contrarian — 5/5 admission gate pass
          </h3>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            两个 4/5 候选（回购 drift + 龙虎榜跌幅 contrarian）失败模式正交，相关
            0.37，等权 ensemble 过 5 gate：ann 41.96% · SR 2.47 · MDD -26.78% · CI_low 1.17。
            <span className="text-[var(--green)] ml-1">查看完整 DSR penalty bookkeeping →</span>
          </p>
        </Link>
      </section>

      {cats && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Categories · 因子分类
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-6">
            7 大类别 — 每类都附经济直觉、A 股特点、代表因子、常见陷阱。点击进入类别总览。
          </p>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
            {CATEGORY_KEYS.map((key) => {
              const meta = cats.categories[key];
              const count = index.by_category_counts[key] ?? 0;
              if (!meta) return null;
              return (
                <Link
                  key={key}
                  href={`/research/category/${key}`}
                  className="group block p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
                >
                  <div className="flex items-baseline justify-between gap-2 mb-2">
                    <CategoryBadge category={key} />
                    <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                      {count} factors
                    </span>
                  </div>
                  <h3 className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)] mb-1">
                    {meta.label_zh} · {meta.label_en}
                  </h3>
                  <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
                    {meta.one_liner}
                  </p>
                </Link>
              );
            })}
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Core 4 — 教材门槛
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          经典动量 / 价值 / 质量 / 低波动 — 其中 ROE 是诚实证伪案例。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {coreHeroes.map((h) => (
            <HeroCard key={h.name} hero={h} />
          ))}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Experimental 4 — 超越教材
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          自研行为金融 / 流动性 / 结构化动量 — 包含全库 ICIR 最高的 team_coin。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {expHeroes.map((h) => (
            <HeroCard key={h.name} hero={h} />
          ))}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="mb-6">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Full Library · {index.total}
          </h2>
          <p className="text-sm text-[var(--text-secondary)]">
            全部因子一览 — {index.with_ic_stats} 个带完整 IC 统计，{index.with_research_folder}{" "}
            个有独立研究文件夹。按分类过滤、按 ICIR 排序、或搜名称/描述。
            英雄因子可点击进入深度页。
          </p>
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
