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
  },
  {
    metric: "夏普比率",
    threshold: "> 0.8",
    v9: { value: "0.6417", pass: false },
    v10: { value: "0.8426", pass: true },
  },
  {
    metric: "最大回撤",
    threshold: "< 30%",
    v9: { value: "-41.92%", pass: false, note: "IS 含 2015/2018 熊市" },
    v10: { value: "-23.64%", pass: true },
  },
  {
    metric: "WF 夏普中位数",
    threshold: "> 0.20",
    v9: { value: "0.5256", pass: true },
    v10: { value: "0.4555", pass: true },
  },
  {
    metric: "OOS Sharpe (2025)",
    threshold: "承诺 ≥ IS",
    v9: { value: "1.6005", pass: true, note: "↑ 2.5x vs IS" },
    v10: { value: "0.2749", pass: false, note: "↓ 从 IS 0.84 掉到 0.27" },
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
      label: "v9 · ICIR 研究门面",
      color: "var(--blue)",
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
      label: "v16 · 9 因子生产",
      color: "var(--green)",
      curve: v16Curve,
    },
  ].filter((s): s is NonNullable<typeof s> => s !== null);

  return (
    <>
      <PageHeader
        eyebrow="Validation · 验证"
        title="Walk-Forward & Honest Failure"
        subtitle="Rolling 17 windows · IS vs OOS · admission gate"
        description="所有策略必须过 4 条 admission gate 才能上 live。v10 在 IS 看起来完美（回撤 -24%、夏普 0.84），但 OOS 把超额砍光 — 这是本站最重要的一页：展示诚实证伪过程。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Validation" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Admission Gate — v9 vs v10
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          策略进入 live 前必须过的四条硬门槛。v10 在 IS 通过 3/4，但 OOS Sharpe 0.27 直接否决。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Metric</th>
                <th className="text-left px-4 py-3 font-normal">Threshold</th>
                <th className="text-left px-4 py-3 font-normal">v9 (IS)</th>
                <th className="text-left px-4 py-3 font-normal">v10 (IS)</th>
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

      <section className="max-w-content mx-auto px-6 pb-24">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          为什么 v10 的止损在 OOS 毁掉策略
        </h2>
        <div className="rounded-lg border border-[var(--red)]/30 bg-[var(--red)]/[0.04] p-6 space-y-4">
          <ReasonRow
            n={1}
            title="−8% 阈值在 2025 反复触发"
            body="2025 行情快速回调+快速反弹（&ldquo;假摔&rdquo;），−8% 门槛容易触发降仓，然后错过反弹。"
          />
          <ReasonRow
            n={2}
            title="降仓 50% 后恢复条件太苛刻"
            body="要求净值创新高才恢复满仓 — 震荡市里长期半仓，损耗大量潜在收益。"
          />
          <ReasonRow
            n={3}
            title="IS 好看但掩盖 OOS 风险"
            body="IS 含 2015/2018 大熊市，止损救回 18pp 的回撤（−42% → −24%），于是 IS 夏普从 0.65 涨到 0.84。但这种&ldquo;一刀切&rdquo;阈值无法区分真熊市和短期回调。"
          />
          <ReasonRow
            n={4}
            title="WF 也印证"
            body="17 窗口滚动，中位 Sharpe 从 v9 的 0.53 掉到 v10 的 0.46。样本外平均表现更差，不是偶然。"
          />
          <div className="text-xs font-mono text-[var(--text-tertiary)] pt-2 border-t border-[var(--red)]/20">
            完整报告 → journal/v10_icir_stoploss_eval_20260416.md
          </div>
        </div>
      </section>
    </>
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
}: {
  n: number;
  title: string;
  body: string;
}) {
  return (
    <div className="flex gap-4">
      <div className="shrink-0 w-7 h-7 rounded-full border border-[var(--red)]/40 bg-[var(--bg-surface)] flex items-center justify-center text-xs font-mono text-[var(--red)]">
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
