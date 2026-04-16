import { PageHeader } from "@/components/layout/PageHeader";

export default function ResearchPage() {
  return (
    <>
      <PageHeader
        eyebrow="Research · 研究"
        title="Alpha Factor Library"
        subtitle="66 因子 · 8 个深度研究"
        description="From raw price/volume to fundamental signals — every factor tested with IC, ICIR, t-stat, and quintile backtests. Including honest failure cases."
        crumbs={[{ label: "Home", href: "/" }, { label: "Research" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            Hero factor grid · category filters · detail pages — coming in Phase B
          </p>
        </div>
      </section>
    </>
  );
}
