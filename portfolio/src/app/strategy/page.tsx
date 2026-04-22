import Link from "next/link";
import { PageHeader } from "@/components/layout/PageHeader";
import { MetricGrid } from "@/components/viz/MetricGrid";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  GateCheck,
  StrategyStatus,
  StrategyVersion,
  StrategyVersionsFile,
} from "@/lib/types";

const STATUS_STYLE: Record<
  StrategyStatus,
  { label: string; color: string; bg: string }
> = {
  legacy: {
    label: "Legacy",
    color: "var(--text-tertiary)",
    bg: "rgba(148,163,184,0.12)",
  },
  "research-face": {
    label: "Research Face",
    color: "var(--blue)",
    bg: "rgba(59,130,246,0.12)",
  },
  candidate: {
    label: "Candidate · pending WF",
    color: "var(--gold)",
    bg: "rgba(234,179,8,0.12)",
  },
  rejected: {
    label: "Rejected",
    color: "var(--red)",
    bg: "rgba(239,68,68,0.1)",
  },
  production: {
    label: "Production Face",
    color: "var(--green)",
    bg: "rgba(34,197,94,0.12)",
  },
  running: {
    label: "Running",
    color: "var(--purple)",
    bg: "rgba(168,85,247,0.12)",
  },
};

const SERIES_COLORS: Record<string, string> = {
  v7: "var(--text-tertiary)",
  v9: "var(--green)",
  v10: "var(--red)",
  v16: "var(--gold)",
};

export default async function StrategyPage() {
  const versionsFile = await readData<StrategyVersionsFile>(
    "strategy/versions.json"
  );

  const equityFiles = await Promise.all(
    versionsFile.versions.map(async (v) =>
      v.equity_file
        ? {
            id: v.id,
            curve: await readDataOrNull<EquityCurveFile>(
              `strategy/${v.equity_file}`
            ),
          }
        : { id: v.id, curve: null }
    )
  );
  const equityById = new Map(
    equityFiles.filter((e) => e.curve !== null).map((e) => [e.id, e.curve!])
  );

  const series = versionsFile.versions
    .filter((v) => equityById.has(v.id))
    .map((v) => ({
      id: v.id,
      label: `${v.id} · ${v.name_zh}`,
      color: SERIES_COLORS[v.id] ?? "var(--cyan)",
      dashed: v.status === "rejected" || v.status === "candidate",
      curve: equityById.get(v.id)!,
    }));

  const face = versionsFile.versions.find(
    (v) => v.id === versionsFile.production_face
  );
  const candidate = versionsFile.versions.find(
    (v) => v.id === versionsFile.candidate
  );
  const rejected = versionsFile.versions.find((v) => v.status === "rejected");

  return (
    <>
      <PageHeader
        title="四代策略演化"
        subtitle="Four Generations: v7 → v9 → v10 → v16"
        crumbs={[{ label: "Home", href: "/" }, { label: "Strategy" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-10">
        <div className="max-w-3xl space-y-4 text-[var(--text-secondary)] leading-relaxed">
          <p>
            这个项目的主线不是任何单一版本的 sharpe，而是
            <span className="text-[var(--text-primary)]"> 纪律</span>
            ：什么样的策略配得上&ldquo;生产门面&rdquo;这四个字。
          </p>
          <p>
            从 v7 的 5 因子手工权重开始，v9 用 ICIR
            学习权重拿到了真正的样本外提升（中位 sharpe 0.53、OOS +18%），成为
            <Link
              href="#v9"
              className="text-[var(--green)] font-semibold hover:underline"
            >
              实际生产门面
            </Link>
            。v10 试图叠加组合止损，IS 回撤看似缓解，却被我们自己的 walk-forward
            {" "}
            <Link
              href="/validation"
              className="text-[var(--red)] hover:underline"
            >
              证伪并否决
            </Link>
            。v16 是上周因子挖掘会话从 12 个候选里挑出的&ldquo;赢家&rdquo;——
            但它的选拔过程和 v10 的陷阱是一样的，
            {" "}
            <Link
              href="#v16"
              className="text-[var(--gold)] hover:underline"
            >
              仍是 candidate，不上 live
            </Link>
            。
          </p>
        </div>
      </section>

      {face && (
        <section className="max-w-content mx-auto px-6 pb-10">
          <FaceBanner version={face} />
          <p className="mt-3 text-xs text-[var(--text-tertiary)] leading-relaxed max-w-3xl">
            {versionsFile.face_note}
          </p>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-10">
        <Link
          href="/strategy/multi-factor"
          className="block rounded-lg border border-[var(--blue)]/35 bg-[var(--blue)]/[0.05] p-5 hover:bg-[var(--blue)]/[0.08] transition-colors"
        >
          <div className="flex items-baseline gap-2 mb-1">
            <span className="text-[10px] font-mono uppercase tracking-[0.18em] text-[var(--blue)]">
              Timeline · v7 → v25
            </span>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
              6 个时代 · 包括止损灾难 v10 和挖掘陷阱 v16
            </span>
          </div>
          <h3 className="text-lg font-semibold text-[var(--text-primary)] mb-1">
            完整演化时间线 + 逐版本深度页
          </h3>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            每一版本都记录动机 / 方法 / 结果 / 教训 / 触发下一版本的问题 —
            包含六次被证伪的诚实故事。
            <span className="text-[var(--blue)] ml-1">进入时间线 →</span>
          </p>
        </Link>
      </section>

      {series.length > 0 && (
        <section className="max-w-content mx-auto px-6 pb-16">
          <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
            Equity Overlay · 四条曲线同一坐标
          </h2>
          <p className="text-sm text-[var(--text-secondary)] mb-4 max-w-3xl">
            2022-01 → 2025-12 回测期。
            <span className="text-[var(--green)]">v9 实线</span> 是当前生产门面；
            <span className="text-[var(--red)]">v10 虚线</span> 被 admission gate 否决；
            <span className="text-[var(--gold)]">v16 虚线</span> 是挖掘候选（注意它总回报最高，但回撤深度 -43%）。
          </p>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-4">
            <EquityChart series={series} height={380} />
          </div>
          <div className="mt-3 grid grid-cols-1 md:grid-cols-3 gap-3 text-xs">
            <ReadingHint
              color="var(--green)"
              title="v9 最关键的地方是平的部分"
              body="2023 风格切换期间小幅回落但未彻底破位，走平后继续上行 — 这是 WF 权重学习的贡献。"
            />
            <ReadingHint
              color="var(--red)"
              title="v10 的止损在 2022 年打断了动量"
              body="止损只有在有 regime 信号时才能救人。单纯用固定阈值，反而在反弹前清了仓。"
            />
            <ReadingHint
              color="var(--gold)"
              title="v16 总收益 +117% 最亮眼"
              body="但回撤 -43% 违反 CLAUDE.md 红线；sharpe 0.73 未达 0.8 门槛。这正是 overfitting 的样子。"
            />
          </div>
        </section>
      )}

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-2">
          Admission Gate · 纪律
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-3xl leading-relaxed">
          写在 <code className="font-mono text-xs text-[var(--text-primary)]">CLAUDE.md</code>
          {" "}里的、每个新策略必须过的 4 条线。没过，不能叫 production。
        </p>
        <div className="overflow-x-auto rounded-lg border border-[var(--border-soft)]">
          <table className="w-full text-sm">
            <thead>
              <tr className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] border-b border-[var(--border-soft)]">
                <th className="text-left px-4 py-3 font-normal">Gate</th>
                <th className="text-left px-4 py-3 font-normal">门槛</th>
                <th className="text-right px-4 py-3 font-normal">v9 · face</th>
                <th className="text-right px-4 py-3 font-normal">v10 · rejected</th>
                <th className="text-right px-4 py-3 font-normal">v16 · candidate</th>
              </tr>
            </thead>
            <tbody className="font-mono">
              <GateRow
                label="年化"
                threshold="> 15%"
                v9={face?.metrics?.annualized_return ?? null}
                v10={rejected?.metrics?.annualized_return ?? null}
                v16={candidate?.metrics?.annualized_return ?? null}
                format="pct"
                pass={(v) => (v ?? 0) >= 0.15}
              />
              <GateRow
                label="Sharpe"
                threshold="> 0.8"
                v9={face?.metrics?.sharpe ?? null}
                v10={rejected?.metrics?.sharpe ?? null}
                v16={candidate?.metrics?.sharpe ?? null}
                format="num"
                pass={(v) => (v ?? 0) >= 0.8}
              />
              <GateRow
                label="最大回撤"
                threshold="> -30%"
                v9={face?.metrics?.max_drawdown ?? null}
                v10={rejected?.metrics?.max_drawdown ?? null}
                v16={candidate?.metrics?.max_drawdown ?? null}
                format="pct"
                pass={(v) => (v ?? 0) > -0.3}
              />
              <tr className="border-t border-[var(--border-soft)]">
                <td className="px-4 py-3 text-[var(--text-primary)]">WF 已验证</td>
                <td className="px-4 py-3 text-[var(--text-tertiary)]">required</td>
                <td className="px-4 py-3 text-right text-[var(--green)]">
                  ✓ 中位 0.53
                </td>
                <td className="px-4 py-3 text-right text-[var(--red)]">
                  ✗ 中位 0.46
                </td>
                <td className="px-4 py-3 text-right text-[var(--red)]">
                  ✗ 未跑
                </td>
              </tr>
            </tbody>
          </table>
        </div>
        <p className="mt-3 text-xs text-[var(--text-tertiary)] leading-relaxed max-w-3xl">
          v9 是唯一四条都过的版本。v16 虽然年化最高，但回撤和 sharpe 两条未过，WF
          还没跑 — 所以它挂 <em>candidate</em> 而不是 production。
        </p>
      </section>

      <section id="versions" className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-2">
          Version Cards · 按时间
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6 max-w-3xl">
          每张卡片包含状态、同期指标、因子组成、被否决或被搁置的原因。
        </p>
        <ol className="relative border-l border-[var(--border-soft)] ml-2 space-y-6">
          {versionsFile.versions.map((v) => (
            <VersionCard key={v.id} version={v} />
          ))}
        </ol>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="rounded-lg border border-[var(--gold)]/30 bg-[var(--gold)]/[0.04] p-5">
          <h3 className="text-sm font-semibold text-[var(--gold)] mb-2">
            想看 v16 是怎么从 11 个候选里挑出来的？
          </h3>
          <p className="text-xs text-[var(--text-secondary)] leading-relaxed mb-3">
            2026-04-14 的因子挖掘会话生成了 v11–v21 共 11 个多因子策略。把它们全部
            sharpe 排序后，你会发现 v16
            并不是孤立的最优解，而是 best-in-sample — 这正是 v10 当初被否决的同一类陷阱。
          </p>
          <Link
            href="/strategy/candidates"
            className="inline-block text-xs font-mono text-[var(--gold)] hover:underline"
          >
            看完整的 11 个候选对比 →
          </Link>
        </div>
      </section>
    </>
  );
}

function FaceBanner({ version }: { version: StrategyVersion }) {
  const m = version.metrics;
  return (
    <div className="rounded-lg border border-[var(--green)]/40 bg-[var(--green)]/[0.05] p-5">
      <div className="flex flex-wrap items-center gap-3 mb-3">
        <span className="inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.18em] text-[var(--green)]">
          <span className="w-2 h-2 rounded-full bg-[var(--green)]" />
          Production Face · 实际生产门面
        </span>
        <span className="text-sm font-semibold text-[var(--text-primary)]">
          {version.id} · {version.name_en}
        </span>
        <span className="text-xs font-mono text-[var(--text-tertiary)]">
          {version.factors.length} factors · WF validated
        </span>
      </div>
      {m && (
        <div className="mt-3">
          <MetricGrid
            metrics={[
              {
                label: "年化",
                value: fmtPct(m.annualized_return, 1),
                tone: "good",
              },
              {
                label: "Sharpe",
                value: fmtNum(m.sharpe, 3),
                tone: (m.sharpe ?? 0) >= 0.8 ? "good" : "warn",
                hint: "WF 中位 0.53",
              },
              {
                label: "Max DD",
                value: fmtPct(m.max_drawdown, 1),
                tone: (m.max_drawdown ?? 0) > -0.3 ? "good" : "warn",
              },
              {
                label: "Win Rate",
                value: fmtPct(m.win_rate, 1),
                tone: "neutral",
              },
            ]}
          />
        </div>
      )}
    </div>
  );
}

function ReadingHint({
  color,
  title,
  body,
}: {
  color: string;
  title: string;
  body: string;
}) {
  return (
    <div
      className="rounded-md p-3 border"
      style={{
        borderColor: `color-mix(in srgb, ${color} 28%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <p className="font-semibold mb-1" style={{ color }}>
        {title}
      </p>
      <p className="text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </div>
  );
}

function GateRow({
  label,
  threshold,
  v9,
  v10,
  v16,
  format,
  pass,
}: {
  label: string;
  threshold: string;
  v9: number | null;
  v10: number | null;
  v16: number | null;
  format: "pct" | "num";
  pass: (v: number | null) => boolean;
}) {
  const fmt = (v: number | null) =>
    v === null ? "—" : format === "pct" ? fmtPct(v, 1) : fmtNum(v, 3);
  const cell = (v: number | null, key: string) => (
    <td
      key={key}
      className="px-4 py-3 text-right"
      style={{ color: pass(v) ? "var(--green)" : "var(--red)" }}
    >
      {pass(v) ? "✓ " : "✗ "}
      {fmt(v)}
    </td>
  );
  return (
    <tr className="border-t border-[var(--border-soft)]">
      <td className="px-4 py-3 text-[var(--text-primary)]">{label}</td>
      <td className="px-4 py-3 text-[var(--text-tertiary)]">{threshold}</td>
      {cell(v9, "v9")}
      {cell(v10, "v10")}
      {cell(v16, "v16")}
    </tr>
  );
}

function VersionCard({ version }: { version: StrategyVersion }) {
  const s = STATUS_STYLE[version.status];
  const m = version.metrics;
  const rejected = version.status === "rejected";
  const isCandidate = version.status === "candidate";
  const isFace = version.status === "production";

  return (
    <li id={version.id} className="ml-5 relative scroll-mt-24">
      <span
        className="absolute -left-[27px] top-2 w-3 h-3 rounded-full border-2"
        style={{
          background: rejected || isCandidate ? "var(--bg-base)" : s.color,
          borderColor: s.color,
        }}
      />
      <article
        className={`rounded-lg border bg-[var(--bg-surface)]/40 p-5 ${
          rejected
            ? "border-[var(--red)]/30"
            : isCandidate
            ? "border-[var(--gold)]/35"
            : isFace
            ? "border-[var(--green)]/40"
            : "border-[var(--border-soft)]"
        }`}
      >
        <header className="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div className="min-w-0">
            <div className="flex items-center gap-2 mb-1">
              <span
                className="text-[10px] font-mono uppercase tracking-[0.15em] px-2 py-0.5 rounded"
                style={{ color: s.color, background: s.bg }}
              >
                {s.label}
              </span>
              <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
                {version.era_start}
              </span>
            </div>
            <h3
              className={`text-lg font-semibold ${
                rejected
                  ? "text-[var(--text-secondary)] line-through decoration-[var(--red)]/50"
                  : "text-[var(--text-primary)]"
              }`}
            >
              <span className="font-mono mr-2">{version.id}</span>
              {version.name_en}
            </h3>
            <p className="text-xs font-mono text-[var(--text-tertiary)] mt-0.5">
              {version.name_zh}
            </p>
            <p className="mt-2 text-sm text-[var(--text-secondary)] leading-relaxed">
              {version.tagline}
            </p>
          </div>
        </header>

        {m && (
          <div className="mt-4 mb-4">
            <MetricGrid
              metrics={[
                {
                  label: "年化",
                  value: fmtPct(m.annualized_return, 2),
                  tone: rejected
                    ? "bad"
                    : (m.annualized_return ?? 0) >= 0.15
                    ? "good"
                    : "warn",
                },
                {
                  label: "Sharpe",
                  value: fmtNum(m.sharpe, 3),
                  tone: rejected
                    ? "bad"
                    : (m.sharpe ?? 0) >= 0.8
                    ? "good"
                    : "warn",
                  hint: rejected
                    ? "IS 0.63 但 OOS 仅 0.27"
                    : isCandidate
                    ? "未达 0.8 门槛"
                    : undefined,
                },
                {
                  label: "Max DD",
                  value: fmtPct(m.max_drawdown, 1),
                  tone: (m.max_drawdown ?? 0) > -0.3 ? "good" : "bad",
                  hint: isCandidate ? "超 30% 红线" : undefined,
                },
                {
                  label: "Win Rate",
                  value: fmtPct(m.win_rate, 1),
                  tone: "neutral",
                },
              ]}
            />
          </div>
        )}

        {version.highlights && version.highlights.length > 0 && (
          <ul className="mt-3 space-y-1.5 text-xs text-[var(--text-secondary)]">
            {version.highlights.map((h, i) => (
              <li key={i} className="flex gap-2">
                <span
                  className="shrink-0"
                  style={{
                    color: rejected
                      ? "var(--red)"
                      : isCandidate
                      ? "var(--gold)"
                      : "var(--text-tertiary)",
                  }}
                >
                  ›
                </span>
                <span>{h}</span>
              </li>
            ))}
          </ul>
        )}

        <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
          <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-2">
            因子 · {version.factors.length}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {version.factors.map((f) => (
              <span
                key={f}
                className="text-[11px] font-mono px-2 py-0.5 rounded border border-[var(--border-soft)] text-[var(--text-secondary)]"
              >
                {f}
              </span>
            ))}
          </div>
        </div>

        {isCandidate && version.gate_check && (
          <GateCheckPanel check={version.gate_check} />
        )}

        {(version.run_id || version.eval_report) && (
          <div className="mt-3 text-[10px] font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-4 gap-y-1">
            {version.run_id && <span>run_id: {version.run_id}</span>}
            {version.eval_report && (
              <Link
                href="/validation"
                className="text-[var(--red)] hover:underline"
              >
                见否决报告 →
              </Link>
            )}
          </div>
        )}
      </article>
    </li>
  );
}

function GateCheckPanel({ check }: { check: Record<string, GateCheck> }) {
  const entries = Object.entries(check);
  return (
    <div className="mt-4 pt-3 border-t border-[var(--border-soft)]">
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--gold)] mb-2">
        Admission Gate Check
      </p>
      <ul className="space-y-1 text-xs font-mono">
        {entries.map(([k, v]) => (
          <li key={k} className="flex items-center gap-2">
            <span style={{ color: v.pass ? "var(--green)" : "var(--red)" }}>
              {v.pass ? "✓" : "✗"}
            </span>
            <span className="text-[var(--text-secondary)] min-w-[140px]">{k}</span>
            <span
              className="text-[var(--text-primary)]"
              style={{ color: v.pass ? "var(--text-primary)" : "var(--red)" }}
            >
              {typeof v.value === "boolean" ? String(v.value) : v.value}
            </span>
            <span className="text-[var(--text-tertiary)]">
              / threshold{" "}
              {typeof v.threshold === "boolean"
                ? String(v.threshold)
                : v.threshold}
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
