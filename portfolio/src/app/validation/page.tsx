import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  StrategyVersionsFile,
} from "@/lib/types";

/**
 * Walk-forward numbers come from journal/v10_icir_stoploss_eval_20260416.md.
 * Hard-coded here because there is no structured dump — if the eval script
 * ever writes a WF summary JSON, swap this for a readData call.
 */
const WF_TABLE = [
  {
    version: "v7",
    label: "手工权重",
    windows: 17,
    sharpe_mean: 0.4808,
    sharpe_median: 0.0,
    win_rate: 0.53,
    verdict: "baseline",
  },
  {
    version: "v8",
    label: "regime + 止损",
    windows: 17,
    sharpe_mean: 0.4917,
    sharpe_median: 0.2756,
    win_rate: 0.71,
    verdict: "已并入 v9 血统",
  },
  {
    version: "v9",
    label: "ICIR 无止损",
    windows: 17,
    sharpe_mean: 0.6322,
    sharpe_median: 0.5256,
    win_rate: 0.65,
    verdict: "research face",
    highlight: true,
  },
  {
    version: "v10",
    label: "ICIR + 止损",
    windows: 17,
    sharpe_mean: 0.4414,
    sharpe_median: 0.4555,
    win_rate: 0.65,
    verdict: "rejected",
    rejected: true,
  },
];

const ADMISSION_GATE = [
  {
    metric: "年化收益",
    threshold: "> 15%",
    v9: { value: "+18.67%", pass: true },
    v10: { value: "+14.09%", pass: false },
    v16: { value: "+28.40%", pass: true, note: "IS 最高，但孤立不可信" },
  },
  {
    metric: "夏普比率",
    threshold: "> 0.8",
    v9: { value: "0.6417", pass: false },
    v10: { value: "0.8426", pass: true },
    v16: { value: "0.7345", pass: false },
  },
  {
    metric: "最大回撤",
    threshold: "< 30%",
    v9: { value: "-41.92%", pass: false, note: "IS 含 2015/2018 熊市" },
    v10: { value: "-23.64%", pass: true },
    v16: { value: "-43.04%", pass: false, note: "超红线" },
  },
  {
    metric: "WF 夏普中位数",
    threshold: "> 0.20",
    v9: { value: "0.5256", pass: true },
    v10: { value: "0.4555", pass: true },
    v16: { value: "—", pass: false, note: "未跑 WF" },
  },
  {
    metric: "OOS Sharpe (2025)",
    threshold: "承诺 ≥ IS",
    v9: { value: "1.6005", pass: true, note: "↑ 2.5x vs IS" },
    v10: { value: "0.2749", pass: false, note: "↓ 从 IS 0.84 掉到 0.27" },
    v16: { value: "—", pass: false, note: "未出 IS" },
  },
];

export default async function ValidationPage() {
  const versionsFile = await readData<StrategyVersionsFile>(
    "strategy/versions.json"
  );

  const v9Curve = await readDataOrNull<EquityCurveFile>("strategy/equity_v9.json");
  const v10Curve = await readDataOrNull<EquityCurveFile>("strategy/equity_v10.json");
  const v16Curve = await readDataOrNull<EquityCurveFile>("strategy/equity_v16.json");

  const series = [
    v9Curve && {
      id: "v9",
      label: "v9 · research face",
      color: "var(--green)",
      curve: v9Curve,
    },
    v10Curve && {
      id: "v10",
      label: "v10 · 加止损（否决）",
      color: "var(--red)",
      dashed: true,
      curve: v10Curve,
    },
    v16Curve && {
      id: "v16",
      label: "v16 · 挖掘候选（未上 live）",
      color: "var(--gold)",
      dashed: true,
      curve: v16Curve,
    },
  ].filter((s): s is NonNullable<typeof s> => s !== null);

  return (
    <>
      <PageHeader
        eyebrow="Validation · 否决档案"
        title="Post-mortems — 否决过的路"
        subtitle="Walk-forward · admission gate · IS vs OOS · pre-reg red lines"
        description={`展示我否决了什么, 为什么否决. 比起「最好的策略」这页更说明方法论 — v10 被 WF 否决 · v16 过不了红线 · MD&A drift IC 不够 · BGFD fade 假设反向 · v4 RIAD 合成 spec 最终放弃. 每条都有具体数字和红线.`}
        crumbs={[{ label: "Home", href: "/" }, { label: "Validation" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Admission Gate — v9 · v10 · v16
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-3xl">
          策略进入 live 前必须过的 5 条硬门槛。v10 被 OOS 否决；v16 在 IS 年化最高，
          但回撤超红线、WF 未跑、OOS 未出 — 不能因为&ldquo;IS 最高&rdquo;就放它上 live。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Metric</th>
                <th className="text-left px-4 py-3 font-normal">Threshold</th>
                <th className="text-left px-4 py-3 font-normal text-[var(--green)]">
                  v9 · face
                </th>
                <th className="text-left px-4 py-3 font-normal text-[var(--red)]">
                  v10 · rejected
                </th>
                <th className="text-left px-4 py-3 font-normal text-[var(--gold)]">
                  v16 · candidate
                </th>
              </tr>
            </thead>
            <tbody>
              {ADMISSION_GATE.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-[var(--border-soft)] last:border-b-0"
                >
                  <td className="px-4 py-3 text-[var(--text-primary)]">{row.metric}</td>
                  <td className="px-4 py-3 font-mono text-xs text-[var(--text-tertiary)]">
                    {row.threshold}
                  </td>
                  <GateCell cell={row.v9} />
                  <GateCell cell={row.v10} />
                  <GateCell cell={row.v16} />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      {series.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Equity Overlay — 三代策略同期对照
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4">
            2022-01 → 2025-12 全样本（含 2025 OOS）。v10 虚线在 2024-2025 被 v9 和 v16 甩开。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart series={series} height={360} />
          </div>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-4">
            {versionsFile.versions
              .filter((v) => v.metrics && ["v9", "v10", "v16"].includes(v.id))
              .map((v) => (
                <div
                  key={v.id}
                  className={`rounded-lg border p-4 bg-[var(--bg-surface)]/40 ${
                    v.status === "rejected"
                      ? "border-[var(--red)]/30"
                      : "border-[var(--border-soft)]"
                  }`}
                >
                  <div className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-2">
                    {v.id} · {v.status}
                  </div>
                  <MetricGrid
                    metrics={[
                      {
                        label: "Annual",
                        value: fmtPct(v.metrics!.annualized_return, 1),
                        tone:
                          v.metrics!.annualized_return !== null &&
                          v.metrics!.annualized_return >= 0.15
                            ? "good"
                            : "warn",
                      },
                      {
                        label: "Sharpe",
                        value: fmtNum(v.metrics!.sharpe, 2),
                        tone:
                          v.metrics!.sharpe !== null && v.metrics!.sharpe >= 0.8
                            ? "good"
                            : "warn",
                      },
                      {
                        label: "MaxDD",
                        value: fmtPct(v.metrics!.max_drawdown, 1),
                        tone: "bad",
                      },
                      {
                        label: "Win%",
                        value: fmtPct(v.metrics!.win_rate, 1),
                        tone: "neutral",
                      },
                    ]}
                  />
                </div>
              ))}
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Walk-Forward — 17 滚动窗口
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          每个窗口独立训练权重 → 样本外测 → 滚动。均值会被极端窗口拉偏，所以看中位数。
          v9 中位 Sharpe 0.5256 是本站采用它作为研究门面的主要依据。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Version</th>
                <th className="text-left px-4 py-3 font-normal">Design</th>
                <th className="text-right px-4 py-3 font-normal">Windows</th>
                <th className="text-right px-4 py-3 font-normal">Sharpe Mean</th>
                <th className="text-right px-4 py-3 font-normal">Sharpe Median</th>
                <th className="text-right px-4 py-3 font-normal">Win %</th>
                <th className="text-left px-4 py-3 font-normal">Verdict</th>
              </tr>
            </thead>
            <tbody>
              {WF_TABLE.map((r) => (
                <tr
                  key={r.version}
                  className={`border-b border-[var(--border-soft)] last:border-b-0 ${
                    r.highlight ? "bg-[var(--blue)]/[0.04]" : ""
                  } ${r.rejected ? "bg-[var(--red)]/[0.04]" : ""}`}
                >
                  <td className="px-4 py-3 font-mono font-semibold text-[var(--text-primary)]">
                    {r.version}
                  </td>
                  <td className="px-4 py-3 text-[var(--text-secondary)]">{r.label}</td>
                  <td className="px-4 py-3 text-right font-mono text-[var(--text-tertiary)]">
                    {r.windows}
                  </td>
                  <td className="px-4 py-3 text-right font-mono">{r.sharpe_mean.toFixed(4)}</td>
                  <td
                    className="px-4 py-3 text-right font-mono font-semibold"
                    style={{
                      color:
                        r.sharpe_median >= 0.5
                          ? "var(--green)"
                          : r.sharpe_median >= 0.3
                          ? "var(--gold)"
                          : r.sharpe_median <= 0.1
                          ? "var(--red)"
                          : "var(--text-primary)",
                    }}
                  >
                    {r.sharpe_median.toFixed(4)}
                  </td>
                  <td className="px-4 py-3 text-right font-mono text-[var(--text-tertiary)]">
                    {(r.win_rate * 100).toFixed(0)}%
                  </td>
                  <td
                    className="px-4 py-3 text-xs font-mono"
                    style={{
                      color: r.rejected
                        ? "var(--red)"
                        : r.highlight
                        ? "var(--blue)"
                        : "var(--text-tertiary)",
                    }}
                  >
                    {r.verdict}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          为什么 v10 的止损在 OOS 毁掉策略
        </h2>
        <div className="rounded-lg border border-[var(--red)]/30 bg-[var(--red)]/[0.04] p-6 space-y-4">
          <ReasonRow
            color="red"
            n={1}
            title="−8% 阈值在 2025 反复触发"
            body="2025 行情快速回调+快速反弹（&ldquo;假摔&rdquo;），−8% 门槛容易触发降仓，然后错过反弹。"
          />
          <ReasonRow
            color="red"
            n={2}
            title="降仓 50% 后恢复条件太苛刻"
            body="要求净值创新高才恢复满仓 — 震荡市里长期半仓，损耗大量潜在收益。"
          />
          <ReasonRow
            color="red"
            n={3}
            title="IS 好看但掩盖 OOS 风险"
            body="IS 含 2015/2018 大熊市，止损救回 18pp 的回撤（−42% → −24%），于是 IS 夏普从 0.65 涨到 0.84。但这种&ldquo;一刀切&rdquo;阈值无法区分真熊市和短期回调。"
          />
          <ReasonRow
            color="red"
            n={4}
            title="WF 也印证"
            body="17 窗口滚动，中位 Sharpe 从 v9 的 0.53 掉到 v10 的 0.46。样本外平均表现更差，不是偶然。"
          />
          <div className="text-xs font-mono text-[var(--text-tertiary)] pt-2 border-t border-[var(--red)]/20">
            完整报告 → journal/v10_icir_stoploss_eval_20260416.md
          </div>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          为什么 v16 不能 promote 到 live
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          v16 是 2026-04-14 因子挖掘会话生成的 11 个候选里按
          <span className="font-mono"> in-sample sharpe </span>
          最高的那个。&ldquo;赢家&rdquo;这两个字本身就是 v10 当初被否决的同一类陷阱。
        </p>
        <div className="rounded-lg border border-[var(--gold)]/35 bg-[var(--gold)]/[0.04] p-6 space-y-4">
          <ReasonRow
            color="gold"
            n={1}
            title="回撤 −43% 直接违反 CLAUDE.md 红线"
            body="admission gate 写的是 &lt; 30%。v16 不是边缘违反，是超过红线 13pp。这一条就足以拦住。"
          />
          <ReasonRow
            color="gold"
            n={2}
            title="Sharpe 0.73 未达 0.8 门槛"
            body="即便按 IS 最友好的口径算，仍然不够。v10 的 IS sharpe 0.84 都过了门槛还是被 WF 否决 — v16 在门槛外更没资格直接上 live。"
          />
          <ReasonRow
            color="gold"
            n={3}
            title="Best-in-sample 选择偏差"
            body="挖掘会话从 11 个候选里挑 sharpe 最高那个，和&ldquo;跑 50 个因子挑 best p-value&rdquo;没有本质区别。前 5 名 sharpe 差距在 0.05 以内，这种窄分布更像在同一份数据上过拟合到不同相位。"
          />
          <ReasonRow
            color="gold"
            n={4}
            title="WF 17 窗口还没跑"
            body="这是最硬的一条。v9 成为 face 的直接依据就是 WF 中位 0.53。v16 没有这个数 — 等于 v10 当初被否决前的状态。"
          />
          <ReasonRow
            color="gold"
            n={5}
            title="OOS 样本都没出过"
            body="v16 的回测区间是 2022-01 → 2025-12 全 IS。连 2025 OOS 检验都没做过，更谈不上通过。"
          />
          <div className="text-xs font-mono text-[var(--text-tertiary)] pt-2 border-t border-[var(--gold)]/25">
            下一步 → 对 top 3 候选 (不只是 v16) 跑 scripts/walk_forward.py ·
            <span className="ml-1">看 11 个候选对比 /strategy/candidates</span>
          </div>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Week 6 · 更多否决
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
          Multi-factor 线外的拒绝 — 差异化因子探索 + 事件驱动 + spec 层决策.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <RejectionCard
            date="2026-04-22"
            tag="Factor research"
            title="MD&A drift (Tier 1b) KILL"
            body="subset 500 × 8 年 PDF 跑完 MD&A 段余弦距离 vs 20d fwd return. Spearman rank IC 0.0036 << 0.015 pre-reg 门槛. 方向符号存在 (post-2023 +0.0075), 但幅度不足.
                  决策: 不再 Tier 2 (LLM hedging 增量). 数据源本身 marginal, 换方向."
            color="red"
          />
          <RejectionCard
            date="2026-04-22"
            tag="Factor research"
            title="BGFD fade 假设反向"
            body="原假设: 券商金股榜过度集中 → fade. 实测: Long consensus OOS 2025 Sharpe +2.23, Short crowded 2025 Ann -44%.
                  启示: 2024-2025 是 follow smart money 的 regime, 不是 fade retail crowd."
            color="gold"
          />
          <RejectionCard
            date="2026-04-22"
            tag="Factor research"
            title="MFD 反转假设证伪"
            body="原假设: elg (超大单) 净流入 → bullish 反转. 实测: IC -0.020 (方向反了), 单独不过门槛.
                  启示: 2025 量化化程度上升后, elg 更可能是 informed selling 伪装, 跟单散户接盘."
            color="gold"
          />
          <RejectionCard
            date="2026-04-23"
            tag="Paper-trade spec"
            title="spec v4 (RIAD + DSR#30 合成) 否决"
            body="合成 4/5 pass (SR 1.87 · DSR 0.920) 是用 baseline (不可执行) 版本算的. Filtered universe (真实融券约束) 下 RIAD OOS 2025 Sharpe -0.59, WF Fold 3 -1.56. DSR 0.920 < 0.95 红线.
                  决策: 继续跑 v3 BB-only 单腿, RIAD 放 shadow mode 跑 6 个月再评估."
            color="red"
          />
        </div>
      </section>
    </>
  );
}

function RejectionCard({
  date,
  tag,
  title,
  body,
  color,
}: {
  date: string;
  tag: string;
  title: string;
  body: string;
  color: "red" | "gold";
}) {
  const colorVar = color === "gold" ? "var(--gold)" : "var(--red)";
  return (
    <article
      className="rounded-lg border p-5"
      style={{
        borderColor: `color-mix(in srgb, ${colorVar} 30%, transparent)`,
        background: `color-mix(in srgb, ${colorVar} 4%, transparent)`,
      }}
    >
      <div className="flex items-baseline gap-3 mb-2">
        <span
          className="text-[10px] font-mono uppercase tracking-[0.15em]"
          style={{ color: colorVar }}
        >
          {tag}
        </span>
        <span className="text-[10px] font-mono text-[var(--text-tertiary)] ml-auto">
          {date}
        </span>
      </div>
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
        {title}
      </h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed whitespace-pre-line">
        {body}
      </p>
    </article>
  );
}

function GateCell({
  cell,
}: {
  cell: { value: string; pass: boolean; note?: string };
}) {
  return (
    <td className="px-4 py-3">
      <div
        className="font-mono text-sm"
        style={{ color: cell.pass ? "var(--green)" : "var(--red)" }}
      >
        {cell.pass ? "✓" : "✗"} {cell.value}
      </div>
      {cell.note && (
        <div className="text-[10px] text-[var(--text-tertiary)] mt-0.5">
          {cell.note}
        </div>
      )}
    </td>
  );
}

function ReasonRow({
  n,
  title,
  body,
  color = "red",
}: {
  n: number;
  title: string;
  body: string;
  color?: "red" | "gold";
}) {
  const colorVar = color === "gold" ? "var(--gold)" : "var(--red)";
  return (
    <div className="flex gap-4">
      <div
        className="shrink-0 w-7 h-7 rounded-full bg-[var(--bg-surface)] flex items-center justify-center text-xs font-mono"
        style={{ borderColor: colorVar, color: colorVar, borderWidth: 1 }}
      >
        {n}
      </div>
      <div className="min-w-0">
        <p className="text-sm font-semibold text-[var(--text-primary)]">{title}</p>
        <p className="text-sm text-[var(--text-secondary)] leading-relaxed mt-0.5">
          {body}
        </p>
      </div>
    </div>
  );
}
