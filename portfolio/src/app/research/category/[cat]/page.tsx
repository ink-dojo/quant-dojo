import Link from "next/link";
import { notFound } from "next/navigation";
import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/PageHeader";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { readData } from "@/lib/data";
import { fmtNum } from "@/lib/formatters";
import { FACTOR_CATEGORIES, type FactorCategory } from "@/lib/constants";
import type {
  CategoriesFile,
  FactorIndex,
  FactorIndexItem,
  HeroFactorsFile,
} from "@/lib/types";

interface PageParams {
  params: { cat: string };
}

const CATEGORY_KEYS = Object.keys(FACTOR_CATEGORIES) as FactorCategory[];

export function generateStaticParams(): { cat: string }[] {
  return CATEGORY_KEYS.map((cat) => ({ cat }));
}

export async function generateMetadata({
  params,
}: PageParams): Promise<Metadata> {
  const cats = await readData<CategoriesFile>("categories.json");
  const cat = cats.categories[params.cat as FactorCategory];
  if (!cat) return { title: "Category not found" };
  return {
    title: `${cat.label_en} factors · QuantDojo`,
    description: cat.one_liner,
  };
}

export default async function CategoryPage({ params }: PageParams) {
  if (!CATEGORY_KEYS.includes(params.cat as FactorCategory)) notFound();
  const cat = params.cat as FactorCategory;

  const [cats, index, heroes] = await Promise.all([
    readData<CategoriesFile>("categories.json"),
    readData<FactorIndex>("factors/index.json"),
    readData<HeroFactorsFile>("factors/hero.json"),
  ]);

  const meta = cats.categories[cat];
  if (!meta) notFound();

  const heroSlugs = new Set(heroes.factors.map((h) => h.name));
  const catFactors = index.factors
    .filter((f) => f.category === cat)
    .sort((a, b) => {
      const ai = a.icir ?? -Infinity;
      const bi = b.icir ?? -Infinity;
      return bi - ai;
    });

  const catIdx = CATEGORY_KEYS.indexOf(cat);
  const prevCat = catIdx > 0 ? CATEGORY_KEYS[catIdx - 1] : null;
  const nextCat = catIdx < CATEGORY_KEYS.length - 1 ? CATEGORY_KEYS[catIdx + 1] : null;

  return (
    <>
      <PageHeader
        eyebrow={`Research · Category · ${meta.label_en}`}
        title={meta.label_zh}
        subtitle={`${catFactors.length} 个因子 · ${meta.label_en}`}
        description={meta.one_liner}
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: meta.label_zh },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <CategoryBadge category={cat} />
          <span className="font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
            {catFactors.length} factors · {catFactors.filter((f) => f.ic_mean !== null).length} with IC
          </span>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          Intuition · 经济直觉
        </h2>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
          {meta.intuition}
        </p>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          A-Share Specifics · A 股特点
        </h2>
        <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1.5">
          {meta.a_share_specifics.map((s, i) => (
            <li key={i}>{s}</li>
          ))}
        </ul>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          Representative Factors · 代表因子
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          {meta.representative_factors.map((r) => {
            const item = index.factors.find((f) => f.name === r.name);
            const isHero = heroSlugs.has(r.name);
            return (
              <Link
                key={r.name}
                href={`/research/${r.name}`}
                className="group block p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
              >
                <div className="flex items-baseline justify-between gap-2 mb-1">
                  <span className="text-sm font-mono font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
                    {r.name}
                  </span>
                  <div className="flex items-center gap-2 shrink-0">
                    {isHero && (
                      <span className="text-[9px] font-mono uppercase tracking-[0.2em] text-[var(--blue)]">
                        hero
                      </span>
                    )}
                    {item?.in_v7 && (
                      <span className="text-[9px] font-mono text-[var(--purple)]">v7</span>
                    )}
                    {item?.in_v16 && (
                      <span className="text-[9px] font-mono text-[var(--blue)]">v16</span>
                    )}
                  </div>
                </div>
                <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{r.why}</p>
                {item && (
                  <div className="mt-2 flex gap-3 text-[10px] font-mono text-[var(--text-tertiary)]">
                    <span>IC={fmtNum(item.ic_mean, 3)}</span>
                    <span>ICIR={fmtNum(item.icir, 2)}</span>
                    <span>t={fmtNum(item.fm_t_stat, 2)}</span>
                  </div>
                )}
              </Link>
            );
          })}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          Common Pitfalls · 常见陷阱
        </h2>
        <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1.5">
          {meta.common_pitfalls.map((p, i) => (
            <li key={i}>{p}</li>
          ))}
        </ul>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="flex items-baseline justify-between gap-4 mb-3">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
            All {catFactors.length} factors in this category
          </h2>
          <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
            sorted by |ICIR| desc
          </span>
        </div>
        <div className="rounded-lg border border-[var(--border-soft)] overflow-hidden">
          <table className="w-full text-xs">
            <thead className="bg-[var(--bg-surface)]/70 text-[var(--text-tertiary)] font-mono uppercase tracking-[0.15em]">
              <tr>
                <th className="text-left px-3 py-2">name</th>
                <th className="text-right px-3 py-2">IC</th>
                <th className="text-right px-3 py-2">ICIR</th>
                <th className="text-right px-3 py-2">FM t</th>
                <th className="text-left px-3 py-2">verdict</th>
                <th className="text-center px-3 py-2">in</th>
              </tr>
            </thead>
            <tbody>
              {catFactors.map((f: FactorIndexItem) => (
                <tr
                  key={f.name}
                  className="border-t border-[var(--border-soft)] hover:bg-[var(--bg-surface)]/40"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/research/${f.name}`}
                      className="font-mono text-[var(--text-primary)] hover:text-[var(--blue)]"
                    >
                      {f.name}
                      {heroSlugs.has(f.name) && (
                        <span className="ml-2 text-[9px] uppercase tracking-[0.2em] text-[var(--blue)]">
                          hero
                        </span>
                      )}
                    </Link>
                  </td>
                  <td className="text-right px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {fmtNum(f.ic_mean, 3)}
                  </td>
                  <td className="text-right px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {fmtNum(f.icir, 2)}
                  </td>
                  <td className="text-right px-3 py-2 font-mono text-[var(--text-secondary)]">
                    {fmtNum(f.fm_t_stat, 2)}
                  </td>
                  <td className="px-3 py-2 text-[var(--text-tertiary)]">{f.verdict ?? "—"}</td>
                  <td className="text-center px-3 py-2 font-mono text-[var(--text-tertiary)]">
                    {f.in_v7 && <span className="text-[var(--purple)] mr-1">v7</span>}
                    {f.in_v16 && <span className="text-[var(--blue)]">v16</span>}
                    {!f.in_v7 && !f.in_v16 && "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-3">
          References
        </h2>
        <ul className="text-sm text-[var(--text-secondary)] leading-relaxed list-disc pl-5 space-y-1">
          {meta.references.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="flex justify-between items-center gap-4 pt-8 border-t border-[var(--border-soft)]">
          {prevCat ? (
            <Link
              href={`/research/category/${prevCat}`}
              className="group flex flex-col gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                ← Prev category
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)]">
                {cats.categories[prevCat]?.label_zh ?? prevCat}
              </span>
            </Link>
          ) : (
            <span />
          )}
          <Link
            href="/research"
            className="text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--text-primary)] shrink-0"
          >
            All categories →
          </Link>
          {nextCat ? (
            <Link
              href={`/research/category/${nextCat}`}
              className="group flex flex-col items-end gap-1 min-w-0"
            >
              <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
                Next category →
              </span>
              <span className="text-sm text-[var(--text-secondary)] group-hover:text-[var(--blue)]">
                {cats.categories[nextCat]?.label_zh ?? nextCat}
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
