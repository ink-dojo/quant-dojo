import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtNum, fmtPct } from "@/lib/formatters";
import type {
  CandidatesFile,
  CandidateRow,
  CandidateReviewFile,
  CandidateReviewRow,
} from "@/lib/types";

export default async function CandidatesPage() {
  const [file, review] = await Promise.all([
    readData<CandidatesFile>("strategy/candidates.json"),
    readDataOrNull<CandidateReviewFile>("strategy/candidate_review.json"),
  ]);

  const ranked = [...file.candidates].sort(
    (a, b) =>
      (b.sharpe ?? -Infinity) - (a.sharpe ?? -Infinity)
  );

  const selectedRank =
    ranked.findIndex((r) => r.id === file.selected) + 1 || null;

  const reviewByVersion = new Map(
    (review?.candidates ?? []).map((r) => [r.version, r])
  );
  const selectedReview = review
    ? review.candidates.find((r) => r.version === file.selected)
    : null;
  const topByDsr = review ? review.candidates[0] : null;

  return (
    <>
      <PageHeader
        eyebrow={`Week 5 · ${file.session_date}`}
        title="Mining round · 11 个候选按 sharpe 排序"
        subtitle="同一份数据跑 11 个 variant, 挑 best-in-sample = 选择偏差. DSR 负责记账."
        description="Week 5 的一次因子挖掘 session: 9 因子不同替换组合跑 11 个 multi-factor variant, 全在同一份 IS 上. 按 sharpe 排序, 前 3 名差距 0.01 级别 — deflated sharpe + walk-forward 才是真正能区分 alpha 和噪声的工具."
        crumbs={[
          { label: "Home", href: "/" },
          { label: "Strategy", href: "/strategy" },
          { label: "Candidates" },
        ]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="max-w-3xl space-y-4 text-[var(--text-secondary)] leading-relaxed text-sm">
          <p>{file.session_note}</p>
          <p>
            下面是 11 个候选按 <span className="font-mono">in-sample sharpe</span>{" "}
            降序排列。
            <span className="text-[var(--gold)] font-semibold">
              v16 排在第 {selectedRank ?? "—"} 名
            </span>
            ，从这个角度看它是&ldquo;赢家&rdquo; — 但第 1、2、3
            名的差距是 0.01 级别的噪声。
          </p>
          <p className="text-[var(--text-tertiary)] italic">
            从 12 个候选里挑 sharpe 最高那个，和把 50 个因子各跑一遍挑 best
            p-value 没有本质区别。真正能区分 alpha 和噪声的是{" "}
            <span className="not-italic text-[var(--text-secondary)]">
              deflated sharpe（对多重检验做修正）
            </span>
            和样本外 walk-forward 检验。
          </p>
        </div>
      </section>

      {review && selectedReview && topByDsr && (
        <section className="max-w-content mx-auto px-6 pb-12">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
            Deflated Sharpe Review · {review.generated_at}
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-5 max-w-3xl leading-relaxed">
            对 {review.n_candidates} 个候选一视同仁地计算了 PSR 和 DSR。
            PSR 回答&ldquo;夏普显著大于零的概率&rdquo;，DSR 额外扣除&ldquo;从
            {review.n_candidates} 个挑最高&rdquo;的选择偏差。
          </p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            <ReviewStatCard
              tag="选择偏差修正"
              headline={`${fmtPct(selectedReview.dsr, 1)} DSR`}
              body={`v16 的 sharpe 0.740 在多重检验修正后仍有 ${fmtPct(selectedReview.dsr, 0)} 概率显著 > 0。`}
              tone="gold"
            />
            <ReviewStatCard
              tag="Admission gate"
              headline={
                selectedReview.gate.all_pass
                  ? "✓ 全通过"
                  : "✗ 未全通过"
              }
              body={`${[
                selectedReview.gate.ann_return_ge_15pct ? "年化✓" : "年化✗",
                selectedReview.gate.sharpe_ge_08 ? "Sharpe✓" : "Sharpe✗",
                selectedReview.gate.max_dd_gt_neg30pct ? "回撤✓" : "回撤✗",
                selectedReview.gate.psr_ge_95pct ? "PSR✓" : "PSR✗",
              ].join(" · ")}. 回撤 ${fmtPct(selectedReview.max_drawdown, 1)} 超 30% 红线。`}
              tone={selectedReview.gate.all_pass ? "green" : "red"}
            />
            <ReviewStatCard
              tag="Bootstrap 95% CI"
              headline={`[${fmtNum(selectedReview.sharpe_ci_low, 2)}, ${fmtNum(selectedReview.sharpe_ci_high, 2)}]`}
              body="Stationary block resample 保留日收益自相关。CI 下沿若 < 0.8 意味着 &ldquo;sharpe 过门槛&rdquo; 不稳健。"
              tone="gold"
            />
          </div>
          <div className="mt-6 overflow-x-auto rounded-lg border border-[var(--border-soft)]">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                  <th className="text-left px-3 py-3 font-normal w-10">#</th>
                  <th className="text-left px-3 py-3 font-normal">Version</th>
                  <th className="text-right px-3 py-3 font-normal">Sharpe</th>
                  <th className="text-right px-3 py-3 font-normal">CI(95%)</th>
                  <th className="text-right px-3 py-3 font-normal">PSR</th>
                  <th className="text-right px-3 py-3 font-normal">DSR</th>
                  <th className="text-right px-3 py-3 font-normal">Ann.</th>
                  <th className="text-right px-3 py-3 font-normal">MaxDD</th>
                  <th className="text-center px-3 py-3 font-normal">Gate</th>
                </tr>
              </thead>
              <tbody>
                {review.candidates.map((row, i) => (
                  <ReviewRowView
                    key={row.version}
                    row={row}
                    rank={i + 1}
                    selected={row.version === file.selected}
                  />
                ))}
              </tbody>
            </table>
          </div>
          <p className="mt-3 text-xs text-[var(--text-tertiary)] leading-relaxed max-w-3xl">
            pool 内 sharpe 标准差 σ = {fmtNum(review.selection_pool_sharpe_std, 3)} — 候选分布很窄，
            DSR 与 PSR 差距小。等 WF 17 窗口跑完后，用 WF 中位 sharpe 重新排序。
          </p>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
          原始 IS 排序（按 sharpe 降序）
        </h2>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-3 py-3 font-normal w-10">#</th>
                <th className="text-left px-3 py-3 font-normal">Version</th>
                <th className="text-left px-3 py-3 font-normal">改动</th>
                <th className="text-right px-3 py-3 font-normal">年化</th>
                <th className="text-right px-3 py-3 font-normal">Sharpe</th>
                <th className="text-right px-3 py-3 font-normal">MaxDD</th>
                <th className="text-right px-3 py-3 font-normal">胜率</th>
                <th className="text-center px-3 py-3 font-normal">Gate</th>
              </tr>
            </thead>
            <tbody>
              {ranked.map((row, i) => (
                <CandidateRowView
                  key={row.id}
                  row={row}
                  rank={i + 1}
                  selected={row.id === file.selected}
                  review={reviewByVersion.get(row.id)}
                />
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Takeaway
            title="分布窄 ≠ 每个都是 alpha"
            body="前 5 名的 sharpe 差距在 0.05 之内。如果真是因子信号强弱的体现，差距应该更悬殊。这样的窄分布更可能是在同一份数据上过拟合到不同相位。DSR 排名与 sharpe 排名几乎相同，因为 pool σ 很小——选 top 1 不比选 top 3 更可信。"
          />
          <Takeaway
            title="下一步 — 跑 walk-forward"
            body="把 top 3 候选（不只是 v16）喂给 scripts/walk_forward.py 跑 17 个滚动窗口，看中位 sharpe 和稳定性。只有在 WF 下表现稳定的才有资格进入 paper-trade review。此外所有候选都没过回撤红线，说明 admission gate 的瓶颈不是因子，而是风险管理。"
          />
        </div>
        <div className="mt-6 text-xs text-[var(--text-tertiary)]">
          原始数据来源：
          <code className="font-mono">live/runs/multi_factor_v*_*.json</code> ·
          DSR/PSR 计算：
          <code className="font-mono">scripts/batch_candidate_review.py</code>
        </div>
        <div className="mt-6">
          <Link
            href="/strategy"
            className="text-sm text-[var(--blue)] hover:underline"
          >
            ← 回到策略演化主线
          </Link>
        </div>
      </section>
    </>
  );
}

function ReviewStatCard({
  tag,
  headline,
  body,
  tone,
}: {
  tag: string;
  headline: string;
  body: string;
  tone: "green" | "gold" | "red";
}) {
  const color =
    tone === "green"
      ? "var(--green)"
      : tone === "gold"
      ? "var(--gold)"
      : "var(--red)";
  return (
    <div
      className="rounded-lg border p-4"
      style={{
        borderColor: `color-mix(in srgb, ${color} 30%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <p
        className="text-[10px] font-mono uppercase tracking-[0.15em] mb-1"
        style={{ color }}
      >
        {tag}
      </p>
      <p
        className="text-2xl font-mono font-semibold mb-2"
        style={{ color }}
      >
        {headline}
      </p>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
        {body}
      </p>
    </div>
  );
}

function ReviewRowView({
  row,
  rank,
  selected,
}: {
  row: CandidateReviewRow;
  rank: number;
  selected: boolean;
}) {
  return (
    <tr
      className={`border-b border-[var(--border-soft)] last:border-b-0 ${
        selected ? "bg-[var(--gold)]/[0.08]" : ""
      }`}
    >
      <td className="px-3 py-3 font-mono text-[var(--text-tertiary)]">
        {rank}
      </td>
      <td className="px-3 py-3 font-mono font-semibold text-[var(--text-primary)]">
        {row.version}
        {selected && (
          <span className="ml-2 text-[10px] font-mono text-[var(--gold)] uppercase tracking-[0.15em]">
            selected
          </span>
        )}
      </td>
      <td
        className="px-3 py-3 text-right font-mono"
        style={{ color: row.sharpe >= 0.8 ? "var(--green)" : "var(--text-primary)" }}
      >
        {fmtNum(row.sharpe, 3)}
      </td>
      <td className="px-3 py-3 text-right font-mono text-xs text-[var(--text-tertiary)]">
        [{fmtNum(row.sharpe_ci_low, 2)}, {fmtNum(row.sharpe_ci_high, 2)}]
      </td>
      <td
        className="px-3 py-3 text-right font-mono text-xs"
        style={{ color: row.psr_vs_zero >= 0.95 ? "var(--green)" : "var(--gold)" }}
      >
        {fmtPct(row.psr_vs_zero, 1)}
      </td>
      <td
        className="px-3 py-3 text-right font-mono text-xs"
        style={{ color: row.dsr >= 0.95 ? "var(--green)" : row.dsr >= 0.5 ? "var(--gold)" : "var(--red)" }}
      >
        {fmtPct(row.dsr, 1)}
      </td>
      <td className="px-3 py-3 text-right font-mono text-xs text-[var(--text-secondary)]">
        {fmtPct(row.ann_return, 1)}
      </td>
      <td
        className="px-3 py-3 text-right font-mono text-xs"
        style={{
          color: row.max_drawdown > -0.3 ? "var(--green)" : "var(--red)",
        }}
      >
        {fmtPct(row.max_drawdown, 1)}
      </td>
      <td className="px-3 py-3 text-center font-mono text-xs">
        <span style={{ color: row.gate.all_pass ? "var(--green)" : "var(--red)" }}>
          {row.gate.all_pass ? "✓" : "✗"}
        </span>
      </td>
    </tr>
  );
}

function CandidateRowView({
  row,
  rank,
  selected,
  review,
}: {
  row: CandidateRow;
  rank: number;
  selected: boolean;
  review?: CandidateReviewRow;
}) {
  const sharpePass = (row.sharpe ?? 0) >= 0.8;
  const ddPass = (row.max_drawdown ?? 0) > -0.3;
  const annPass = (row.annualized_return ?? 0) >= 0.15;
  const gatePass = sharpePass && ddPass && annPass && (review?.gate.psr_ge_95pct ?? false);

  return (
    <tr
      className={`border-b border-[var(--border-soft)] last:border-b-0 ${
        selected ? "bg-[var(--gold)]/[0.08]" : ""
      }`}
    >
      <td className="px-3 py-3 font-mono text-[var(--text-tertiary)]">
        {rank}
      </td>
      <td className="px-3 py-3 font-mono font-semibold text-[var(--text-primary)]">
        {row.id}
        {selected && (
          <span className="ml-2 text-[10px] font-mono text-[var(--gold)] uppercase tracking-[0.15em]">
            selected
          </span>
        )}
      </td>
      <td className="px-3 py-3 text-xs text-[var(--text-secondary)]">
        {row.change_zh}
      </td>
      <td
        className="px-3 py-3 text-right font-mono"
        style={{ color: annPass ? "var(--green)" : "var(--text-secondary)" }}
      >
        {fmtPct(row.annualized_return, 1)}
      </td>
      <td
        className="px-3 py-3 text-right font-mono"
        style={{ color: sharpePass ? "var(--green)" : "var(--gold)" }}
      >
        {fmtNum(row.sharpe, 3)}
      </td>
      <td
        className="px-3 py-3 text-right font-mono"
        style={{ color: ddPass ? "var(--green)" : "var(--red)" }}
      >
        {fmtPct(row.max_drawdown, 1)}
      </td>
      <td className="px-3 py-3 text-right font-mono text-[var(--text-secondary)]">
        {fmtPct(row.win_rate, 1)}
      </td>
      <td className="px-3 py-3 text-center font-mono text-xs">
        <span style={{ color: gatePass ? "var(--green)" : "var(--red)" }}>
          {gatePass ? "✓ pass" : "✗ fail"}
        </span>
      </td>
    </tr>
  );
}

function Takeaway({ title, body }: { title: string; body: string }) {
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
      <h3 className="text-sm font-semibold text-[var(--text-primary)] mb-2">
        {title}
      </h3>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
        {body}
      </p>
    </div>
  );
}
