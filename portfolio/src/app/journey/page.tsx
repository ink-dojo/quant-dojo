import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { readData } from "@/lib/data";
import { projectWeek, SITE } from "@/lib/constants";
import type { JourneyFile, Phase } from "@/lib/types";

/**
 * 每个 phase 对应的"决策 + 教训/否决/踩坑"叙事.
 * ROADMAP.md 给出标题和进度打勾; 具体的故事、代价、转向决策写在这里.
 */
const PHASE_NARRATIVE: Record<
  string,
  { scope?: string; rejection?: string; output?: string }
> = {
  "phase-0": {
    scope: "团队分工 (jialong 负责金融逻辑, xingyu 负责代码框架), pip install -e, Tushare + akshare 双数据源接入, 跑通第一张 OHLCV 图.",
    rejection: "早期 akshare 批量下载限流导致数据不完整, 后期切 parquet 缓存.",
    output: "本地环境可拉数据、画图、跑简单计算.",
  },
  "phase-1": {
    scope: "收益率 / 相关性 / t-test / 假设检验; A 股 T+1 / 涨跌停 / 除权除息细节; utils/data_loader, utils/metrics 的骨架.",
    rejection: "—",
    output: "能用代码分析任意 A 股历史数据, 回测和 live 共享同一套 metrics.",
  },
  "phase-2": {
    scope: "事件驱动 vs 向量化两种回测范式; BacktestEngine 固定 __init__/run 签名; 未来函数 / 幸存者偏差 / 交易成本红线写死.",
    rejection: "第一版 dual_ma 没 shift(1) 信号 → 隐性 look-ahead, 发现后重构.",
    output: "strategies/examples/dual_ma.py 完整跑通 + 绩效报告.",
  },
  "phase-3": {
    scope: "4 个经典因子 (动量 / 价值 / 质量 / 低波动) + 分层 / 衰减 / 中性化 / 多因子合成; 66 个因子扫 IC 三件套.",
    rejection: "ROE 因子 IC ≈ 0, 教科书质量因子在 A 股表现不佳, 留在库里作反面案例; 66 里只 18 个过 t-stat 门, 48 个被筛掉.",
    output: "utils/factor_analysis.py (compute_ic_series, quintile_backtest, fama_macbeth_t, decay).",
  },
  "phase-4": {
    scope: "Multi-factor session v7 → v25: 手工等权 → ICIR 学习权重 → 组合止损 → 因子挖掘 v11-v21 → regime gating v22-v25.",
    rejection: "v10 (ICIR + 组合止损) 在 IS 把回撤从 -42% 救到 -24%, 看似完美; WF 17 窗口中位 Sharpe 从 0.53 掉到 0.46, OOS 从 1.60 崩到 0.27 — 止损在震荡市反复割肉, 诚实否决.",
    output: "v9 (ICIR-weighted 5 因子) 成为 research face; v16/v25 挂 candidate, 未 promote.",
  },
  "phase-5": {
    scope: "Paper-trade 四层: signal_generator / broker_adapter / reconcile / factor_snapshot; SQLite WAL ACID ledger + 幸存者偏差修复 + 数据 manifest 指纹.",
    rejection: "—",
    output: "10 个交易日连续 replay, 每日 4/4 步成功, 幂等重跑无副作用; 周报含 git commit + 因子 t-stat audit.",
  },
  "phase-6": {
    scope: "统一 CLI 入口 (qd run / qd audit / qd reconcile), 只读 dashboard 展示所有策略 / 运行状态.",
    rejection: "—",
    output: "quant_dojo CLI 16 个子命令; portfolio 站点 (本站) 自动同步 repo 最新 commit.",
  },
  "phase-7": {
    scope: "Claude / Ollama agent 写因子草稿 / 跑 coverage audit / 交叉验证 journal 一致性; 人工 admission gate 仍是硬约束.",
    rejection: "MD&A drift factor KILL (IC 0.0036 << 0.015 门槛); BGFD fade 假设证伪 (反向 follow consensus OOS 2025 Sharpe 2.23 才有 alpha).",
    output: "agent 能提出实验 / 跑 backtest / 出报告; pre-reg + 5-gate 评审保持在人手里.",
  },
  "phase-8": {
    scope: "真实资金前: 合规 / 风控规则固化 / 自动熔断 / 券商 API 审查 / AI 治理规则.",
    rejection: "—",
    output: "(待写 — 还没到那里.)",
  },
};

const STATUS_STYLE: Record<
  Phase["status"],
  { color: string; bg: string; label: string }
> = {
  done: { color: "var(--green)", bg: "rgba(34,197,94,0.1)", label: "Done" },
  running: { color: "var(--blue)", bg: "rgba(59,130,246,0.1)", label: "Running" },
  planned: { color: "var(--gold)", bg: "rgba(234,179,8,0.1)", label: "Planned" },
};

export default async function JourneyPage() {
  const journey = await readData<JourneyFile>("journey/phases.json");

  const totalChecks = journey.phases.reduce((s, p) => s + p.checks_total, 0);
  const doneChecks = journey.phases.reduce((s, p) => s + p.checks_done, 0);
  const overallProgress = totalChecks > 0 ? doneChecks / totalChecks : 0;
  const { week, dateStr } = projectWeek();

  return (
    <>
      <PageHeader
        eyebrow={`Week ${week} · ${dateStr}`}
        title="6 周 · 9 phase · 48 个因子被筛掉"
        subtitle={`Project started ${SITE.started_at} · today ${dateStr} · Day ${(week - 1) * 7 + 1}+`}
        description="按周线时间轴看项目从 0 到当前的 scope / rejection / output. ROADMAP.md 里的 phase 编号是研究里程碑, 不是周数; 下面每个 phase 标的是实际日期区间, 有的 phase 压缩在几天内完成, 有的横跨一周以上."
        crumbs={[{ label: "Home", href: "/" }, { label: "Journey" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <div className="flex items-baseline justify-between mb-3">
            <span className="text-[10px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)]">
              Overall progress
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
            Credibility signals · 诚实的失败清单
          </p>
          <ul className="space-y-1.5">
            <li>
              Phase 3: 66 因子扫 IC 三件套, 只 18 个过 t-stat 门 → 留着全部 48 个否决作为
              ablation. (
              <Link href="/research/roe_factor" className="text-[var(--red)] hover:underline">
                roe_factor
              </Link>{" "}
              是典型反面案例)
            </li>
            <li>
              Phase 4:{" "}
              <Link href="/validation" className="text-[var(--red)] hover:underline">
                v10 止损层
              </Link>{" "}
              — IS 回撤救回 18pp, OOS Sharpe 从 1.60 崩到 0.27, WF 否决并回滚.
            </li>
            <li>
              Week 6: spec v4 RIAD + DSR#30 BB-only 合成 paper-trade proposal 写完 → 否决.
              Filtered universe OOS 2025 Sharpe −0.59, DSR 0.92 &lt; 0.95 门槛;
              合成的 4/5 gate 是在 baseline (不可执行) 版本上过的.
            </li>
            <li>
              Week 6: MD&amp;A drift factor KILL — subset 500 × 8 年 PDF 跑完,
              IC 0.0036 &lt; 0.015 门槛, 方向符号存在但幅度不足.
            </li>
            <li>
              Week 6: BGFD fade 假设证伪 — 原本想 short crowded 金股, 反向 (follow consensus)
              OOS 2025 Sharpe 2.23.
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
          {phase.week_range && (
            <span className="text-[10px] font-mono text-[var(--blue)]">
              {phase.week_range}
            </span>
          )}
          {phase.date_range && (
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
              {phase.date_range}
            </span>
          )}
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
          <dl className="mt-4 text-sm space-y-3">
            {narrative.scope && (
              <div>
                <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-0.5">
                  Scope
                </dt>
                <dd className="text-[var(--text-secondary)] leading-relaxed">
                  {narrative.scope}
                </dd>
              </div>
            )}
            {narrative.rejection && narrative.rejection !== "—" && (
              <div>
                <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--red)] mb-0.5">
                  Rejection / Lesson
                </dt>
                <dd className="text-[var(--text-secondary)] leading-relaxed">
                  {narrative.rejection}
                </dd>
              </div>
            )}
            {narrative.output && (
              <div>
                <dt className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-0.5">
                  Output
                </dt>
                <dd className="text-[var(--text-secondary)] leading-relaxed">
                  {narrative.output}
                </dd>
              </div>
            )}
          </dl>
        )}
      </article>
    </li>
  );
}
