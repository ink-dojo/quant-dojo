import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
} from "@/components/layout/Primitives";
import { Lang } from "@/components/layout/LanguageText";
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
        eyebrow="Validation"
        title={<Lang zh="否决档案" en="Rejection files" />}
        subtitle={<Lang zh="Gate 失败 · OOS 断裂 · 不可执行 spec" en="Gate failures · OOS breaks · non-executable specs" />}
        description={<Lang zh="被否决的工作保留可见，但默认视图只是索引。展开 case 查看精确指标和来源说明。" en="Rejected work stays visible, but the default view is an index. Open a case for exact metrics and source notes." />}
        crumbs={[{ label: "Home", href: "/" }, { label: "Validation" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-16">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard
            tone="red"
            label="v10"
            value="OOS break"
            detail={<Lang zh="止损层降低了 IS 回撤，但破坏了 OOS。" en="Stop-loss layer reduced IS drawdown and damaged OOS." />}
          />
          <EvidenceCard
            tone="gold"
            label="v16"
            value="-43% DD"
            detail={<Lang zh="IS 收益高，但回撤和 WF 要求未过。" en="High IS return, but failed drawdown and WF requirements." />}
          />
          <EvidenceCard
            tone="red"
            label="RIAD combo"
            value={<Lang zh="已阻塞" en="Blocked" />}
            detail={<Lang zh="Baseline 结果没有经受住可执行约束。" en="Baseline result did not survive executable constraints." />}
          />
          <EvidenceCard
            tone="red"
            label="MD&A drift"
            value="IC 0.0036"
            detail={<Lang zh="低于预注册门槛；跳过 Tier 2。" en="Below pre-registered threshold; Tier 2 skipped." />}
          />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-12">
        <SectionLabel
          eyebrow={<Lang zh="Gate 矩阵" en="Gate matrix" />}
          title={<Lang zh="策略 gate 对比" en="Strategy gate comparison" />}
          body={<Lang zh="需要精确值时再展开。它是支持证据，不是页面装饰。" en="Open for exact values. This is supporting evidence, not page furniture." />}
        />
        <DisclosurePanel
          tone="neutral"
          title="Admission gate — v9 / v10 / v16"
          summary={<Lang zh="v10 OOS 失败；v16 被回撤和缺失 WF 拦住。" en="v10 fails OOS; v16 is blocked by drawdown and missing WF." />}
        >
          <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-soft)] text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                  <th className="px-4 py-3 text-left font-normal"><Lang zh="指标" en="Metric" /></th>
                  <th className="px-4 py-3 text-left font-normal"><Lang zh="门槛" en="Threshold" /></th>
                  <th className="px-4 py-3 text-left font-normal text-[var(--green)]">v9</th>
                  <th className="px-4 py-3 text-left font-normal text-[var(--red)]">v10</th>
                  <th className="px-4 py-3 text-left font-normal text-[var(--gold)]">v16</th>
                </tr>
              </thead>
              <tbody>
                {ADMISSION_GATE.map((row, i) => (
                  <tr key={i} className="border-b border-[var(--border-soft)] last:border-b-0">
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
        </DisclosurePanel>
      </section>

      {series.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <DisclosurePanel
            tone="blue"
            title={<Lang zh="净值对比和指标卡" en="Equity overlay and metric cards" />}
            summary={<Lang zh="只有需要图表级对比时再打开。" en="Open only if you need chart-level comparison." />}
          >
            <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/40 p-4">
              <EquityChart series={series} height={360} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-4 md:grid-cols-3">
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
                    <div className="mb-2 text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                      {v.id} · {v.status}
                    </div>
                    <MetricGrid
                      metrics={[
                        { label: "Annual", value: fmtPct(v.metrics!.annualized_return, 1) },
                        { label: "Sharpe", value: fmtNum(v.metrics!.sharpe, 2) },
                        { label: "MaxDD", value: fmtPct(v.metrics!.max_drawdown, 1), tone: "bad" },
                        { label: "Win%", value: fmtPct(v.metrics!.win_rate, 1) },
                      ]}
                    />
                  </div>
                ))}
            </div>
          </DisclosurePanel>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <DisclosurePanel
          tone="blue"
          title={<Lang zh="Walk-forward 表" en="Walk-forward table" />}
          summary={<Lang zh="17 个滚动窗口；中位 Sharpe 是对比锚点。" en="17 rolling windows; median Sharpe is the comparison anchor." />}
        >
          <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-[var(--border-soft)] text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)]">
                  <th className="px-4 py-3 text-left font-normal"><Lang zh="版本" en="Version" /></th>
                  <th className="px-4 py-3 text-left font-normal"><Lang zh="设计" en="Design" /></th>
                  <th className="px-4 py-3 text-right font-normal">Windows</th>
                  <th className="px-4 py-3 text-right font-normal">Mean</th>
                  <th className="px-4 py-3 text-right font-normal">Median</th>
                  <th className="px-4 py-3 text-right font-normal">Win %</th>
                  <th className="px-4 py-3 text-left font-normal">Verdict</th>
                </tr>
              </thead>
              <tbody>
                {WF_TABLE.map((r) => (
                  <tr key={r.version} className="border-b border-[var(--border-soft)] last:border-b-0">
                    <td className="px-4 py-3 font-mono font-semibold text-[var(--text-primary)]">{r.version}</td>
                    <td className="px-4 py-3 text-[var(--text-secondary)]">{r.label}</td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--text-tertiary)]">{r.windows}</td>
                    <td className="px-4 py-3 text-right font-mono">{r.sharpe_mean.toFixed(4)}</td>
                    <td className="px-4 py-3 text-right font-mono font-semibold">{r.sharpe_median.toFixed(4)}</td>
                    <td className="px-4 py-3 text-right font-mono text-[var(--text-tertiary)]">{(r.win_rate * 100).toFixed(0)}%</td>
                    <td className="px-4 py-3 text-xs font-mono text-[var(--text-tertiary)]">{r.verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </DisclosurePanel>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <DisclosurePanel
          tone="red"
          title={<Lang zh="Case：v10 止损层 OOS 失败" en="Case: v10 stop-loss failed OOS" />}
          summary={<Lang zh="它改善了样本内回撤，但砍掉了样本外收益。" en="The layer improved in-sample drawdown and cut away out-of-sample upside." />}
        >
          <div className="space-y-4">
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
        </DisclosurePanel>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <DisclosurePanel
          tone="gold"
          title={<Lang zh="Case：v16 仍是候选" en="Case: v16 remains candidate" />}
          summary={<Lang zh="一次挖掘会话里的 best，但回撤破线且缺少 WF。" en="Best in one mining session, but drawdown breached the gate and WF was missing." />}
        >
          <div className="space-y-4">
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
        </DisclosurePanel>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <DisclosurePanel
          tone="red"
          title="Other Week 6 rejections"
          summary="Factor kills, reversed hypotheses, and blocked paper-trade specs."
        >
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <RejectionCard
              date="2026-04-22"
              tag="Factor research"
              title="MD&A drift (Tier 1b) KILL"
              body="Spearman rank IC 0.0036 << 0.015 pre-reg threshold. Tier 2 skipped."
              color="red"
            />
            <RejectionCard
              date="2026-04-22"
              tag="Factor research"
              title="BGFD fade hypothesis reversed"
              body="Fade crowded broker picks failed; long consensus was the side that worked in 2025."
              color="gold"
            />
            <RejectionCard
              date="2026-04-22"
              tag="Factor research"
              title="MFD reversal failed"
              body="IC was negative and the standalone factor did not pass gate."
              color="gold"
            />
            <RejectionCard
              date="2026-04-23"
              tag="Paper-trade spec"
              title="spec v4 RIAD combo blocked"
              body="Baseline combo passed several gates, but executable RIAD constraints broke the result."
              color="red"
            />
          </div>
        </DisclosurePanel>
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
