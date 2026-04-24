import { PageHeader } from "@/components/layout/PageHeader";
import { EvidenceCard, SectionLabel } from "@/components/layout/Primitives";
import { readData } from "@/lib/data";
import type { Meta } from "@/lib/types";

const STACK = [
  {
    category: "Data",
    zh: "数据层",
    color: "var(--blue)",
    rows: [
      {
        name: "utils/data_loader.py",
        desc: "akshare / local cache entry points for stock history.",
      },
      {
        name: "utils/tushare_loader.py",
        desc: "Tushare access layer; token / endpoint rules live in the journal guide.",
      },
      {
        name: "utils/listing_metadata.py + utils/data_manifest.py",
        desc: "Survivorship guard and data fingerprinting for auditable runs.",
      },
    ],
  },
  {
    category: "Factor Research",
    zh: "因子研究",
    color: "var(--purple)",
    rows: [
      {
        name: "utils/alpha_factors.py",
        desc: "Registered cross-sectional factor library.",
      },
      {
        name: "utils/factor_analysis.py",
        desc: "compute_ic_series / quintile_backtest / factor_decay_analysis / fama_macbeth_t",
      },
      {
        name: "research/factors/",
        desc: "Per-factor research folders, reports, and pre-registered evaluations.",
      },
      {
        name: "scripts/audit_factor_data_coverage.py",
        desc: "Exports factor coverage for the portfolio site.",
      },
    ],
  },
  {
    category: "Backtest Engine",
    zh: "回测引擎",
    color: "var(--cyan)",
    rows: [
      {
        name: "backtest/engine.py :: BacktestEngine",
        desc: "Event-driven engine; public constructor/run signature is a protected interface.",
      },
      {
        name: "backtest/standardized.py",
        desc: "Standardized run artifacts and comparable metrics.",
      },
      {
        name: "utils/walk_forward.py + utils/purged_cv.py",
        desc: "Rolling validation, purging, and embargo logic.",
      },
    ],
  },
  {
    category: "Paper-trade",
    zh: "模拟盘",
    color: "var(--green)",
    rows: [
      {
        name: "scripts/paper_trade_daily.py",
        desc: "Daily EOD paper-trade runner: signal, orders, ledger, report.",
      },
      {
        name: "live/event_paper_trader.py",
        desc: "Event-driven order generation and fill simulation.",
      },
      {
        name: "live/ledger.py",
        desc: "SQLite WAL append-only ledger for trades and NAV.",
      },
      {
        name: "live/event_kill_switch.py",
        desc: "Runtime halt / halve / warning decisions.",
      },
    ],
  },
  {
    category: "Risk Tier 1",
    zh: "风控",
    color: "var(--gold)",
    rows: [
      {
        name: "pipeline/vol_targeting.py",
        desc: "Realized-vol scaling with bounded gross exposure.",
      },
      {
        name: "pipeline/capacity_monitor.py",
        desc: "ADV occupancy checks and capacity caps.",
      },
      {
        name: "pipeline/live_vs_backtest.py",
        desc: "Live/backtest divergence metrics and alert input.",
      },
      {
        name: "scripts/stress_test.py",
        desc: "Historical stress replay for current positions.",
      },
    ],
  },
  {
    category: "Control surface",
    zh: "操作面",
    color: "var(--cyan)",
    rows: [
      {
        name: "quant_dojo/__main__.py",
        desc: "Top-level CLI with run / backtest / compare / history / diff / doctor.",
      },
      {
        name: "pipeline/cli.py + control_surface.py",
        desc: "Research assistant and control-plane entry points.",
      },
      {
        name: "dashboard/",
        desc: "FastAPI operational dashboard and routers.",
      },
    ],
  },
  {
    category: "Portfolio Site (this site)",
    zh: "本站",
    color: "var(--text-tertiary)",
    rows: [
      {
        name: "portfolio/scripts/export_data.py",
        desc: "Exports structured JSON from repo artifacts into public/data.",
      },
      {
        name: "portfolio/ · Next.js 14 App Router",
        desc: "SSG 静态导出（output: export）；Recharts + react-katex；Vercel 托管",
      },
      {
        name: "prebuild hook",
        desc: "npm run build runs export_data first, then static export.",
      },
    ],
  },
];

export default async function InfrastructurePage() {
  const meta = await readData<Meta>("meta.json");

  return (
    <>
      <PageHeader
        eyebrow="Infrastructure"
        title="Repo map"
        subtitle="Actual paths, not architecture slogans"
        description="A compact map of the code that produces research, paper-trade state, risk checks, and this static site."
        crumbs={[{ label: "Home", href: "/" }, { label: "Infrastructure" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard tone="blue" label="Research" value="factors" detail="IC, decay, quintile, FM tests" />
          <EvidenceCard tone="green" label="Paper" value="ledger" detail="orders, NAV, kill switch" />
          <EvidenceCard tone="gold" label="Risk" value="Tier 1" detail="vol, capacity, stress, divergence" />
          <EvidenceCard tone="neutral" label="Site" value="SSG" detail={`build ${meta.git.short ?? "dirty"}`} />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow="Layers"
          title={`${STACK.length} code layers`}
          body="Each row is a real file or directory in the repo."
        />
        <div className="space-y-4">
          {STACK.map((layer) => (
            <StackLayer key={layer.category} layer={layer} />
          ))}
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-24">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-3">
              Tech Stack
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
              <Dt>Research</Dt>
              <Dd>Python 3.11 · pandas · numpy · scipy · statsmodels</Dd>
              <Dt>Backtest</Dt>
              <Dd>自研 BacktestEngine（固定接口）</Dd>
              <Dt>Data</Dt>
              <Dd>Tushare + parquet 本地缓存</Dd>
              <Dt>Agents</Dt>
              <Dd>claude -p subprocess / Ollama localhost fallback</Dd>
              <Dt>Site</Dt>
              <Dd>Next.js 14 (App Router) · Tailwind · Recharts · react-katex</Dd>
              <Dt>Hosting</Dt>
              <Dd>Vercel · SSG 静态导出 · prebuild 自动跑 export_data</Dd>
            </dl>
          </div>
          <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
            <h3 className="text-sm font-mono uppercase tracking-[0.15em] text-[var(--text-tertiary)] mb-3">
              Build Info
            </h3>
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-xs font-mono">
              <Dt>Repo</Dt>
              <Dd>ink-dojo/quant-dojo</Dd>
              <Dt>SHA</Dt>
              <Dd>{meta.git.short ?? "dirty"}</Dd>
              <Dt>Subject</Dt>
              <Dd className="break-words">{meta.git.subject}</Dd>
              <Dt>Generated</Dt>
              <Dd>{meta.generated_at}</Dd>
              <Dt>Research face</Dt>
              <Dd>{meta.face.research}</Dd>
              <Dt>Multi-factor line</Dt>
              <Dd>{meta.face.production}</Dd>
            </dl>
          </div>
        </div>
      </section>
    </>
  );
}

function StackLayer({
  layer,
}: {
  layer: (typeof STACK)[number];
}) {
  return (
    <article className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 overflow-hidden">
      <header
        className="px-5 py-3 flex items-baseline gap-3 border-b border-[var(--border-soft)]"
        style={{ background: `color-mix(in srgb, ${layer.color} 8%, transparent)` }}
      >
        <span
          className="text-sm font-semibold"
          style={{ color: layer.color }}
        >
          {layer.category}
        </span>
        <span className="text-xs font-mono text-[var(--text-tertiary)]">
          {layer.zh}
        </span>
        <span className="ml-auto text-[10px] font-mono text-[var(--text-tertiary)]">
          {layer.rows.length} components
        </span>
      </header>
      <ul>
        {layer.rows.map((r) => (
          <li
            key={r.name}
            className="px-5 py-3 border-b border-[var(--border-soft)] last:border-b-0"
          >
            <p className="font-mono text-xs text-[var(--text-primary)] mb-0.5">
              {r.name}
            </p>
            <p className="text-xs text-[var(--text-secondary)] leading-relaxed">
              {r.desc}
            </p>
          </li>
        ))}
      </ul>
    </article>
  );
}

function Dt({ children }: { children: React.ReactNode }) {
  return (
    <dt className="text-[var(--text-tertiary)] uppercase tracking-[0.1em] text-[10px] self-center">
      {children}
    </dt>
  );
}
function Dd({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <dd className={`text-[var(--text-secondary)] ${className}`}>{children}</dd>
  );
}
