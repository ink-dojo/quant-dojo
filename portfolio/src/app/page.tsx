import Link from "next/link";
import { SITE } from "@/lib/constants";
import { CategoryBadge } from "@/components/cards/CategoryBadge";
import { GaugeRing } from "@/components/viz/GaugeRing";
import { readData, readDataOrNull } from "@/lib/data";
import { fmtPct } from "@/lib/formatters";
import type {
  FactorIndex,
  HeroFactorsFile,
  JourneyFile,
  Meta,
  StrategyVersionsFile,
} from "@/lib/types";

export default async function Home() {
  const [meta, index, heroes, versions, journey] = await Promise.all([
    readData<Meta>("meta.json"),
    readData<FactorIndex>("factors/index.json"),
    readData<HeroFactorsFile>("factors/hero.json"),
    readData<StrategyVersionsFile>("strategy/versions.json"),
    readDataOrNull<JourneyFile>("journey/phases.json"),
  ]);

  const activeVersion = versions.versions.find((v) => v.is_active);
  const coreHeroes = heroes.factors.filter((h) => h.tier === "core").slice(0, 4);
  const expHeroes = heroes.factors
    .filter((h) => h.tier === "experimental")
    .slice(0, 4);

  const journeyDone = journey
    ? journey.phases.reduce((s, p) => s + p.checks_done, 0)
    : 0;
  const journeyTotal = journey
    ? journey.phases.reduce((s, p) => s + p.checks_total, 0)
    : 0;

  return (
    <div className="max-w-content mx-auto px-6">
      <section className="pt-20 pb-12">
        <p className="text-[11px] font-mono uppercase tracking-[0.25em] text-[var(--blue)] mb-4">
          Research · Strategy · Execution
        </p>
        <h1 className="text-4xl md:text-6xl font-semibold text-[var(--text-primary)] leading-tight max-w-4xl">
          {SITE.title}
          <span className="text-[var(--text-tertiary)] font-mono text-2xl md:text-3xl ml-3">
            量化道场
          </span>
        </h1>
        <p className="mt-6 max-w-2xl text-lg text-[var(--text-secondary)] leading-relaxed">
          A 股量化研究工作台 — {index.total} 个 alpha 因子、一个 9 因子的生产策略
          live active、walk-forward 验证、从 hypothesis 到 execution 的完整审计路径。
        </p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link
            href="/research"
            className="px-5 py-2.5 rounded-md bg-[var(--blue)] text-[var(--bg-base)] font-medium hover:opacity-90 transition-opacity"
          >
            Explore Research
          </Link>
          <Link
            href="/strategy"
            className="px-5 py-2.5 rounded-md border border-[var(--border)] text-[var(--text-primary)] hover:bg-[var(--bg-surface)] transition-colors"
          >
            See Strategy
          </Link>
          <Link
            href="/validation"
            className="px-5 py-2.5 rounded-md border border-[var(--red)]/40 text-[var(--red)] hover:bg-[var(--red)]/[0.06] transition-colors"
          >
            诚实失败案例 →
          </Link>
        </div>
      </section>

      <section className="pb-12">
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <StatCard
            label="Alpha Factors"
            value={String(index.total)}
            hint={`${index.with_ic_stats} 带 IC 统计`}
          />
          <StatCard
            label="Production Face"
            value={versions.production_face}
            hint={
              activeVersion?.metrics?.annualized_return !== undefined &&
              activeVersion?.metrics?.annualized_return !== null
                ? `年化 ${fmtPct(
                    activeVersion.metrics.annualized_return,
                    1
                  )} · live`
                : "live active"
            }
            tone="good"
          />
          <StatCard
            label="Research Face"
            value={versions.research_face}
            hint="ICIR 学习权重"
            tone="info"
          />
          <StatCard
            label="Journey"
            value={`${journeyDone}/${journeyTotal}`}
            hint="checkpoints"
          />
        </div>
      </section>

      {activeVersion && (
        <section className="pb-12">
          <div className="rounded-lg border border-[var(--green)]/40 bg-[var(--green)]/[0.05] p-5 flex flex-wrap items-center gap-4">
            <span className="inline-flex items-center gap-2 text-[11px] font-mono uppercase tracking-[0.2em] text-[var(--green)]">
              <span className="w-2 h-2 rounded-full bg-[var(--green)] animate-pulse" />
              Live Active
            </span>
            <span className="text-sm font-mono text-[var(--text-secondary)]">
              <span className="text-[var(--text-primary)] font-semibold">
                {activeVersion.id}
              </span>{" "}
              · {activeVersion.name_zh}
            </span>
            <Link
              href="/strategy"
              className="ml-auto text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)]"
            >
              详情 →
            </Link>
          </div>
        </section>
      )}

      <section className="py-12 border-t border-[var(--border-soft)]">
        <div className="flex items-end justify-between mb-6">
          <div>
            <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
              Hero Factors — 8 支深度研究
            </h2>
            <p className="text-sm text-[var(--text-secondary)]">
              4 个教科书 Core + 4 个自研 Experimental，每个都有 IC / 衰减 / 分层回测。
            </p>
          </div>
          <Link
            href="/research"
            className="text-xs font-mono text-[var(--text-tertiary)] hover:text-[var(--blue)]"
          >
            All 8 →
          </Link>
        </div>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
          {[...coreHeroes, ...expHeroes].map((h) => (
            <Link
              key={h.name}
              href={`/research/${h.name}`}
              className="group p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] hover:border-[var(--border)] transition-all flex items-center gap-3"
            >
              <div className="min-w-0 flex-1">
                <div className="mb-1">
                  <CategoryBadge category={h.category} />
                </div>
                <p className="font-mono text-xs text-[var(--text-tertiary)] truncate">
                  {h.name}
                </p>
                <p className="text-sm font-semibold text-[var(--text-primary)] group-hover:text-[var(--blue)] transition-colors truncate">
                  {h.title_en}
                </p>
              </div>
              <div className="shrink-0">
                <GaugeRing value={h.icir} label="ICIR" size={56} />
              </div>
            </Link>
          ))}
        </div>
      </section>

      <section className="py-12 border-t border-[var(--border-soft)]">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-2">
          Sections
        </h2>
        <p className="text-sm text-[var(--text-secondary)] mb-6">
          按研究 → 策略 → 验证 → 实盘的顺序分层。每一层都直连原始数据，不做粉饰。
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3">
          <SectionTile
            href="/research"
            en="Research"
            zh="研究"
            body="66 个因子库 · 8 个深度研究 · IC / ICIR / Fama-MacBeth"
          />
          <SectionTile
            href="/strategy"
            en="Strategy"
            zh="策略"
            body="v7 → v9 → v10 否决 → v16 四代演化 · 因子组合 · equity curve"
          />
          <SectionTile
            href="/validation"
            en="Validation"
            zh="验证"
            body="admission gate · walk-forward · 诚实失败证据"
            accent="red"
          />
          <SectionTile
            href="/live"
            en="Live"
            zh="实盘"
            body="v16 运行中 · snapshot / reconcile / signal log"
            accent="green"
          />
          <SectionTile
            href="/infrastructure"
            en="Infra"
            zh="工程"
            body="数据层 · 回测引擎 · control plane · agentic research"
          />
          <SectionTile
            href="/journey"
            en="Journey"
            zh="历程"
            body="9 phases · 每阶段关键决策 + 代价换来的教训"
          />
        </div>
      </section>

      <footer className="py-8 mt-8 border-t border-[var(--border-soft)] text-xs font-mono text-[var(--text-tertiary)] flex flex-wrap gap-x-6 gap-y-2 justify-between">
        <span>
          {SITE.title} · {SITE.author}
        </span>
        <span>
          build {meta.git.short ?? "dirty"} ·{" "}
          <span className="text-[var(--text-secondary)]">{meta.git.subject}</span>
        </span>
        <span>data generated {meta.coverage_generated_at}</span>
      </footer>
    </div>
  );
}

function StatCard({
  label,
  value,
  hint,
  tone = "neutral",
}: {
  label: string;
  value: string;
  hint?: string;
  tone?: "neutral" | "good" | "info";
}) {
  const toneColor =
    tone === "good"
      ? "var(--green)"
      : tone === "info"
      ? "var(--blue)"
      : "var(--text-primary)";
  return (
    <div className="p-4 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40">
      <p className="text-[10px] font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-1">
        {label}
      </p>
      <p className="text-2xl font-mono font-semibold" style={{ color: toneColor }}>
        {value}
      </p>
      {hint && (
        <p className="text-[10px] font-mono text-[var(--text-tertiary)] mt-1">
          {hint}
        </p>
      )}
    </div>
  );
}

function SectionTile({
  href,
  en,
  zh,
  body,
  accent,
}: {
  href: string;
  en: string;
  zh: string;
  body: string;
  accent?: "red" | "green";
}) {
  const borderAccent =
    accent === "red"
      ? "hover:border-[var(--red)]/50"
      : accent === "green"
      ? "hover:border-[var(--green)]/50"
      : "hover:border-[var(--border)]";
  return (
    <Link
      href={href}
      className={`group p-5 rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 hover:bg-[var(--bg-surface)] transition-all ${borderAccent}`}
    >
      <div className="flex items-baseline gap-2 mb-2">
        <span className="text-[var(--text-primary)] font-semibold group-hover:text-[var(--blue)] transition-colors">
          {en}
        </span>
        <span className="text-xs font-mono text-[var(--text-tertiary)]">{zh}</span>
      </div>
      <p className="text-xs text-[var(--text-secondary)] leading-relaxed">{body}</p>
    </Link>
  );
}
