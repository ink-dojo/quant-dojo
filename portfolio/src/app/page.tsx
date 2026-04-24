import Link from "next/link";
import { SITE, projectWeek } from "@/lib/constants";
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

  const { week, dateStr } = projectWeek();

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
        <p className="text-[11px] font-mono uppercase tracking-[0.25em] text-[var(--blue)] mb-4">
          Week {week} · {dateStr} · Open research journal
        </p>
        <h1 className="text-4xl md:text-6xl font-semibold text-[var(--text-primary)] leading-tight max-w-4xl">
          {SITE.title}
          <span className="text-[var(--text-tertiary)] font-mono text-2xl md:text-3xl ml-3">
            量化道场
          </span>
        </h1>
        <div className="mt-8 max-w-3xl space-y-4 text-[var(--text-secondary)] leading-relaxed">
          <p className="text-lg">
            我是 jialong. {SITE.started_at} 开始认真学 A 股量化,
            这个站是我的工作台 — 把每一条假设、每一次否决、每一份数据钉在同一个地方,
            给未来的我和正在路上的同行查阅.
          </p>
          <p>
            核心纪律只有一条: 把&ldquo;为什么否决一个策略&rdquo;和
            &ldquo;为什么选中一个策略&rdquo;摆在同一页.
            Admission gate 写死在{" "}
            <code className="font-mono text-sm text-[var(--text-primary)]">
              CLAUDE.md
            </code>
            , 数据跑完按 gate 盖章, 不改门槛迁就成绩.
          </p>
          <p>
            本周状态 —
            {" "}<span className="text-[var(--text-primary)]">{index.total} 个因子</span>
            扫过横截面, IC 三件套后仅 {index.with_ic_stats} 个带完整统计, 8 个做深度研究;
            多因子方向的 research face 是{" "}
            {face && (
              <span className="text-[var(--green)] font-semibold">{face.id}</span>
            )}
            (ICIR-weighted, WF 中位 0.53);
            {rejected && (
              <>
                {" "}<span className="text-[var(--red)] font-semibold">{rejected.id}</span>
                {" "}被自己的 walk-forward 否决;
              </>
            )}
            {" "}Event-driven 31 个 pre-reg trials 里, 两个 4/5 + 一个 50/50 ensemble 过 5/5 admission gate;
            从 Week 6 Day 1 (2026-04-17) 起, DSR #30 BB-only 主板 rescaled 单腿上了 paper-trade,
            5% 模拟资金.
          </p>
          <p className="text-sm text-[var(--text-tertiary)]">
            下面三条 equity 曲线都是 2022-01 → 2025-12 的 backtest (同一份数据、同一套 metrics),
            用来对比三种不同方法论的后果:
            {face && (
              <>
                {" "}<span className="text-[var(--green)] font-semibold">{face.id}</span>
                {" "}当前 face;
              </>
            )}
            {rejected && (
              <>
                {" "}<span className="text-[var(--red)] font-semibold">{rejected.id}</span>
                {" "}被 walk-forward 否决;
              </>
            )}
            {candidate && (
              <>
                {" "}<span className="text-[var(--gold)] font-semibold">{candidate.id}</span>
                {" "}总收益最高, 仍是 candidate, 没上 live.
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
              Event-driven · Week 4-6 · 31 pre-reg trials
            </span>
            <span className="text-[10px] font-mono text-[var(--text-tertiary)]">
              BB × LHB · 50/50 ensemble
            </span>
          </div>
          <h2 className="text-xl font-semibold text-[var(--text-primary)] mb-1">
            两个 4/5 候选失败模式正交 → 等权合成过 5/5 admission gate
          </h2>
          <p className="text-sm text-[var(--text-secondary)] leading-relaxed">
            DSR #30 回购 drift 卡在 CI_low, DSR #33 LHB 跌幅 contrarian 卡在 MDD;
            两者 correlation 0.37, 等权 ensemble 同时补上两个失败模式.
            <span className="text-[var(--green)] ml-1">看完整 DSR penalty bookkeeping →</span>
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
                tag="Research face"
                id={face.id}
                metric={`年化 ${fmtPct(face.metrics?.annualized_return, 1)} · Sharpe ${fmtNum(face.metrics?.sharpe, 2)}`}
                body="ICIR 学习权重, walk-forward 17 窗口中位 sharpe 0.53. 4 条 admission gate 都过."
              />
            )}
            {rejected && (
              <CurveReading
                color="var(--red)"
                tag="Rejected"
                id={rejected.id}
                metric={`IS 0.63 → OOS 0.27`}
                body="叠加组合止损看似缓解 IS 回撤, 但 WF 样本外 sharpe 半砍. 这是 IS-OOS 落差的典型样子."
              />
            )}
            {candidate && (
              <CurveReading
                color="var(--gold)"
                tag="Candidate"
                id={candidate.id}
                metric={`年化 ${fmtPct(candidate.metrics?.annualized_return, 1)} · DD ${fmtPct(candidate.metrics?.max_drawdown, 1)}`}
                body="Week 5 挖掘 session 从 11 个候选里按 sharpe 挑出的赢家. 回撤超红线、WF 未跑, 仍是 candidate."
              />
            )}
          </div>
        </section>
      )}

      <section className="py-12 border-t border-[var(--border-soft)] max-w-3xl">
        <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-5">
          Reading path
        </p>
        <ol className="space-y-5 text-[var(--text-secondary)] leading-relaxed">
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              01
            </span>
            <div>
              <Link
                href="/journey"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Journey · 历程
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              按周看这 6 周做了什么 / 学到什么 / 踩了哪些坑.
              这是社区友好的入口 (5 分钟).
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              02
            </span>
            <div>
              <Link
                href="/research"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Research · 研究
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              {index.total} 因子的 IC / ICIR / Fama-MacBeth; 8 个核心因子带衰减曲线 + 分层回测.
              Event-driven 单独成章.
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              03
            </span>
            <div>
              <Link
                href="/strategy"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Strategy · 策略
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              v7 → v25 的 multi-factor 实验, 同一张 equity overlay + admission gate 表.
              哪些过、哪些被否.
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              04
            </span>
            <div>
              <Link
                href="/validation"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Validation · 否决档案
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              踩过的坑 / post-mortem. v10 为什么 OOS 崩, v16 为什么不能 promote,
              v4 RIAD 合成 spec 为什么最终放弃.
            </div>
          </li>
          <li className="flex gap-4">
            <span className="font-mono text-[var(--text-tertiary)] text-sm shrink-0 w-6 pt-0.5">
              05
            </span>
            <div>
              <Link
                href="/live"
                className="text-[var(--text-primary)] font-semibold hover:text-[var(--blue)]"
              >
                Live · 模拟盘
              </Link>
              <span className="text-[var(--text-tertiary)]"> — </span>
              从 Week 6 Day 1 起跑的 DSR #30 BB-only paper-trade 状态.
              5% 模拟资金, 不是真钱.
            </div>
          </li>
        </ol>
        <p className="mt-6 text-xs text-[var(--text-tertiary)] leading-relaxed">
          <Link href="/infrastructure" className="hover:text-[var(--blue)]">
            Infra
          </Link>{" "}
          展示数据 / 回测 / live / agentic 的分层,{" "}
          <Link href="/glossary" className="hover:text-[var(--blue)]">
            Glossary
          </Link>{" "}
          是 IC / ICIR / PSR / DSR 等术语的公式 + 直觉速查.
        </p>
      </section>

      <section className="py-12 border-t border-[var(--border-soft)] max-w-3xl">
        <p className="text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-5">
          About · How I learn
        </p>
        <div className="space-y-4 text-sm text-[var(--text-secondary)] leading-relaxed">
          <p>
            我 {SITE.author}, US CS 研究生在读, 将来想回深圳做系统化 A 股策略.
            这个 repo 是我从 0 开始的公开学习实验 —
            书 / 论文 / AI 工具 / 错误 / 修正 都记录在 git 里, 站点只是一个可视化入口.
          </p>
          <p>
            方法论来源主要是三条:
            <span className="text-[var(--text-primary)]"> Advances in Financial Machine Learning</span> (López de Prado)
            教会我 deflated sharpe / walk-forward / regime split 的纪律;
            <span className="text-[var(--text-primary)]"> 量化选股策略实战</span> (杨平) 给了我 A 股 specific 的因子池起点;
            各种 Chinese academic papers 让我理解 A 股 T+1 / 涨跌停 / 北向 / 两融
            这些与美股不同的市场结构.
          </p>
          <p>
            开发过程几乎全程用 Claude Code 做 pair programmer — 但每个 admission gate 由我手动签字,
            AI 不能直接上线任何因子或权重. 这在{" "}
            <code className="font-mono text-xs text-[var(--text-primary)]">CLAUDE.md</code>{" "}
            第一条红线里写死.
          </p>
          <p>
            如果你也在学量化, 直接打开{" "}
            <Link href="/journey" className="text-[var(--blue)] hover:underline">
              /journey
            </Link>{" "}
            看这 6 周的时间线, 或者{" "}
            <Link href="/validation" className="text-[var(--red)] hover:underline">
              /validation
            </Link>{" "}
            看我否决过的东西 — 这两页比任何一张亮眼的 equity 曲线都信息密度高.
          </p>
        </div>
      </section>

      <footer className="py-8 mt-8 border-t border-[var(--border-soft)] text-[11px] font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-6 gap-y-2 justify-between">
        <span>
          {SITE.title} · {SITE.author} · started {SITE.started_at}
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
