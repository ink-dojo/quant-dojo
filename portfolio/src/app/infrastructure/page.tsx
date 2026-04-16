import { PageHeader } from "@/components/layout/PageHeader";
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
        desc: "Tushare 日频 OHLCV + 复权价 loader；附数据质量断言（行数/空值/单调）",
      },
      {
        name: "utils/fundamental_loader.py",
        desc: "PE / PB / 市值等截面基本面，point-in-time join 避免未来函数",
      },
      {
        name: "utils/industry_loader.py",
        desc: "申万一级行业归类，用于因子行业中性化",
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
        desc: "66 个 alpha 因子的纯函数实现，每个带中文 docstring + 最小 __main__ 验证",
      },
      {
        name: "utils/factor_analysis.py",
        desc: "compute_ic_series / quintile_backtest / factor_decay_analysis / fama_macbeth_t",
      },
      {
        name: "scripts/audit_factor_data_coverage.py",
        desc: "扫 factor_library 产出 coverage 报告（IC 统计 + research 文件夹 + 策略覆盖）",
      },
      {
        name: "scripts/deep_analysis_hero_factors.py",
        desc: "8 个英雄因子的深度分析管道，~10 分钟跑完，产出 hero_factor_stats_*.json",
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
        desc: "固定 __init__ / run 签名 — notebook 依赖这个接口，不允许改",
      },
      {
        name: "utils/metrics.py",
        desc: "年化 / 夏普 / 回撤 / 胜率；backtest 和 live 共享同一套 metrics",
      },
      {
        name: "utils/icir_weight.py",
        desc: "v9/v10 的 ICIR 学习权重器，walk-forward 不泄漏训练窗口",
      },
    ],
  },
  {
    category: "Live / Paper",
    zh: "实盘",
    color: "var(--green)",
    rows: [
      {
        name: "live/signal_generator.py",
        desc: "日终收盘后：读当日因子 → 合成得分 → 生成 long/short 仓位",
      },
      {
        name: "live/broker_adapter.py",
        desc: "Paper broker 接口，预留 XTP/宽邮券商真实成交替换点",
      },
      {
        name: "live/reconcile.py",
        desc: "live 仓位 vs signal 期望仓位对账，发现 drift 打日志",
      },
      {
        name: "live/factor_snapshot/",
        desc: "每日因子值快照（可重放）— bug bisect 的地基",
      },
    ],
  },
  {
    category: "Control Plane",
    zh: "统一入口",
    color: "var(--gold)",
    rows: [
      {
        name: "qd run <strategy>",
        desc: "统一 runner：跑 backtest 或 live signal，复用同一组 config/metrics",
      },
      {
        name: "qd audit",
        desc: "定期扫因子库、run 产物、journal 是否匹配（发现脚本被遗弃）",
      },
      {
        name: "qd reconcile",
        desc: "对账 + 每日报表生成",
      },
    ],
  },
  {
    category: "Agentic Research",
    zh: "Agentic 层",
    color: "var(--red)",
    rows: [
      {
        name: "agents/",
        desc: "Claude / Ollama 驱动的研究助理：写因子草稿、跑 audit、交叉验证 journal 一致性",
      },
      {
        name: "admission gate (人工)",
        desc: "agent 产出不直接上 live — 任何进策略的因子/权重必须由 jialong 签字确认",
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
        desc: "AST 解析 alpha_factors.py + ROADMAP.md regex + live/ 状态 → public/data/*.json",
      },
      {
        name: "portfolio/ · Next.js 14 App Router",
        desc: "SSG 静态导出（output: export）；Recharts + react-katex；Vercel 托管",
      },
      {
        name: "prebuild hook",
        desc: "npm run build 前自动跑 export_data.py — 本站永远和 repo 最新 commit 对齐",
      },
    ],
  },
];

export default async function InfrastructurePage() {
  const meta = await readData<Meta>("meta.json");

  return (
    <>
      <PageHeader
        eyebrow="Infrastructure · 工程"
        title="Research & Execution Stack"
        subtitle="Data → Factors → Strategy → Live → Agents"
        description="把整个仓库的分层画在一张图上。每一层都有一条&ldquo;不能改&rdquo;的接口（data loader 的 assertion、BacktestEngine 的签名、metrics 的计算），其余都可以自由实验。"
        crumbs={[{ label: "Home", href: "/" }, { label: "Infrastructure" }]}
      />

      <section className="max-w-content mx-auto px-6 pb-12">
        <div className="rounded-lg border border-[var(--border-soft)] bg-[var(--bg-surface)]/40 p-5">
          <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
            设计公理
          </h2>
          <ul className="space-y-2 text-sm text-[var(--text-secondary)] leading-relaxed">
            <li>
              <span className="font-mono text-[var(--blue)]">数据质量门</span>{" "}
              — 每次 load 后 assertion：行数 &gt; 100，缺失 &lt; 10%，日期单调
            </li>
            <li>
              <span className="font-mono text-[var(--blue)]">回测 / live 共享 metrics</span>{" "}
              — 一套 utils/metrics.py 同时服务 backtest 和 paper trader
            </li>
            <li>
              <span className="font-mono text-[var(--blue)]">snapshot 可重放</span>{" "}
              — 任何信号都能从 factor_snapshot 复原，bug 可以 bisect
            </li>
            <li>
              <span className="font-mono text-[var(--blue)]">单一控制面</span>{" "}
              — qd 命令作为所有运行的唯一入口，杜绝脚本漂移
            </li>
            <li>
              <span className="font-mono text-[var(--blue)]">人类 admission gate</span>{" "}
              — agent 可以当操作员，不能当决策者
            </li>
          </ul>
        </div>
      </section>

      <section className="max-w-content mx-auto px-6 pb-16">
        <h2 className="text-sm font-mono uppercase tracking-[0.2em] text-[var(--text-tertiary)] mb-4">
          分层组件 · {STACK.length} 层
        </h2>
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
              <Dd>Python 3.11 · pandas · numpy · scipy · numba</Dd>
              <Dt>Backtest</Dt>
              <Dd>自研 BacktestEngine（固定接口）</Dd>
              <Dt>Data</Dt>
              <Dd>Tushare + parquet 本地缓存</Dd>
              <Dt>Agents</Dt>
              <Dd>claude -p subprocess / Ollama localhost · 无 API key</Dd>
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
              <Dt>Production face</Dt>
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
