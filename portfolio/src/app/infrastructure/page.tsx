import { PageHeader } from "@/components/layout/PageHeader";

export default function InfrastructurePage() {
  return (
    <>
      <PageHeader
        eyebrow="Infrastructure · 工程"
        title="Research & Execution Stack"
        subtitle="Data pipeline · backtesting engine · CI"
        description="The plumbing beneath the research: data loaders, factor analysis utilities, backtest engine, and automation that keeps this site synced with the repo."
        crumbs={[{ label: "Home", href: "/" }, { label: "Infrastructure" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            System diagram · data flow · tech stack — coming in Phase F
          </p>
        </div>
      </section>
    </>
  );
}
