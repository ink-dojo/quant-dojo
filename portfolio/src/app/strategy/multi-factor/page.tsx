import Link from "next/link";
import type { Metadata } from "next";
import { PageHeader } from "@/components/layout/PageHeader";
import { readData } from "@/lib/data";
import type { StrategyTimelineFile, TimelineVersionStatus } from "@/lib/types";

export const metadata: Metadata = {
  title: "Multi-Factor Strategy Evolution · QuantDojo",
  description: "v7 → v25 六个时代的多因子策略演化 — 动机、方法、结果、下一步触发。",
};

const STATUS_STYLE: Record<
  TimelineVersionStatus,
  { label: string; color: string; bg: string }
> = {
  legacy: {
    label: "Legacy",
    color: "var(--text-tertiary)",
    bg: "rgba(148,163,184,0.12)",
  },
  production: {
    label: "Production",
    color: "var(--green)",
    bg: "rgba(34,197,94,0.12)",
  },
  rejected: {
    label: "Rejected",
    color: "var(--red)",
    bg: "rgba(239,68,68,0.1)",
  },
  "mining-round": {
    label: "Mining Round",
    color: "var(--gold)",
    bg: "rgba(234,179,8,0.12)",
  },
  candidate: {
    label: "Candidate",
    color: "var(--gold)",
    bg: "rgba(234,179,8,0.12)",
  },
  active: {
    label: "Active",
    color: "var(--purple)",
    bg: "rgba(168,85,247,0.12)",
  },
};

export default async function MultiFactorTimelinePage() {
  const timeline = await readData<StrategyTimelineFile>("strategy/timeline.json");
  const totalVersions = timeline.eras.reduce((sum, e) => sum + e.versions.length, 0);

  return (
    <>
      <PageHeader
        eyebrow="Strategy · Multi-Factor · Evolution"
        title="v7 → v25 演化时间线"
        subtitle={`${timeline.eras.length} 个时代 · ${totalVersions} 个版本`}
        description="每个版本都记录动机 / 方法 / 结果 / 下一版本的起因 — 包括成功、失败、和诚实证伪。"
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Strategy", href: "/strategy" },
          { label: "Multi-Factor" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="max-w-3xl text-[var(--text-secondary)] leading-relaxed space-y-3">
          <p>
            多因子路线从 2026-Q1 的 5 因子等权基线 v7 起步，经过 ICIR 加权 v9、
            止损灾难 v10、因子挖掘沙盒 v11-v16、外生 regime 门控 v22-v25，
            最终在 v25 处达到 saturation，转向事件驱动。
          </p>
          <p>
            这条线最有价值的不是某个 production face, 而是<span className="text-[var(--text-primary)]">六次被证伪的教训</span>：
            止损无 regime 信号就是 OOS killer (v10), IS 2022-2025 挑最佳 = data snooping (v16),
            分散/正交不能降 systematic risk (v22/v24)。
          </p>
        </div>
      </section>

      {timeline.eras.map((era, eraIdx) => (
        <section key={era.id} className="max-w-content mx-auto px-6 pb-16">
          <div className="flex items-baseline justify-between gap-4 mb-2">
            <h2 className="text-xl font-semibold text-[var(--text-primary)]">
              {era.era_label}
            </h2>
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--text-tertiary)]">
              Era {eraIdx + 1}/{timeline.eras.length}
            </span>
          </div>
          <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-3xl">
            {era.theme}
          </p>

          <div className="space-y-4">
            {era.versions.map((v) => {
              const style = STATUS_STYLE[v.status];
              return (
                <Link
                  key={v.id}
                  href={`/strategy/multi-factor/${encodeURIComponent(v.id)}`}
                  className="group block p-5 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all"
                >
                  <div className="flex items-baseline flex-wrap gap-3 mb-2">
                    <span className="text-lg font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
                      {v.name_en}
                    </span>
                    <span
                      className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
                      style={{ color: style.color, background: style.bg }}
                    >
                      {style.label}
                    </span>
                    <span className="text-[10px] font-mono text-[var(--text-tertiary)] ml-auto">
                      {v.date} · {v.id}
                    </span>
                  </div>
                  <div className="text-xs font-mono text-[var(--text-tertiary)] mb-2">
                    {v.name_zh}
                  </div>
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed mb-2">
                    <span className="text-[var(--text-tertiary)]">动机 · </span>
                    {v.motivation}
                  </p>
                  <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
                    <span className="text-[var(--text-tertiary)]">结果 · </span>
                    {v.result}
                  </p>
                </Link>
              );
            })}
          </div>
        </section>
      ))}
    </>
  );
}
