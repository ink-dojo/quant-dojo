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
        eyebrow="Strategy · Multi-Factor · Timeline"
        title="v7 → v25 实验线"
        subtitle={`${timeline.eras.length} 个研究阶段 · ${totalVersions} 个版本 · Week 4-5`}
        description="每个版本记录动机 / 方法 / 结果 / 下一版本的起因 — 包括被证伪的路. Week 5 的 v11-v25 整条挖掘 session 只用了 3 天, 并不是长期迭代."
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Strategy", href: "/strategy" },
          { label: "Multi-Factor" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="max-w-3xl text-[var(--text-secondary)] leading-relaxed space-y-3">
          <p>
            Multi-factor 线 Week 4 起步 (5 因子等权基线 v7), ICIR 加权拿到 research face (v9),
            止损试验 v10 被 WF 否决, 因子挖掘沙盒 v11-v16 碰到 best-in-sample 陷阱,
            regime 门控 v22-v25 把 MDD 收回到门槛内但 sharpe 仍差 0.03.
            Week 6 开始转向事件驱动 (见 /research/event-driven).
          </p>
          <p>
            这条线真正有价值的不是某个版本的 sharpe, 而是
            <span className="text-[var(--text-primary)]">几次被证伪的教训</span>:
            止损无 regime 信号就是 OOS killer (v10), 从挖掘候选里挑 best-in-sample = data snooping (v16),
            分散 / 正交不能降 systematic risk (v22/v24).
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
