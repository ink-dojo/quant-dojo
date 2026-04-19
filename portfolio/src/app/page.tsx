import Link from "next/link";
import { SITE } from "@/lib/constants";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import type {
  EquityCurveFile,
  FactorIndex,
  Meta,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function Home() {
  const [meta, index, versions] = await Promise.all([
    readData<Meta>("meta.json"),
    readData<FactorIndex>("factors/index.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
  ]);

  const face = versions.versions.find((v) => v.id === versions.production_face);
  const candidate = versions.versions.find((v) => v.id === versions.candidate);
  const rejected = versions.versions.find((v) => v.status === "rejected");

  const curveIds = [face, rejected, candidate]
    .filter((v): v is NonNullable<typeof v> => Boolean(v?.equity_file))
    .map((v) => ({ id: v.id, file: v.equity_file!, status: v.status, name: v.name_zh }));

  const curves = await Promise.all(
    curveIds.map(async (c) => ({
      ...c,
      curve: await readDataOrNull<EquityCurveFile>(`strategy/${c.file}`),
    }))
  );

  const seriesColor: Record<string, string> = {
    v9: "var(--green)",
    v10: "var(--red)",
    v16: "var(--gold)",
  };

  const series = curves
    .filter((c) => c.curve !== null)
    .map((c) => ({
      id: c.id,
      label: `${c.id} · ${c.name}`,
      color: seriesColor[c.id] ?? "var(--cyan)",
      dashed: c.status === "rejected" || c.status === "candidate",
      curve: c.curve!,
    }));

  return (
    <div className="max-w-content mx-auto px-6">
      <section className="pt-20 pb-10">
        <p className="text-[11px] font-mono uppercase tracking-[0.25em] text-[var(--text-tertiary)] mb-4">
          {meta.face.production === meta.face.research
            ? `Production face · ${meta.face.production}`
            : `${meta.face.production} production · ${meta.face.research} research`}
        </p>
        <h1 className="text-4xl md:text-6xl font-semibold text-[var(--text-primary)] leading-tight max-w-4xl">
          {SITE.title}
          <span className="text-[var(--text-tertiary)] font-mono text-2xl md:text-3xl ml-3">
            量化道场
          </span>
        </h1>
        <div className="mt-8 max-w-3xl space-y-4 text-[var(--text-secondary)] leading-relaxed">
          <p className="text-lg">
            一个 A 股量化研究工作台。{index.total} 个 alpha 因子、四代策略迭代、
            一套写在{" "}
            <code className="font-mono text-sm text-[var(--text-primary)]">
              CLAUDE.md
            </code>{" "}
            里的 admission gate —— 这是骨架。但真正的主线，是
            <span className="text-[var(--text-primary)]"> 纪律</span>
            ：什么样的策略配得上&ldquo;生产门面&rdquo;四个字。
          </p>
          <p>
            下面这张图是整个项目的答案。三条曲线都活在同一份数据上，
            结局却完全不同。{face && (
              <>
                <span className="text-[var(--green)] font-semibold">
                  {face.id}
                </span>
                {" "}走得最稳，是当前生产门面；
              </>
            )}
            {rejected && (
              <>
                <span className="text-[var(--red)] font-semibold">
                  {rejected.id}
                </span>
                {" "}被我们自己的 walk-forward 否决；
              </>
            )}
            {candidate && (
              <>
                <span className="text-[var(--gold)] font-semibold">
                  {candidate.id}
                </span>
                {" "}总收益最高，但不上 live。
              </>
            )}
          </p>
        </div>
      </section>

      <section className="pb-8">
        <Link
          href="/research/event-driven"
          className="block rounded-lg border border-[var(--green)]/35 bg-[var(--green)]/[0.05] p-5 hover:bg-[var(--green)]/[0.08] transition-colors"
        >
          <div className="flex items-baseline gap-3 mb-1">
            <span className="text-[10px] font-mono uppercase tracking-[0.22em] text-[var(--green)]">
              Event-driven · 21 pre-reg trials
            </span>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
              Phase 3 · 4 · 4.1
            </span>
          </div>
          <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
            回购 drift × 龙虎榜跌幅 contrarian 50/50 ensemble — 过 5/5 admission gate
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            两个 4/5 候选失败模式正交（相关 0.37），等权 ensemble 零自由度组合 →
            ann 41.96% · Sharpe 2.47 · MDD -26.78% · CI_low 1.17。
            <span className="text-[var(--green)] ml-1">看完整 DSR 记账表 →</span>
          </p>
        </Link>
      </section>

      {series.length > 0 && (
        <section className="pb-6">
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <EquityChart series={series} height={420} />
          </div>
          <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-4 text-sm">
            {face && (
              <CurveReading
                color="var(--green)"
                tag="Production face"
                id={face.id}
                metric={`年化 ${fmtPct(face.metrics?.annualized_return, 1)} · Sharpe ${fmtNum(face.metrics?.sharpe, 2)}`}
                body="ICIR 学习权重，walk-forward 中位 0.53。4 条 admission gate 都过。"
              />
            )}
            {rejected && (
              <CurveReading
                color="var(--red)"
                tag="Rejected"
                id={rejected.id}
                metric={`IS 0.63 → OOS 0.27`}
                body="叠加组合止损看似缓解回撤，但 WF 样本外 sharpe 半砍。这是 IS-OOS 落差的典型样子。"
              />
            )}
            {candidate && (
              <CurveReading
                color="var(--gold)"
                tag="Candidate · 未上 live"
                id={candidate.id}
                metric={`年化 ${fmtPct(candidate.metrics?.annualized_return, 1)} · DD ${fmtPct(candidate.metrics?.max_drawdown, 1)}`}
                body="从 11 个挖掘候选里按 sharpe 挑出来的赢家。回撤超红线、WF 未跑，仍是候选。"
              />
            )}
          </div>
        </section>
      )}

      <section className="py-12 border-t border-[var(--border-soft)] max-w-3xl">
        <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-5">
          How to read this site
        </p>
        <ol className="space-y-5 text-[var(--text-secondary)] leading-relaxed">
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              01
            </span>
            <div>
              <Link
                href="/research"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Research · 研究
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              从 {index.total} 个因子库里看 IC / ICIR / Fama-MacBeth。
              8 个核心因子每一个都有独立的衰减曲线和分层回测。
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              02
            </span>
            <div>
              <Link
                href="/strategy"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Strategy · 策略
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              v7 → v9 → v10 → v16 的四代演化。
              同一张 equity overlay、同一张 admission gate 表，决定谁是 face。
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              03
            </span>
            <div>
              <Link
                href="/validation"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Validation · 验证
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              不是 &ldquo;我们最好的策略&rdquo;，而是 &ldquo;我们否决过哪些&rdquo;。
              v10 否决报告、WF 17 个滚动窗口、CLAUDE.md 红线对照。
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              04
            </span>
            <div>
              <Link
                href="/live"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Live · 实盘
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              reconcile / snapshot / signal log 的真实状态。
              声明的 active 和 face 可能不一致 —— 这一页就是说明白这件事。
            </div>
          </li>
        </ol>
        <p className="mt-6 text-xs text-[var(--text-tertiary)] leading-relaxed">
          另有{" "}
          <Link
            href="/infrastructure"
            className="hover:text-[var(--blue)]"
          >
            Infra
          </Link>
          （数据层 · 回测引擎 · control plane）和{" "}
          <Link href="/journey" className="hover:text-[var(--blue)]">
            Journey
          </Link>
          （9 阶段里程碑和代价换来的教训）两条支线。
        </p>
      </section>

      <footer className="py-8 mt-8 border-t border-[var(--border-soft)] text-[11px] font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-6 gap-y-2 justify-between">
        <span>
          {SITE.title} · {SITE.author}
        </span>
        <span>
          build {meta.git.short ?? "dirty"}
          {meta.git.subject && (
            <>
              {" · "}
              <span className="text-[var(--text-secondary)]">
                {meta.git.subject}
              </span>
            </>
          )}
        </span>
        <span>data generated {meta.coverage_generated_at.slice(0, 10)}</span>
      </footer>
    </div>
  );
}

function CurveReading({
  color,
  tag,
  id,
  metric,
  body,
}: {
  color: string;
  tag: string;
  id: string;
  metric: string;
  body: string;
}) {
  return (
    <div
      className="rounded-md p-4 border"
      style={{
        borderColor: `color-mix(in srgb, ${color} 28%, transparent)`,
        background: `color-mix(in srgb, ${color} 5%, transparent)`,
      }}
    >
      <div className="flex items-baseline gap-2 mb-1">
        <span
          className="text-[10px] font-mono uppercase tracking-[0.15em]"
          style={{ color }}
        >
          {tag}
        </span>
        <span className="font-mono text-sm font-semibold text-[var(--text-primary)]">
          {id}
        </span>
      </div>
      <p className="text-xs font-mono text-[var(--text-secondary)] mb-2">
        {metric}
      </p>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
        {body}
      </p>
    </div>
  );
}
