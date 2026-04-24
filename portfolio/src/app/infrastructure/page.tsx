import { PageHeader } from "@/components/layout/PageHeader";
import { EvidenceCard, SectionLabel } from "@/components/layout/Primitives";
import { Lang } from "@/components/layout/LanguageText";
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
        desc_zh: "akshare / 本地缓存的股票历史数据入口。",
      },
      {
        name: "utils/tushare_loader.py",
        desc: "Tushare access layer; token / endpoint rules live in the journal guide.",
        desc_zh: "Tushare 访问层；token / endpoint 规则记录在 journal 指南里。",
      },
      {
        name: "utils/listing_metadata.py + utils/data_manifest.py",
        desc: "Survivorship guard and data fingerprinting for auditable runs.",
        desc_zh: "幸存者偏差防护和数据指纹，保证 run 可审计。",
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
        desc_zh: "已注册的截面因子库。",
      },
      {
        name: "utils/factor_analysis.py",
        desc: "compute_ic_series / quintile_backtest / factor_decay_analysis / fama_macbeth_t",
        desc_zh: "IC、分层回测、衰减和 Fama-MacBeth 检验工具。",
      },
      {
        name: "research/factors/",
        desc: "Per-factor research folders, reports, and pre-registered evaluations.",
        desc_zh: "每个因子的研究目录、报告和预注册评估。",
      },
      {
        name: "scripts/audit_factor_data_coverage.py",
        desc: "Exports factor coverage for the portfolio site.",
        desc_zh: "导出本站使用的因子覆盖度数据。",
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
        desc_zh: "事件驱动回测引擎；公开构造函数和 run 签名是受保护接口。",
      },
      {
        name: "backtest/standardized.py",
        desc: "Standardized run artifacts and comparable metrics.",
        desc_zh: "标准化 run 产物和可比指标。",
      },
      {
        name: "utils/walk_forward.py + utils/purged_cv.py",
        desc: "Rolling validation, purging, and embargo logic.",
        desc_zh: "滚动验证、purging 和 embargo 逻辑。",
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
        desc_zh: "每日 EOD 模拟盘 runner：信号、订单、ledger、报告。",
      },
      {
        name: "live/event_paper_trader.py",
        desc: "Event-driven order generation and fill simulation.",
        desc_zh: "事件驱动下单和成交模拟。",
      },
      {
        name: "live/ledger.py",
        desc: "SQLite WAL append-only ledger for trades and NAV.",
        desc_zh: "SQLite WAL 追加式 ledger，记录交易和 NAV。",
      },
      {
        name: "live/event_kill_switch.py",
        desc: "Runtime halt / halve / warning decisions.",
        desc_zh: "运行时 halt / halve / warning 决策。",
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
        desc_zh: "基于实现波动率的仓位缩放，并限制 gross exposure。",
      },
      {
        name: "pipeline/capacity_monitor.py",
        desc: "ADV occupancy checks and capacity caps.",
        desc_zh: "ADV 占比检查和容量上限。",
      },
      {
        name: "pipeline/live_vs_backtest.py",
        desc: "Live/backtest divergence metrics and alert input.",
        desc_zh: "live / backtest 偏差指标和告警输入。",
      },
      {
        name: "scripts/stress_test.py",
        desc: "Historical stress replay for current positions.",
        desc_zh: "用历史压力场景 replay 当前持仓。",
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
        desc_zh: "顶层 CLI，包含 run / backtest / compare / history / diff / doctor。",
      },
      {
        name: "pipeline/cli.py + control_surface.py",
        desc: "Research assistant and control-plane entry points.",
        desc_zh: "研究助理和 control plane 入口。",
      },
      {
        name: "dashboard/",
        desc: "FastAPI operational dashboard and routers.",
        desc_zh: "FastAPI 运维 dashboard 和路由。",
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
        desc_zh: "把 repo 产物导出成 public/data 下的结构化 JSON。",
      },
      {
        name: "portfolio/ · Next.js 14 App Router",
        desc: "SSG 静态导出（output: export）；Recharts + react-katex；Vercel 托管",
        desc_zh: "SSG 静态导出（output: export）；Recharts + react-katex；Vercel 托管。",
      },
      {
        name: "prebuild hook",
        desc: "npm run build runs export_data first, then static export.",
        desc_zh: "npm run build 先跑 export_data，再执行静态导出。",
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
        title={<Lang zh="Repo 地图" en="Repo map" />}
        subtitle={<Lang zh="真实路径，不是架构口号" en="Actual paths, not architecture slogans" />}
        description={<Lang zh="这张图展示产生研究、模拟盘状态、风控检查和静态站点的实际代码。" en="A compact map of the code that produces research, paper-trade state, risk checks, and this static site." />}
        crumbs={[{ label: "Home", href: "/" }, { label: "Infrastructure" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="grid grid-cols-1 gap-3 md:grid-cols-4">
          <EvidenceCard tone="blue" label={<Lang zh="研究" en="Research" />} value="factors" detail={<Lang zh="IC、衰减、分层、FM 检验" en="IC, decay, quintile, FM tests" />} />
          <EvidenceCard tone="green" label={<Lang zh="模拟盘" en="Paper" />} value="ledger" detail={<Lang zh="订单、NAV、kill switch" en="orders, NAV, kill switch" />} />
          <EvidenceCard tone="gold" label={<Lang zh="风控" en="Risk" />} value="Tier 1" detail={<Lang zh="波动、容量、压力、偏差" en="vol, capacity, stress, divergence" />} />
          <EvidenceCard tone="neutral" label={<Lang zh="站点" en="Site" />} value="SSG" detail={`build ${meta.git.short ?? "dirty"}`} />
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <SectionLabel
          eyebrow={<Lang zh="分层" en="Layers" />}
          title={<Lang zh={`${STACK.length} 层代码`} en={`${STACK.length} code layers`} />}
          body={<Lang zh="每一行都对应 repo 里的真实文件或目录。" en="Each row is a real file or directory in the repo." />}
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
              <Lang zh={r.desc_zh ?? r.desc} en={r.desc} />
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
