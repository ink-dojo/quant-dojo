import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { readData } from "@/lib/data";
import type { JourneyFile, Phase } from "@/lib/types";

/**
 * Hand-written narrative hooks for each phase. ROADMAP.md gives us titles
 * and progress ticks; the *story* — what was hard, what the course
 * correction was — lives here. Keep it one or two sentences per phase.
 */
const PHASE_NARRATIVE: Record<string, { decision?: string; lesson?: string }> = {
  "phase-0": {
    decision: "确定三人角色分工（jialong 金融逻辑 / xingyu 代码框架）",
    lesson: "统一工具链之前不开始写业务代码 — 否则调环境的时间会淹没研究",
  },
  "phase-1": {
    decision: "数据层 Tushare + 日频收盘 / 基本面双源头",
    lesson: "先把 loader 的 assertion 门写死（行数、空值、单调），之后每个 notebook 都受益",
  },
  "phase-2": {
    decision: "回测引擎 BacktestEngine 固定接口，不让 notebook 改签名",
    lesson: "回测结果必须和 live 产物共享同一份 metrics.py — 两套指标等于在骗自己",
  },
  "phase-3": {
    decision: "IC / ICIR / Fama-MacBeth 三件套作为因子入库门",
    lesson:
      "66 个因子里只有 18 个过门，其余大多数是「看起来有道理」的噪声 — 这一步筛掉了多数过拟合陷阱",
  },
  "phase-4": {
    decision: "从 v7 手工权重切到 v9 ICIR 学习，中途试过 v10 止损层",
    lesson:
      "v10 在 IS 回撤 -42% → -24% 看起来是救命丹，OOS Sharpe 1.60 → 0.27 说明止损在震荡市反复割肉 — 诚实否决，回滚",
  },
  "phase-5": {
    decision: "模拟盘基础设施：signal / execution / reconcile / snapshot 四层",
    lesson: "snapshot 可重放是整个系统的地基 — 只要一个 run 的信号能复原，bug 就能 bisect",
  },
  "phase-6": {
    decision: "CLI 统一入口（qd run / qd audit / qd reconcile），dashboard 只读",
    lesson: "把「入口多了就乱」作为设计公理，任何新脚本先问自己能不能挂在现有 qd 子命令下",
  },
  "phase-7": {
    decision: "引入 Agentic Research，但设置门禁（操作员，不是决策者）",
    lesson: "AI agent 可以写 notebook 草稿、跑 coverage audit，但 admission gate 必须由人签字",
  },
  "phase-8": {
    decision: "真实资金前准备：合规、风控、回路校验",
    lesson: "（待写 — 还没到那里）",
  },
};

const STATUS_STYLE: Record<
  Phase["status"],
  { color: string; bg: string; label: string }
> = {
  done: { color: "var(--green)", bg: "rgba(34,197,94,0.1)", label: "完成" },
  running: { color: "var(--blue)", bg: "rgba(59,130,246,0.1)", label: "进行" },
  planned: { color: "var(--gold)", bg: "rgba(234,179,8,0.1)", label: "规划" },
};

export default async function JourneyPage() {
  const journey = await readData<JourneyFile>("journey/phases.json");

  const totalChecks = journey.phases.reduce((s, p) => s + p.checks_total, 0);
  const doneChecks = journey.phases.reduce((s, p) => s + p.checks_done, 0);
  const overallProgress = totalChecks > 0 ? doneChecks / totalChecks : 0;

  return (
    <>
      <PageHeader
        eyebrow="Journey · 历程"
        title="From Hypothesis to Strategy"
        subtitle={`9 phases · ${doneChecks}/${totalChecks} checkpoints`}
        description="这里展示的不是完美版本，是真实的路径。每个阶段都包含一个关键决策和一条代价换来的教训 — 尤其是 Phase 4 的 v10 否决，和 Phase 3 里筛掉的 48 个过拟合因子。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Journey" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
              Overall Progress
            </span>
            <span className="text-sm font-mono text-[var(--text-secondary)]">
              {doneChecks}/{totalChecks} ·{" "}
              <span className="text-[var(--blue)]">
                {(overallProgress * 100).toFixed(0)}%
              </span>
            </span>
          </div>
          <div className="h-2 rounded-full bg-[var(--border-soft)] overflow-hidden">
            <div
              className="h-full bg-gradient-to-r from-[var(--green)] to-[var(--blue)]"
              style={{ width: `${overallProgress * 100}%` }}
            />
          </div>
          <p className="text-[10px] font-mono text-[var(--text-tertiary)] mt-3">
            Source: {journey.source} · generated {journey.generated_at}
          </p>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <ol className="relative border-l border-[var(--border-soft)] ml-3 space-y-5">
          {journey.phases.map((p, i) => (
            <PhaseNode key={p.id} phase={p} index={i} />
          ))}
        </ol>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5 text-sm text-[var(--text-secondary)]">
          <p className="font-semibold text-[var(--text-primary)] mb-2">
            诚实失败清单（Credibility Signals）
          </p>
          <ul className="space-y-1.5">
            <li>
              <Link
                href="/research/roe_factor"
                className="text-[var(--red)] hover:underline"
              >
                roe_factor
              </Link>{" "}
              — 教科书质量因子但 IC ≈ 0，A 股 ROE proxy 噪声太大，留在因子库作为反面案例
            </li>
            <li>
              <Link
                href="/validation"
                className="text-[var(--red)] hover:underline"
              >
                v10 策略
              </Link>{" "}
              — ICIR 权重 + 组合止损，IS 看起来完美但 OOS Sharpe 从 1.60 掉到 0.27，否决并回滚
            </li>
            <li>
              Phase 3 下架 48 个因子 — 初版因子库 66 个，IC 三件套门后仅剩 18 个有统计显著性
            </li>
          </ul>
        </div>
      </section>
    </>
  );
}

function PhaseNode({ phase, index }: { phase: Phase; index: number }) {
  const s = STATUS_STYLE[phase.status];
  const progress = phase.progress ?? 0;
  const narrative = PHASE_NARRATIVE[phase.id];

  return (
    <li className="ml-5 relative">
      <span
        className="absolute -left-[27px] top-2 w-3 h-3 rounded-full border-2"
        style={{ borderColor: s.color, background: s.color }}
        aria-hidden
      />
      <article className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
        <header className="flex flex-wrap items-center gap-3 mb-3">
          <span
            className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
            style={{ color: s.color, background: s.bg }}
          >
            {s.label}
          </span>
          <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
            #{index + 1} · {phase.label}
          </span>
          <span className="text-[10px] font-mono text-[var(--text-tertiary)] ml-auto">
            {phase.checks_done}/{phase.checks_total}
          </span>
        </header>
        <h3 className="text-base font-semibold text-[var(--text-primary)]">
          {phase.title}
        </h3>

        <div className="mt-3 h-1 rounded-full bg-[var(--border-soft)] overflow-hidden">
          <div
            className="h-full transition-all"
            style={{ width: `${progress * 100}%`, background: s.color }}
          />
        </div>

        {narrative && (
          <dl className="mt-4 text-sm space-y-2.5">
            {narrative.decision && (
              <div>
                <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-0.5">
                  Key Decision
                </dt>
                <dd className="text-[var(--text-secondary)] leading-relaxed">
                  {narrative.decision}
                </dd>
              </div>
            )}
            {narrative.lesson && (
              <div>
                <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-0.5">
                  Lesson
                </dt>
                <dd className="text-[var(--text-secondary)] leading-relaxed italic">
                  {narrative.lesson}
                </dd>
              </div>
            )}
          </dl>
        )}
      </article>
    </li>
  );
}
