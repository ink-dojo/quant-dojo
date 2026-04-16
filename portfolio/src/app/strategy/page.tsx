import { PageHeader } from "@/components/layout/PageHeader";

export default function StrategyPage() {
  return (
    <>
      <PageHeader
        eyebrow="Strategy · 策略"
        title="Multi-Factor Strategy Construction"
        subtitle="v7 → v9 → v10 → v16"
        description="From a 5-factor equal-weight baseline to a 9-factor production strategy with ICIR-learned weights, industry neutralization, and risk parity sizing."
        crumbs={[{ label: "Home", href: "/" }, { label: "Strategy" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            Version timeline · construction flow · weight radar — coming in Phase C
          </p>
        </div>
      </section>
    </>
  );
}
