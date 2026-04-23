# quant-dojo

[![English](https://img.shields.io/badge/lang-English-2563EB?style=for-the-badge)](./README.md)
[![中文](https://img.shields.io/badge/lang-中文-DC2626?style=for-the-badge)](./README.zh-CN.md)

面向 **A 股市场**的系统化研究与执行框架。
核心是预注册 (pre-registration) + walk-forward 验证 + 多层风控的研究纪律 ——
任何策略在动用真实资金之前, 必须通过同一套准入门槛.

> 项目站点: **https://quantdojo.vercel.app**
> 协议: CC BY-NC-SA 4.0

---

## 项目能力

- **30+ 个因子研究轨道** (价量 / 基本面 / 事件驱动 / LLM-native),
  每个都有可复现的 IC / ICIR / Fama-MacBeth 分析流程
- **两类策略**: 截面多因子 (`v7`–`v16` 系列) + 事件驱动 (DSR — 公司行动 / 回购)
- **回测引擎** (`backtest/engine.py`): 显式滑点 / T+1 / ST 过滤 / 幸存者偏差防护
- **Walk-forward 验证器** (`utils/walk_forward.py`): 含 López-de-Prado embargo + purged CV
- **5 项准入门槛** (Sharpe / DSR / PSR / CI 下界 / MDD)
- **模拟盘基础设施**: ACID SQLite ledger / 审计跟踪 / 与回测对账
- **三层风控**: 研究阶段 gate → 运行时 kill switch → 实时监控
  (Phase 8 加上 vol target / 偏差监控 / 容量限制)
- **Agent 层** (`agents/`): 用 `claude -p` / Ollama 做因子挖掘、reviewer 评审、
  受护栏约束的运营执行

---

## 系统架构

```
                    ┌────────────────────────────────────────────────────┐
                    │   数据源 (akshare / tushare / 本地 parquet)        │
                    └───────────────────────┬────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  utils/  数据加载 / 因子分析 / 指标 / 工具                            │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  research/factors/  每个因子单独目录: factor.py + evaluate_*.py       │
   │  utils/alpha_factors.py  注册到 factor library                        │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  strategies/  多因子 (v7..v16) + 事件驱动 (DSR)                       │
   │  backtest/    引擎 / 对比 / 标准化报告                                │
   │  utils/walk_forward.py  purged CV + embargo, OOS 评估                 │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/risk_gate.py  5-gate 准入                                   │
   │  pipeline/rx_factor_monitor.py  IC 衰减监控                           │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/daily_signal.py → active_strategy.py → orchestrator.py      │
   │  pipeline/vol_targeting.py  目标 12% 波动率的 gross 缩放              │
   │  pipeline/regime_detector.py  宏观 gate (高波动 / 低增长)             │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  live/paper_trader.py  下单 + 成交模拟                                │
   │  live/ledger.py  ACID SQLite ledger / NAV 对账                        │
   │  live/event_kill_switch.py  DD/SR/偏差驱动的 HALT/HALVE               │
   │  live/risk_monitor.py  集中度 / 暴露度 / 因子漂移                     │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/weekly_report.py + dashboard/ + portfolio/ (Next.js 站点)   │
   └───────────────────────────────────────────────────────────────────────┘
```

---

## 阶段进度

| 阶段 | 范围 | 状态 |
|------|------|------|
| 0–2  | 环境 / 数据 / 回测引擎 | ✅ 已完成 |
| 3    | 因子研究 — 30+ 轨道, IC/ICIR/FM 分析 | ✅ 已完成 |
| 4    | 多因子策略 / walk-forward / reviewer 评审 | ✅ 已完成 |
| 5    | 模拟盘基础设施 / ACID ledger / 审计 | ✅ 已完成 |
| 6    | Control plane — CLI + dashboard | ✅ 已完成 |
| 7    | Agentic research — 带 risk gate 的 AI 操作员 | ✅ 已完成 |
| **8** | **实盘 readiness — Tier 1 风控基建** | 🟡 **进行中 (2/4 已完成)** |

**当前候选策略**: `spec v4` — RIAD + DSR #30 BB-only 50/50 组合.
SR 1.87, PSR 0.998, DSR 0.920, MDD −4.86%; 通过 4/5 门槛, 待 Phase 8 Tier 1
完成后上线. spec 已锁死在
`journal/paper_trade_spec_v4_riad_dsr30_combo_20260422.md`.

---

## 仓库结构

```
utils/             可复用的基础组件
                   ├── data_loader, fundamental_loader, tushare_loader  (数据接入)
                   ├── factor_analysis, multi_factor, alpha_factors     (因子框架)
                   ├── metrics, walk_forward, purged_cv                 (验证)
                   ├── risk_overlay, position_sizing, stop_loss         (风控数学)
                   └── tradability_filter, universe, capacity           (universe 构造)

research/          各因子研究目录 + notebooks
research/factors/  31 个因子轨道, 每个含 factor.py + evaluate_*.py

strategies/        策略实现
                   ├── multi_factor.py        (截面 v7..v16)
                   └── examples/, generated/  (模板 + 自动生成)

backtest/          事件驱动引擎: engine.py, comparison.py, standardized.py

pipeline/          每日编排 (27 个模块)
                   ├── daily_signal, active_strategy, orchestrator      (信号 → 下单)
                   ├── risk_gate, rx_factor_monitor                     (研究阶段 gate)
                   ├── vol_targeting, regime_detector                   (Phase 8 风控)
                   ├── live_vs_backtest                                 (漂移监控)
                   ├── weekly_report, alert_notifier                    (报告)
                   └── experiment_runner, experiment_summarizer         (研究管理)

live/              模拟盘 + ACID ledger
                   ├── paper_trader, event_paper_trader                 (执行模拟)
                   ├── ledger.py                                        (SQLite, atomic)
                   ├── event_kill_switch                                (DSR #30 spec v2 §5)
                   ├── risk_monitor                                     (集中度 / 漂移)
                   └── broker_adapter                                   (broker 无关 API)

agents/            LLM 操作员 (claude -p / Ollama fallback)
                   ├── factor_miner, factor_analyst, factor_doctor     (研究 agent)
                   ├── debate, fund_manager                            (评审)
                   └── executor_agent                                   (受 gate 约束执行)

dashboard/         FastAPI + Streamlit 运维 dashboard
portfolio/         Next.js 公开站点 (部署到 Vercel)
scripts/           数据回填 / 审计 / 一次性分析 (60+ 脚本)
tests/             pytest — 38 个模块, 647 个 test
journal/           周报 + 调查纪要 (项目 "实验日志")
```

---

## 信号生命周期 (一个交易日)

```
T-1 收盘后        T 早上            T 09:25        T 15:00         T 16:00
数据更新     →   信号生成      →   下单      →    成交      →    对账
(scripts/    →   (pipeline/    →   (live/    →    (live/    →    (pipeline/
 daily_      →    daily_        →   paper_   →     ledger)  →     live_vs_backtest)
 update.sh)  →    signal.py)    →   trader)  →                →    + kill_switch 评估
                                                              →    + 告警
```

每一步都写结构化日志 (`logs/`) 和 ledger (`live/ledger.db`),
任何后续决策都能追溯到输入数据的指纹.

---

## 研究方法论

| 工具 | 用途 | 位置 |
|------|------|------|
| **Walk-Forward** | 训练/测试滚动窗口, 防止 look-ahead | `utils/walk_forward.py` |
| **Purged CV** | embargo 期 (López de Prado), 去除序列重叠 | `utils/purged_cv.py` |
| **DSR** | Deflated Sharpe Ratio — 选择偏差校正 | `utils/metrics.py` |
| **PSR** | Probabilistic Sharpe Ratio | `utils/metrics.py` |
| **5-Gate** | 准入硬门槛 | `pipeline/risk_gate.py` |

### 5-gate 准入门槛 (任何候选策略上模拟盘前必过)

| 指标 | 阈值 |
|------|------|
| 年化收益 | ≥ 15% |
| Sharpe ratio | ≥ 0.8 |
| 最大回撤 | > −30% |
| PSR (Probabilistic Sharpe) | ≥ 95% |
| Sharpe CI 下界 | ≥ 0.5 |

门槛在 `CLAUDE.md` 中硬编码, **不会因某个候选策略而调整**.

---

## 风控架构

三层, 每层管不同的时间尺度:

| 层 | 责任模块 | 时间尺度 | 触发条件 |
|----|----------|----------|----------|
| **研究阶段 gate** | `pipeline/risk_gate.py` | 部署前 | 5-gate 准入 (见上) |
| **运行时 kill switch** | `live/event_kill_switch.py` | 每日 | DD > 20%, 30 日 SR < 0, 月 MDD > 12%, T+3mo/6mo 快速 check |
| **实时监控** | `live/risk_monitor.py` | 每次调仓 | 集中度 / 行业暴露 / 因子暴露 / 仓位规模 |

**Phase 8 新增** (进行中) 在三层之上加**事前**控制:

- `pipeline/vol_targeting.py` — gross 缩放至目标 12% 年化波动率
- `pipeline/live_vs_backtest.py` 每日 z-score 偏差告警 + kill 联动
- `pipeline/regime_detector.py` — 宏观 gate (波动率/增长 regime
  跨过学习阈值时切现金)
- `pipeline/capacity_monitor.py` (TODO #39) — 单股 ADV 占比限制
- `scripts/stress_test.py` (TODO #40) — 当前组合在历史极端日 replay
  (2015-08, 2020-02, 2024-09)

完整路线图: `journal/risk_infra_roadmap_phase8_20260423.md`.

---

## 快速开始

```bash
# 1. 安装 (editable, 需 Python ≥ 3.11)
pip install -e .

# 2. 验证环境
python -c "from utils import get_stock_history; from agents import LLMClient; print('env ok')"

# 3. 查看 CLI 接口
quant_dojo --help

# 4. 跑测试套件 (647 个 test, 约 30 秒)
pytest -q

# 5. 跑单因子分析 demo (用 akshare, 不需要 API key)
python -m research.factors.low_vol.factor
```

数据后端: **akshare** (免费, 无需 key) + **tushare** (免费 tier).
所有公开研究轨道都不需要付费数据源.

---

## 核心文档

| 文件 | 用途 |
|------|------|
| `ROADMAP.md` | 阶段路线图, 含里程碑 |
| `TODO.md` | 当前任务清单 (在线维护) |
| `CLAUDE.md` | 项目规则 (Claude Code agent 自动加载) |
| `WORKFLOW.md` | Git 工作流 / commit 规范 / 分支策略 |
| `BRAINSTORM.md` | 设计决策 / 取舍 / 备选方案 |
| `ALPHA_THEORY_2026.md` | 当前 alpha 理论 + 探索方向 |
| `CHINA_QUANT_GUIDE.md` | A 股市场参考 (T+1, ST, 费率等) |
| `journal/risk_infra_roadmap_phase8_20260423.md` | Phase 8 可执行计划 |
| `journal/paper_trade_spec_v4_*.md` | 当前实盘策略规格 |

---

## 研究展示站点

`portfolio/` 目录是一个 Next.js 静态站点, 发布因子库 / 策略时间线 /
DSR 事件驱动记录 / 方法论术语表.

```bash
cd portfolio
npm install
npm run build          # 静态 export → out/
vercel deploy --prod   # 部署到 https://quantdojo.vercel.app
```

---

## 协议

CC BY-NC-SA 4.0 — 见 [LICENSE](./LICENSE).
非商业用途, 须署名; 衍生作品须采用相同协议 (share-alike).
