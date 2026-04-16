import { PageHeader } from "@/components/layout/PageHeader";

export default function JourneyPage() {
  return (
    <>
      <PageHeader
        eyebrow="Journey · 历程"
        title="From Hypothesis to Strategy"
        subtitle="Phases · decisions · course corrections"
        description="The unedited trail of how this research got here — what was tried, what worked, what didn't, and why the current version looks the way it does."
        crumbs={[{ label: "Home", href: "/" }, { label: "Journey" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            Phase timeline · decision log · lessons — coming in Phase D
          </p>
        </div>
      </section>
    </>
  );
}
