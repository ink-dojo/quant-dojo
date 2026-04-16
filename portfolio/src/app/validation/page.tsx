import { PageHeader } from "@/components/layout/PageHeader";

export default function ValidationPage() {
  return (
    <>
      <PageHeader
        eyebrow="Validation · 验证"
        title="Walk-Forward & Out-of-Sample"
        subtitle="Rolling windows · regime analysis"
        description="Every strategy version revalidated on rolling out-of-sample windows — the only way to know whether backtest Sharpe survives contact with the future."
        crumbs={[{ label: "Home", href: "/" }, { label: "Validation" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            Equity curves · drawdown · monthly heatmap — coming in Phase C
          </p>
        </div>
      </section>
    </>
  );
}
