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
import { Lang } from "@/components/layout/LanguageText";
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
        title={<Lang zh="因子漏斗" en="Factor funnel" />}
        subtitle={<Lang zh={`${index.total} 个已扫描 · ${index.with_ic_stats} 个有 IC 统计 · ${heroes.factors.length} 个深度页`} en={`${index.total} scanned · ${index.with_ic_stats} with IC stats · ${heroes.factors.length} deep dives`} />}
        description={<Lang zh="因子页先作为索引使用：摘要卡展示覆盖度，分类和精选因子按需展开。" en="The factor page is an index first. Summary cards show coverage; categories and selected factors open on demand." />}
        crumbs={[{ label: "Home", href: "/" }, { label: "Research" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard
            tone="blue"
            label={<Lang zh="已扫描" en="Scanned" />}
            value={String(index.total)}
            detail={<Lang zh="全部已注册 alpha 函数" en="all registered alpha functions" />}
          />
          <EvidenceCard
            tone="green"
            label={<Lang zh="有统计" en="With stats" />}
            value={String(index.with_ic_stats)}
            detail={<Lang zh="IC / ICIR / Fama-MacBeth 可用" en="IC / ICIR / Fama-MacBeth available" />}
          />
          <EvidenceCard
            tone="gold"
            label={<Lang zh="深度页" en="Deep dives" />}
            value={String(heroes.factors.length)}
            detail={<Lang zh="分层、衰减、因子页" en="quintile, decay, and factor page" />}
          />
          <EvidenceCard
            tone="red"
            label={<Lang zh="未晋级" en="Not promoted" />}
            value={String(Math.max(index.total - heroes.factors.length, 0))}
            detail={<Lang zh="保留作 ablation 上下文" en="kept as ablation context" />}
          />
        </div>
      </section>

      {cats && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <SectionLabel
            eyebrow={<Lang zh="分类" en="Categories" />}
            title={<Lang zh="按问题打开，而不是按页面长度阅读" en="Open by question, not by page length" />}
            body={<Lang zh="每个分类页包含经济直觉、A 股特征、代表因子和常见陷阱。" en="Each category page carries intuition, A-share specifics, representative factors, and pitfalls." />}
          />
          <DisclosurePanel
            tone="blue"
            title={<Lang zh="浏览 7 类因子" en="Browse 7 factor categories" />}
            summary={<Lang zh="技术、基本面、微观结构、行为金融、筹码、流动性和扩展因子。" en="Technical, fundamental, microstructure, behavioral, chip, liquidity, and extended factors." />}
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
          eyebrow={<Lang zh="精选因子" en="Selected factors" />}
          title={<Lang zh="深度研究" en="Deep dives" />}
          body={<Lang zh="卡片只是入口，完整证据在每个因子详情页。" en="The cards are entry points. The full evidence sits in each factor page." />}
        />
        <div className="space-y-3">
          <DisclosurePanel
            tone="green"
            title={<Lang zh="核心组" en="Core set" />}
            summary={<Lang zh="经典动量、价值、质量、低波动基线。" en="Classic momentum, value, quality, and low-volatility baselines." />}
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {coreHeroes.map((h) => (
                <HeroCard key={h.name} hero={h} />
              ))}
            </div>
          </DisclosurePanel>
          <DisclosurePanel
            tone="gold"
            title={<Lang zh="实验组" en="Experimental set" />}
            summary={<Lang zh="行为金融、流动性和结构化变体，和教材基线分开看。" en="Behavioral, liquidity, and structural variants kept separate from textbook baselines." />}
          >
            <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
              {expHeroes.map((h) => (
                <HeroCard key={h.name} hero={h} />
              ))}
            </div>
          </DisclosurePanel>
          <DisclosurePanel
            tone="green"
            title={<Lang zh="事件驱动轨道" en="Event-driven track" />}
            summary={<Lang zh="公司行为和订单流事件测试独立于截面因子库。" en="Corporate-action and order-flow event tests live outside the cross-sectional factor library." />}
          >
            <p>
              <Lang
                zh="事件驱动策略以预注册 trial 形式追踪，单独记录 gate、净值曲线和模拟盘 spec。"
                en="Event-driven strategies are tracked as pre-registered trials with separate gates, equity curves, and paper-trade specs."
              />
            </p>
            <div className="mt-3">
              <TextLink href="/research/event-driven"><Lang zh="查看事件驱动研究" en="Open event-driven research" /></TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="mb-6">
          <SectionLabel
            eyebrow={<Lang zh="完整因子库" en="Full library" />}
            title={<Lang zh={`${index.total} 个因子`} en={`${index.total} factors`} />}
            body={<Lang zh="先筛选、搜索、排序；只有需要时再进入详情。" en="Filter, search, sort, then click into detail only when needed." />}
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
