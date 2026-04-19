import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { EquityChart } from "@/components/viz/EquityChart";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { readData } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import type { EquityCurveFile } from "@/lib/types";

interface Trial {
  id: number;
  name: string;
  factor: string;
  n_pass: number;
  ann: number;
  sharpe: number;
  mdd: number;
  psr: number;
  ci_low: number;
  status: "candidate" | "fail" | "falsified";
}

interface Gates {
  ann_ge_15pct: boolean;
  sharpe_ge_08: boolean;
  mdd_gt_neg30pct: boolean;
  psr_ge_95pct: boolean;
  ci_low_ge_05: boolean;
}

interface CandidateBlock {
  ann_return: number;
  sharpe: number;
  max_drawdown: number;
  psr: number;
  sharpe_ci_low: number;
  sharpe_ci_high: number;
  n_obs: number;
  gates: Gates;
  n_pass: number;
}

interface EnsembleBlock extends CandidateBlock {
  correlation: number;
}

interface TrialsFile {
  generated_at: string;
  n_trials_conservative: number;
  n_pass_4_of_5: number;
  candidates: string[];
  ensemble_50_50: EnsembleBlock;
  dsr30: CandidateBlock;
  dsr33: CandidateBlock;
  trials: Trial[];
}

export default async function EventDrivenPage() {
  const [trials, eq30, eq33, eqEns] = await Promise.all([
    readData<TrialsFile>("event_driven/trials.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr30_bb.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr33_lhb_decline.json"),
    readData<EquityCurveFile>("event_driven/equity_dsr30_33_ensemble.json"),
  ]);

  const byStatus = {
    candidate: trials.trials.filter((t) => t.status === "candidate"),
    falsified: trials.trials.filter((t) => t.status === "falsified"),
    fail: trials.trials.filter((t) => t.status === "fail"),
  };

  const series = [
    { id: "dsr30", label: "#30 BB 主板 rescaled (4/5)", color: "var(--blue)", curve: eq30, dashed: false },
    { id: "dsr33", label: "#33 LHB 跌幅 contrarian (4/5)", color: "var(--gold)", curve: eq33, dashed: false },
    { id: "ens", label: "50/50 ensemble (5/5)", color: "var(--green)", curve: eqEns, dashed: false },
  ];

  return (
    <>
      <PageHeader
        eyebrow="Research · Event-Driven"
        title="21 预注册 trials · 1 个 5/5 组合"
        subtitle="Phase 3 + 4 + 4.1 · Event-driven long-only on A-share main board"
        description="从锁定期 / 回购 / 业绩预告 / 龙虎榜 / 分红 / 股东增减持六类事件出发，逐一 pre-register hypothesis → backtest → 过 5-gate admission。最终两个 4/5 候选因失败模式正交，50/50 ensemble 过全 5 gate。"
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Research", href: "/research" },
          { label: "Event-Driven" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="max-w-3xl space-y-4 text-[var(--text-secondary)] leading-relaxed">
          <p>
            事件驱动 long-only 策略 — 所有假设在 backtest 前
            <span className="text-[var(--text-primary)]">写入 pre-reg spec</span>
            , 跑完按 5-gate 硬门槛评估（年化 15% / Sharpe 0.8 / 回撤 30% /
            PSR 0.95 / Bootstrap Sharpe CI_low 0.5）。
            一共 {trials.n_trials_conservative} trials 守纪律计入 DSR penalty
            （对从 n 次尝试里挑最佳做多重检验修正）。
          </p>
          <p>
            单独策略里最多过 4/5。<span className="text-[var(--gold)] font-semibold">
              DSR #30 BB 回购 drift</span>卡在 CI_low（样本 8 年不够稳），
            <span className="text-[var(--gold)] font-semibold">DSR #33 LHB 跌幅 contrarian</span>
            卡在 MDD（尾部失控）— 两者失败模式互补，
            相关系数仅 <span className="font-mono">{fmtNum(trials.ensemble_50_50.correlation, 2)}</span>。
            50/50 等权 ensemble（零自由度 combination rule）达 5/5。
          </p>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          50/50 Ensemble · 5/5 PASS
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          零 DoF combination (1/2 · #30 + 1/2 · #33), 主板 only, 成本 15bps/side,
          gross cap 1.0 已施加于每个 sleeve。下图三条曲线共坐标 — 观察组合曲线
          <span className="text-[var(--green)] font-semibold"> 尾部浅于两个成分</span>
          但上行斜率显著高于 #30。
        </p>
        <div className="rounded-lg border border-[var(--green)]/30 bg-[var(--green)]/[0.05] p-4 mb-6">
          <EquityChart series={series} height={400} />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <EnsembleMetricCard
            tag="5/5 gate"
            headline={`${fmtPct(trials.ensemble_50_50.ann_return, 1)}`}
            subline={`ann · SR ${fmtNum(trials.ensemble_50_50.sharpe, 2)}`}
            body={`MDD ${fmtPct(trials.ensemble_50_50.max_drawdown, 1)} < -30% 红线；Bootstrap CI_low ${fmtNum(trials.ensemble_50_50.sharpe_ci_low, 2)} >> 0.5 gate.`}
            tone="green"
          />
          <EnsembleMetricCard
            tag="Diversification"
            headline={`ρ = ${fmtNum(trials.ensemble_50_50.correlation, 2)}`}
            subline={`独立失败模式`}
            body={`#30 tail 稳 CI 弱 · #33 CI 超强 tail 失控。Equal-weight 把两条曲线的缺陷抵消。`}
            tone="blue"
          />
          <EnsembleMetricCard
            tag="PSR · DSR-aware"
            headline={`${fmtPct(trials.ensemble_50_50.psr, 1)}`}
            subline={`vs zero, n = ${trials.ensemble_50_50.n_obs}`}
            body={`从 ${trials.n_trials_conservative} 个 pre-reg trials 里挑 2 个做 ensemble — 选择偏差已在 DSR penalty 层面 bookkeep.`}
            tone="gold"
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-4">
          两个 4/5 成分 · 失败模式互补
        </h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
          <CandidateDeep
            slug="dsr30-bb"
            tag="DSR #30"
            title="BB-only 主板 rescaled"
            thesis="A 股版 Ikenberry 1995 — 上市公司自愿回购后 T+1 ~ T+20 drift. 主板过滤去掉小盘噪声, UNIT rescale 把 mean gross 提到 0.80."
            failMode="仅 CI_low 0.20 < 0.5 gate — 8 年样本对 Sharpe 稳定性估计不足"
            m={trials.dsr30}
          />
          <CandidateDeep
            slug="dsr33-lhb-decline"
            tag="DSR #33"
            title="LHB 跌幅 contrarian · 席位净买入"
            thesis="DeBondt-Thaler 1985 短期 reversion + informed-flow 筛选 — 股票日跌幅 7% 上榜（散户恐慌抛售）, 若 LHB 席位反而净买入, 是 institutional informed confidence signal. T+1 ~ T+5 捕捉 reversion."
            failMode="仅 MDD -55.9% 未过 — 统计置信极强 (CI_low 1.31) 但集中性尾风险未对冲"
            m={trials.dsr33}
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          DSR #32 / #34 · falsification 而非浪费
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          DSR #33 通过了 4/5, 但 "seat 净买入" 这个信号是不是只在跌幅场景 work?
          同一份 LHB 数据, 换 category 各跑一遍 —
          <span className="text-[var(--red)] font-semibold"> 0/5 两次</span>。
          这 falsification 反而加固 #33 假设: alpha 来自
          &ldquo;跌幅 × 席位净买入&rdquo; 的 conditional informed-flow,
          不是泛泛 seat 信号。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          {[...byStatus.falsified, byStatus.candidate.find((c) => c.id === 33)!]
            .filter(Boolean)
            .map((t) => (
              <FalsifyCard key={t.id} trial={t} />
            ))}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
          完整 trial 表 · {trials.n_trials_conservative} pre-registered
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          按 n_pass 降序 — 除 2 个 4/5 候选外, 其余全部 ≤ 3/5。
          这份诚实的负结果表本身是最重要的产出: 说明
          <span className="text-[var(--text-primary)]"> 主板 long-only 单因子事件 alpha 普遍薄</span>
          , 优势只出现在 ensemble 层。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-3 py-3 font-normal w-14">#</th>
                <th className="text-left px-3 py-3 font-normal">假设</th>
                <th className="text-left px-3 py-3 font-normal">因子类</th>
                <th className="text-right px-3 py-3 font-normal">ann</th>
                <th className="text-right px-3 py-3 font-normal">Sharpe</th>
                <th className="text-right px-3 py-3 font-normal">MDD</th>
                <th className="text-right px-3 py-3 font-normal">PSR</th>
                <th className="text-right px-3 py-3 font-normal">CI_low</th>
                <th className="text-center px-3 py-3 font-normal">Gate</th>
              </tr>
            </thead>
            <tbody>
              {[...trials.trials]
                .sort((a, b) => b.n_pass - a.n_pass || b.sharpe - a.sharpe)
                .map((t) => (
                  <TrialRow key={t.id} t={t} />
                ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Takeaway
            title="方法论: 零自由度 + 诚实记账"
            body="每个 DSR trial 开工前写 pre-reg spec (数据源 / 信号 / 方向 / 窗口 / UNIT / gross cap 全固定), 跑完把结果钉到 journal, 不再修参。这意味着表里的 17 个 fail 不能藏。从 21 个 trial 里挑 best-Sharpe 再做 ensemble = 天然有选择偏差 — DSR penalty 负责 bookkeep。"
          />
          <Takeaway
            title="发现: gross-cap bug 修正"
            body="Phase 3 期间发现早期 Sharpe 偏高是因为 UNIT × 事件聚集期位置数 > gross cap 1.0 → 被悄悄放大杠杆。加入 apply_gross_cap 后, 原 3 真 alpha 两个退回 ~10% ann, 一个 Sharpe 从 0.91 降到 0.64。这条修正是 Phase 3.5 的核心产出, 也是为什么需要 UNIT rescale 重跑 (#30)。"
          />
          <Takeaway
            title="A 股 event-driven 的真相"
            body="单因子 long-only alpha 普遍薄 & 方差大, 8 年样本不足以穿过 CI_low 0.5 gate。但 DSR #30 + #33 的正交失败模式支撑了 ensemble 层 5/5 — 说明 A 股 alpha 不是不存在, 只是需要多因子组合 & 风险互补才稳。"
          />
          <Takeaway
            title="下一步 · paper-trade"
            body="50/50 ensemble 准备进 paper-trade, 资金 10-20%, forward test 6-12 个月。若 live 曲线守住 SR > 1.0 + MDD > -30%, 把规模推到 30-50% — 否则回 drawing board 加入资金流 / 北向 / 分钟频数据。"
          />
        </div>
        <div className="mt-6 text-xs text-[var(--text-tertiary)]">
          数据: <code className="font-mono">data/raw/events/_all_*.parquet</code> · 计算:
          <code className="font-mono"> research/event_driven/dsr3*_*.py</code> ·
          methodology: pre-reg spec + deflated Sharpe + bootstrap CI.
        </div>
      </section>
    </>
  );
}

function EnsembleMetricCard({
  tag,
  headline,
  subline,
  body,
  tone,
}: {
  tag: string;
  headline: string;
  subline: string;
  body: string;
  tone: "green" | "blue" | "gold";
}) {
  const color =
    tone === "green" ? "var(--green)" : tone === "blue" ? "var(--blue)" : "var(--gold)";
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] mb-1" style={{ color }}>
        {tag}
      </p>
      <p className="text-2xl font-mono font-semibold" style={{ color }}>
        {headline}
      </p>
      <p className="text-xs font-mono text-[var(--text-tertiary)] mb-2">{subline}</p>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}

function CandidateDeep({
  slug,
  tag,
  title,
  thesis,
  failMode,
  m,
}: {
  slug: string;
  tag: string;
  title: string;
  thesis: string;
  failMode: string;
  m: CandidateBlock;
}) {
  return (
    <article className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
      <div className="flex items-baseline gap-2 mb-1">
        <span className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--gold)]">
          {tag} · 4/5
        </span>
      </div>
      <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-4">{thesis}</p>
      <MetricGrid
        metrics={[
          { label: "年化", value: fmtPct(m.ann_return, 1), tone: m.gates.ann_ge_15pct ? "good" : "warn" },
          { label: "Sharpe", value: fmtNum(m.sharpe, 2), tone: m.gates.sharpe_ge_08 ? "good" : "warn" },
          { label: "Max DD", value: fmtPct(m.max_drawdown, 1), tone: m.gates.mdd_gt_neg30pct ? "good" : "bad" },
          { label: "CI_low", value: fmtNum(m.sharpe_ci_low, 2), tone: m.gates.ci_low_ge_05 ? "good" : "bad" },
        ]}
      />
      <div className="mt-3 rounded-md border border-[var(--red)]/20 bg-[var(--red)]/[0.04] p-3">
        <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--red)] mb-1">
          唯一 fail gate
        </p>
        <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{failMode}</p>
      </div>
    </article>
  );
}

function FalsifyCard({ trial }: { trial: Trial }) {
  const isPass = trial.status === "candidate";
  const color = isPass ? "var(--green)" : "var(--red)";
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: `color-mix(in srgb, ${color} 25%, transparent)`,
        background: `color-mix(in srgb, ${color} 4%, transparent)`,
      }}
    >
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] mb-1" style={{ color }}>
        DSR #{trial.id} · {isPass ? "4/5 PASS" : "0/5 FAIL"}
      </p>
      <p className="text-sm font-semibold text-[var(--text-primary)] mb-2">{trial.name}</p>
      <div className="text-xs font-mono text-[var(--text-secondary)] space-y-0.5">
        <p>ann: {fmtPct(trial.ann, 1)}</p>
        <p>Sharpe: {fmtNum(trial.sharpe, 2)}</p>
        <p>MDD: {fmtPct(trial.mdd, 1)}</p>
      </div>
    </div>
  );
}

function TrialRow({ t }: { t: Trial }) {
  const rowBg =
    t.status === "candidate"
      ? "bg-[var(--gold)]/[0.06]"
      : t.status === "falsified"
      ? "bg-[var(--red)]/[0.04]"
      : "";
  return (
    <tr className={`border-b border-[var(--border-soft)] last:border-b-0 ${rowBg}`}>
      <td className="px-3 py-2.5 font-mono text-[var(--text-tertiary)]">#{t.id}</td>
      <td className="px-3 py-2.5 text-[var(--text-primary)]">
        <span className="text-sm">{t.name}</span>
      </td>
      <td className="px-3 py-2.5">
        <span className="text-[10px] font-mono uppercase text-[var(--text-tertiary)]">
          {t.factor}
        </span>
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.ann >= 0.15 ? "var(--green)" : t.ann < 0 ? "var(--red)" : "var(--text-secondary)" }}
      >
        {fmtPct(t.ann, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.sharpe >= 0.8 ? "var(--green)" : t.sharpe < 0 ? "var(--red)" : "var(--text-secondary)" }}
      >
        {fmtNum(t.sharpe, 2)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono"
        style={{ color: t.mdd > -0.3 ? "var(--green)" : "var(--red)" }}
      >
        {fmtPct(t.mdd, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono text-xs"
        style={{ color: t.psr >= 0.95 ? "var(--green)" : "var(--text-secondary)" }}
      >
        {fmtPct(t.psr, 1)}
      </td>
      <td
        className="px-3 py-2.5 text-right font-mono text-xs"
        style={{ color: t.ci_low >= 0.5 ? "var(--green)" : "var(--text-secondary)" }}
      >
        {fmtNum(t.ci_low, 2)}
      </td>
      <td className="px-3 py-2.5 text-center font-mono text-xs">
        <span
          style={{
            color:
              t.n_pass === 4 ? "var(--gold)" : t.n_pass === 5 ? "var(--green)" : t.n_pass === 0 ? "var(--red)" : "var(--text-secondary)",
          }}
        >
          {t.n_pass}/5
        </span>
      </td>
    </tr>
  );
}

function Takeaway({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">{title}</h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}
