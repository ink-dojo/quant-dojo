import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { GaugeRing } from "@/components/viz/GaugeRing";
import { FactorLibrary } from "@/components/research/FactorLibrary";
import { readData } from "@/lib/data";
import { fmtNum } from "@/lib/formatters";
import type {
  FactorIndex,
  HeroFactorsFile,
} from "@/lib/types";

export default async function ResearchPage() {
  const [index, heroes] = await Promise.all([
    readData<FactorIndex>("factors/index.json"),
    readData<HeroFactorsFile>("factors/hero.json"),
  ]);

  const coreHeroes = heroes.factors.filter((f) => f.tier === "core");
  const expHeroes = heroes.factors.filter((f) => f.tier === "experimental");

  return (
    <>
      <PageHeader
        eyebrow="Research · 研究"
        title="Alpha Factor Library"
        subtitle={`${index.total} 因子 · ${index.with_ic_stats} 带 IC 统计 · ${heroes.factors.length} 深度研究`}
        description="From textbook factors to behavioral-finance experiments. Every factor tested with IC, ICIR, Fama-MacBeth t-stat; quintile backtests and decay analysis for the 8 hero cases."
        crumbs={[{ label: "Home", href: "/" }, { label: "Research" }]}
      />

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
