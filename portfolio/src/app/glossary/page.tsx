import type { Metadata } from "next";
import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { FormulaDisplay } from "@/components/viz/FormulaDisplay";
import { readData } from "@/lib/data";
import type { GlossaryFile, GlossaryTerm } from "@/lib/types";

export const metadata: Metadata = {
  title: "Glossary · QuantDojo",
  description: "本站术语参考: IC / ICIR / PSR / DSR / Walk-Forward / Admission Gate. 公式 + 直觉 + A 股典型取值.",
};

const CATEGORY_ORDER = [
  "factor-eval",
  "statistical",
  "portfolio",
  "event-driven",
  "operations",
  "other",
];

const CATEGORY_LABEL: Record<string, string> = {
  "factor-eval": "因子评估 · Factor Evaluation",
  statistical: "统计量 · Statistical",
  portfolio: "组合 / 风控 · Portfolio & Risk",
  "event-driven": "事件驱动 · Event-Driven",
  operations: "运维 / 纪律 · Operations & Discipline",
  other: "其他 · Other",
};

export default async function GlossaryPage() {
  const file = await readData<GlossaryFile>("glossary.json");

  const byCategory = new Map<string, GlossaryTerm[]>();
  for (const t of file.terms) {
    const cat = byCategory.has(t.category) ? t.category : t.category;
    const arr = byCategory.get(cat) ?? [];
    arr.push(t);
    byCategory.set(cat, arr);
  }

  const orderedCats = [
    ...CATEGORY_ORDER.filter((c) => byCategory.has(c)),
    ...Array.from(byCategory.keys()).filter((c) => !CATEGORY_ORDER.includes(c)),
  ];

  const termByKey = new Map(file.terms.map((t) => [t.key, t]));

  return (
    <>
      <PageHeader
        eyebrow="Glossary · 术语"
        title="术语参考"
        subtitle={`${file.terms.length} 个术语 · ${orderedCats.length} 类`}
        description="本站用到的统计 / 量化概念: IC · ICIR · PSR · DSR · Walk-Forward · Admission Gate. 每条给公式 + 直觉 + A 股典型取值 + 常见陷阱, 碰到不确定时回来查."
        crumbs={[{ label: "Home", href: "/" }, { label: "Glossary" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <nav
          aria-label="术语跳转"
          className="flex flex-wrap gap-2 p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40"
        >
          {file.terms.map((t) => (
            <a
              key={t.key}
              href={`#${t.key}`}
              className="text-[11px] font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)] hover:underline"
            >
              {t.term_en.split(" (")[0]}
            </a>
          ))}
        </nav>
      </section>

      {orderedCats.map((cat) => (
        <section key={cat} className="max-w-content mx-auto px-6 pb-12">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4 sticky top-0 bg-[var(--bg)] py-2 z-10">
            {CATEGORY_LABEL[cat] ?? cat}
          </h2>
          <div className="space-y-6">
            {(byCategory.get(cat) ?? []).map((term) => (
              <article
                id={term.key}
                key={term.key}
                className="scroll-mt-24 p-5 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40"
              >
                <header className="mb-3">
                  <h3 className="text-lg font-semibold text-[var(--text-primary)]">
                    {term.term_en}
                  </h3>
                  <p className="text-xs font-mono text-[var(--text-tertiary)] mt-0.5">
                    {term.term_zh} · {term.key}
                  </p>
                </header>

                {term.formula_latex && (
                  <div className="mb-3">
                    <FormulaDisplay
                      latex={term.formula_latex}
                      caption={term.formula_caption ?? undefined}
                    />
                  </div>
                )}

                <div className="space-y-3 text-sm leading-relaxed">
                  <div>
                    <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                      intuition · 直觉
                    </span>
                    <p className="text-[var(--text-secondary)] mt-1">{term.intuition}</p>
                  </div>

                  {term.typical_values && (
                    <div>
                      <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                        typical values · 典型取值
                      </span>
                      <p className="text-[var(--text-secondary)] mt-1">{term.typical_values}</p>
                    </div>
                  )}

                  {term.pitfall && (
                    <div>
                      <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                        pitfall · 坑点
                      </span>
                      <p className="text-[var(--text-secondary)] mt-1">{term.pitfall}</p>
                    </div>
                  )}
                </div>

                {term.related && term.related.length > 0 && (
                  <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
                    <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mr-2">
                      related
                    </span>
                    {term.related.map((key, i) => {
                      const exists = termByKey.has(key);
                      return (
                        <span key={key}>
                          {exists ? (
                            <Link
                              href={`#${key}`}
                              className="text-[11px] font-mono text-[var(--blue)] hover:underline"
                            >
                              {key}
                            </Link>
                          ) : (
                            <span className="text-[11px] font-mono text-[var(--text-tertiary)]">
                              {key}
                            </span>
                          )}
                          {i < term.related.length - 1 && (
                            <span className="text-[var(--text-tertiary)] mx-2">·</span>
                          )}
                        </span>
                      );
                    })}
                  </div>
                )}
              </article>
            ))}
          </div>
        </section>
      ))}
    </>
  );
}
