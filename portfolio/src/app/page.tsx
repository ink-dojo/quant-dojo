import Link from "next/link";
import { SITE, projectWeek } from "@/lib/constants";
import { EquityChart } from "@/components/viz/EquityChart";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct, fmtNum } from "@/lib/formatters";
import {
  DisclosurePanel,
  EvidenceCard,
  SectionLabel,
  StatusPill,
  TextLink,
} from "@/components/layout/Primitives";
import { Lang } from "@/components/layout/LanguageText";
import type {
  EquityCurveFile,
  FactorIndex,
  Meta,
  PaperTradeState,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function Home() {
  const [meta, index, versions, paper] = await Promise.all([
    readData<Meta>("meta.json"),
    readData<FactorIndex>("factors/index.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
    readDataOrNull<PaperTradeState>("paper_trade/state.json"),
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
    v25: "var(--gold)",
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
      <section className="pt-20 pb-12">
        <div className="mb-8 flex flex-wrap items-center gap-2">
          <StatusPill tone="blue">Week {week}</StatusPill>
          <StatusPill tone="neutral">{dateStr}</StatusPill>
          <StatusPill tone={paper?.enabled ? "green" : "gold"}>
            {paper?.enabled ? "paper-trade running" : "paper-trade unavailable"}
          </StatusPill>
        </div>

        <h1 className="max-w-4xl text-4xl font-semibold tracking-[-0.035em] text-[var(--text-primary)] md:text-6xl">
          <Lang
            zh="A 股策略研究账本。"
            en="A research ledger for A-share strategies."
          />
        </h1>
        <p className="mt-6 max-w-2xl text-base leading-relaxed text-[var(--text-secondary)] md:text-lg">
          <Lang
            zh="这里不是展示型首页，而是策略研究的索引：预注册测试、否决记录、模拟盘状态和可追溯证据。默认只看状态，需要细节再点开。"
            en="A-share strategy workbench with pre-registered tests, rejection records, paper-trade state, and source-linked evidence. The default view shows status; details stay one click away."
          />
        </p>
      </section>

      <section className="pb-16">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard
            tone={paper?.kill.action === "ok" ? "green" : paper ? "gold" : "neutral"}
            label={<Lang zh="模拟盘" en="Paper trade" />}
            value={paper ? paper.strategy_id?.replace(/_/g, " ") ?? "active" : <Lang zh="无快照" en="No snapshot" />}
            detail={
              paper
                ? `spec ${paper.spec_version} · Day ${paper.kill.running_days} · risk ${paper.kill.action.toUpperCase()}`
                : <Lang zh="等待 EOD 状态导出" en="Waiting for exported EOD state" />
            }
            href="/live"
          />
          <EvidenceCard
            tone="blue"
            label={<Lang zh="因子库" en="Factor library" />}
            value={<Lang zh={`${index.total} 个已扫描`} en={`${index.total} scanned`} />}
            detail={<Lang zh={`${index.with_ic_stats} 个有 IC 统计 · ${index.with_research_folder} 个研究目录`} en={`${index.with_ic_stats} with IC stats · ${index.with_research_folder} research folders`} />}
            href="/research"
          />
          <EvidenceCard
            tone="green"
            label={<Lang zh="研究基线" en="Research face" />}
            value={face?.id ?? versions.production_face}
            detail={
              face?.metrics
                ? `Sharpe ${fmtNum(face.metrics.sharpe, 2)} · DD ${fmtPct(face.metrics.max_drawdown, 1)}`
                : <Lang zh="已过 walk-forward 的多因子线" en="WF-validated multi-factor line" />
            }
            href="/strategy"
          />
          <EvidenceCard
            tone="red"
            label={<Lang zh="最近硬否决" en="Latest hard reject" />}
            value="RIAD combo"
            detail={<Lang zh="可执行股票池破坏 baseline 结果；继续跑 BB-only。" en="Executable universe broke the baseline result; keep BB-only live." />}
            href="/validation"
          />
        </div>
      </section>

      <section className="pb-16">
        <SectionLabel
          eyebrow={<Lang zh="当前地图" en="Current map" />}
          title={<Lang zh="运行中、研究中、已阻塞" en="What is running, what is research, what is blocked" />}
          body={<Lang zh="运行状态和研究产物分开呈现。需要理由或源文件时，展开对应条目。" en="The site separates operational state from research artifacts. Open the row if you need the reasoning or source path." />}
        />
        <div className="space-y-3">
          <DisclosurePanel
            tone="green"
            title={<Lang zh="运行中：DSR #30 BB-only 模拟盘" en="Running: DSR #30 BB-only paper-trade" />}
            summary={
              paper
                ? `NAV ${fmtNum(paper.last_nav, 0)} · Cum ${fmtPct(paper.cum_return, 2)} · ${paper.positions.length} positions`
                : <Lang zh="没有找到已导出的模拟盘快照。" en="No exported paper-trade snapshot found." />
            }
          >
            <p>
              <Lang
                zh="这是当前唯一标记为运行中的模拟盘线。它使用 spec v3 BB-only 和 5% 模拟资金；Live 页展示 ledger 快照、kill switch、持仓和每日交易摘要。"
                en="This is the only operational paper-trade line shown as running. It uses spec v3 BB-only with 5% simulated capital. The live page carries the ledger snapshot, kill switch state, positions, and daily trade summary."
              />
            </p>
            <div className="mt-3">
              <TextLink href="/live"><Lang zh="查看 Live 状态" en="Open live state" /></TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="blue"
            title={<Lang zh="研究中：因子库和多因子版本" en="Research: factor library and multi-factor versions" />}
            summary={<Lang zh={`${index.total} 个因子候选，${index.with_ic_stats} 个有统计，${face?.id ?? "v9"} 是多因子研究基线。`} en={`${index.total} factor candidates, ${index.with_ic_stats} with statistics, ${face?.id ?? "v9"} as the multi-factor research face.`} />}
          >
            <p>
              <Lang
                zh="多因子版本默认都是研究产物，除非 Live 页明确标记为模拟盘。这里有价值的是 gate 序列：v9 通过 walk-forward，v10 OOS 失败，挖掘候选在验证前仍只是候选。"
                en="Multi-factor versions are research artifacts unless explicitly marked as paper-trade. The useful record is the sequence of gates: v9 survives walk-forward, v10 fails OOS, and mining candidates remain candidates until validated."
              />
            </p>
            <div className="mt-3 flex flex-wrap gap-3">
              <TextLink href="/research"><Lang zh="查看因子库" en="Open factor library" /></TextLink>
              <TextLink href="/strategy"><Lang zh="查看策略版本" en="Open strategy versions" /></TextLink>
            </div>
          </DisclosurePanel>

          <DisclosurePanel
            tone="red"
            title={<Lang zh="已阻塞：RIAD + DSR #30 组合" en="Blocked: RIAD + DSR #30 combo" />}
            summary={<Lang zh="Baseline 回测好看，但可执行约束没有保住结果。" en="Baseline backtest looked good; executable constraints did not." />}
          >
            <p>
              <Lang
                zh="这个组合不会被展示为运行中。问题不是 headline Sharpe，而是 baseline 构造和真实融券/股票池约束之间的差距。Validation 把它保留为 case file，而不是上线故事。"
                en="The combo is not presented as running. The issue is not the headline Sharpe; it is the gap between baseline construction and executable short/universe constraints. Validation keeps this as a case file, not a promotion story."
              />
            </p>
            <div className="mt-3">
              <TextLink href="/validation"><Lang zh="查看否决档案" en="Open rejection file" /></TextLink>
            </div>
          </DisclosurePanel>
        </div>
      </section>

      {series.length > 0 && (
        <section className="pb-16">
          <SectionLabel
            eyebrow={<Lang zh="可选细节" en="Optional detail" />}
            title={<Lang zh="净值曲线是证据，不是首页主角" en="Equity curves are supporting evidence" />}
            body={<Lang zh="先看状态，再看图。图表默认折叠，避免把阅读路径变成数据墙。" en="Charts are useful after the status is clear. They are no longer the hero of the page." />}
          />
          <DisclosurePanel
            tone="neutral"
            title={<Lang zh="打开多因子净值对比" en="Open multi-factor equity overlay" />}
            summary={<Lang zh="v9 基线、被否决的止损版本、当前候选放在同一坐标。" en="v9 face, rejected stop-loss variant, and current candidate on one axis." />}
          >
            <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-base)]/40 p-4">
              <EquityChart series={series} height={380} />
            </div>
            <div className="mt-4 grid grid-cols-1 gap-3 md:grid-cols-3">
              {face && (
                <MiniNote
                  tone="green"
                  label={`${face.id} · research face`}
                  body={<Lang zh="通过 walk-forward。它是研究基准，不是当前模拟盘线。" en="Walk-forward survived. This is a research benchmark, not the current paper-trade line." />}
                />
              )}
              {rejected && (
                <MiniNote
                  tone="red"
                  label={`${rejected.id} · rejected`}
                  body={<Lang zh="止损层改善了一个口径的回撤，但破坏了 OOS 表现。" en="The stop-loss layer improved one view of drawdown and damaged OOS behavior." />}
                />
              )}
              {candidate && (
                <MiniNote
                  tone="gold"
                  label={`${candidate.id} · candidate`}
                  body={<Lang zh="保留展示是因为它有诱惑力，不代表已批准。" en="Kept visible because it is tempting, not because it is approved." />}
                />
              )}
            </div>
          </DisclosurePanel>
        </section>
      )}

      <section className="pb-20">
        <SectionLabel
          eyebrow={<Lang zh="阅读路径" en="Reading path" />}
          title={<Lang zh="先看总览，需要再展开" en="Start broad. Open only what you need." />}
        />
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          <PathCard href="/live" n="01" title="Live" body={<Lang zh="当前模拟盘状态、风控动作、持仓和每日摘要。" en="Current paper-trade state, risk action, positions, and daily summary." />} />
          <PathCard href="/validation" n="02" title="Validation" body={<Lang zh="被否决策略、被杀因子、被阻塞 spec 的 case files。" en="Case files for rejected strategies, killed factors, and blocked specs." />} />
          <PathCard href="/research" n="03" title="Research" body={<Lang zh="因子库、分类筛选和核心因子的深度页。" en="Factor library, category filter, and deep dives for selected factors." />} />
          <PathCard href="/strategy" n="04" title="Strategy" body={<Lang zh="多因子版本、gate、候选和净值对比。" en="Multi-factor versions, gates, candidates, and equity overlays." />} />
          <PathCard href="/journey" n="05" title="Journey" body={<Lang zh="按时间记录 scope、产出和教训。" en="Chronological project record with scope, output, and lessons." />} />
          <PathCard href="/infrastructure" n="06" title="Infra" body={<Lang zh="真实 repo 分层、数据导出路径和构建信息。" en="Actual repo layers, data export path, and build metadata." />} />
        </div>
      </section>

      <footer className="border-t border-[var(--border-soft)] py-8 text-[11px] font-mono text-[var(--text-tertiary)]">
        <div className="flex flex-wrap justify-between gap-3">
          <span>{SITE.title} · started {SITE.started_at}</span>
          <span>build {meta.git.short ?? "dirty"} · {meta.git.subject}</span>
          <span>data {meta.coverage_generated_at.slice(0, 10)}</span>
        </div>
      </footer>
    </div>
  );
}

function PathCard({
  href,
  n,
  title,
  body,
}: {
  href: string;
  n: string;
  title: React.ReactNode;
  body: React.ReactNode;
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-[var(--border-soft)] bg-[var(--bg-surface)]/28 p-4 transition-colors hover:border-[var(--border)] hover:bg-[var(--bg-surface)]/50"
    >
      <p className="mb-4 text-[10px] font-mono text-[var(--text-tertiary)]">{n}</p>
      <h3 className="text-base font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)]">
        {title}
      </h3>
      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">{body}</p>
    </Link>
  );
}

function MiniNote({
  tone,
  label,
  body,
}: {
  tone: "green" | "red" | "gold";
  label: string;
  body: React.ReactNode;
}) {
  const color =
    tone === "green" ? "var(--green)" : tone === "red" ? "var(--red)" : "var(--gold)";
  return (
    <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/35 p-3">
      <p className="text-[10px] font-mono uppercase tracking-[0.14em]" style={{ color }}>
        {label}
      </p>
      <p className="mt-2 text-xs leading-relaxed text-[var(--text-secondary)]">{body}</p>
    </div>
  );
}
