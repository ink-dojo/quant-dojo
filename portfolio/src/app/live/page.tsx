import { PageHeader } from "@/components/layout/PageHeader";

export default function LivePage() {
  return (
    <>
      <PageHeader
        eyebrow="Live · 实盘"
        title="Paper Trading Dashboard"
        subtitle="v16 · running since 2026"
        description="The current production strategy running on live A-share data — position snapshots, daily P&L, and divergence from backtest expectations."
        crumbs={[{ label: "Home", href: "/" }, { label: "Live" }]}
      />
      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="p-8 rounded-lg border border-dashed border-[var(--border-soft)] text-center">
          <p className="text-sm font-mono text-[var(--text-tertiary)]">
            Live equity · positions · tracking error — coming in Phase F
          </p>
        </div>
      </section>
    </>
  );
}
