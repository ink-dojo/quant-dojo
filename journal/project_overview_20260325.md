# quant-dojo 项目概览 — 2026-03-25

> 两天工作（3/24-3/25），68 个 commit。从"控制面未收口"推进到"策略差门槛 1%"。

---

## 项目定位

A 股多因子量化策略研究与执行系统。三人团队（jialong + xingyu），目标是建一套可持续迭代的策略开发 → 验证 → 模拟盘 → 实盘的完整工程链路。

---

## 当前架构

```
quant-dojo/
├── utils/                    # 核心工具库
│   ├── alpha_factors.py      # 因子库（15 快速 + 5 慢速）
│   ├── market_regime.py      # 择时策略库（7 种）
│   ├── factor_analysis.py    # IC/ICIR/分层/中性化/合成
│   ├── metrics.py            # 绩效指标
│   ├── tradability_filter.py # 可交易性过滤
│   ├── local_data_loader.py  # 本地 CSV 加载（5477 只 A 股）
│   ├── data_loader.py        # 指数/远程数据
│   └── walk_forward.py       # 滚动样本外验证
│
├── providers/                # 数据源抽象层
│   ├── base.py               # 抽象基类 + ProviderError
│   ├── akshare_provider.py   # AkShare（日线主力，偶尔不可用）
│   ├── baostock_provider.py  # BaoStock（备选，免费无限制）
│   └── sina_provider.py      # 新浪实时行情（800只/1.5秒）
│
├── pipeline/                 # 执行管道
│   ├── cli.py                # 统一 CLI 命令树（30+ 命令）
│   ├── control_surface.py    # AI-safe 控制面（审批门 + 只读/变更分离）
│   ├── daily_signal.py       # 每日信号生成
│   ├── data_update.py        # 数据增量更新（AkShare/BaoStock 自动降级）
│   ├── data_checker.py       # Freshness 契约
│   ├── live_data_service.py  # 实时数据服务（轮询 + EOD 自动更新）
│   ├── run_store.py          # 回测运行记录持久化
│   ├── strategy_registry.py  # 策略注册表
│   └── weekly_report.py      # 周报生成
│
├── strategies/               # 策略实现
│   ├── multi_factor.py       # 多因子选股策略
│   └── base.py               # 策略基类
│
├── backtest/                 # 回测引擎
│   └── engine.py             # BacktestEngine
│
├── live/                     # 模拟盘
│   ├── paper_trader.py       # 虚拟持仓管理
│   └── risk_monitor.py       # 风险预警
│
├── dashboard/                # Web 工作台
│   ├── app.py                # FastAPI 主应用
│   ├── routers/              # API 路由（9 个模块）
│   ├── services/             # 业务服务层
│   └── static/index.html     # 前端（Tailwind + Chart.js）
│
├── scripts/                  # 研究/评估脚本
│   ├── strategy_eval.py      # v2/v3 策略评估
│   ├── strategy_v4.py        # v4 行业中性策略
│   ├── strategy_v5.py        # v5 全因子库评估
│   └── batch_update.py       # 全量数据更新
│
├── research/                 # 研究资料
│   ├── factors/              # 因子研究（momentum/value/quality/low_vol）
│   └── notebooks/            # Jupyter 研究 notebook（01-13）
│
├── journal/                  # 工作记录
│   ├── weekly/               # 周报
│   ├── strategy_eval_*.md    # 策略评估报告
│   ├── methodology_gap_*.md  # 方法论差距分析
│   └── full_factor_*.md      # 因子库分析报告
│
└── tests/                    # 自动化测试（70+ 测试）
    ├── test_control_plane.py
    ├── test_e2e_control_plane.py
    ├── test_phase5_smoke.py
    ├── test_data_checker.py
    ├── test_data_update.py
    └── test_live_data.py
```

---

## 因子库（19 个因子）

### 快速因子（14 个，向量化秒级计算）

| 类别 | 因子 | ICIR | FM t值 | 状态 |
|------|------|------|--------|------|
| **行为金融** | team_coin（球队硬币） | **0.45** | **5.08** | 最强，双杀 |
| **行为金融** | str_salience（凸显理论） | **0.43** | 0.14 | ICIR强，FM被吸收 |
| **技术** | low_vol_20d（低波动） | 0.34 | **2.83** | 双杀 |
| **行为金融** | cgo_simple（处置效应） | 0.33 | **3.38** | 双杀 |
| **技术** | reversal_1m | 0.31 | 0.94 | 仅IC |
| **技术** | turnover_rev | 0.31 | -1.20 | 与low_vol共线0.98 |
| **基本面** | bp | 0.28 | **1.94** | 双杀 |
| **技术** | enhanced_mom_60 | 0.27 | **2.94** | 双杀 |
| **技术** | quality_mom_60 | 0.26 | 1.50 | 与enhanced共线0.92 |
| **基本面** | ep | 0.22 | -1.61 | FM反向 |
| **微观结构** | shadow_upper | 0.08 | — | 无效 |
| **微观结构** | shadow_lower | -0.38 | — | 无效 |
| **技术** | ma_ratio_120 | -0.30 | — | 无效 |
| **基本面** | roe | -0.03 | — | 无效 |

### 最优 5 因子组合（FM 双杀验证）

**team_coin(30%) + low_vol(25%) + cgo(20%) + enhanced_mom(15%) + bp(10%)**

### 慢因子（5 个，逐行循环，研究用）

amplitude_hidden, w_reversal, network_scc, chip_arc, chip_vrc, cgo(full)

---

## 择时策略库（7 种）

| 策略 | 年化(HS300) | 夏普 | 回撤 | 偷看风险 |
|------|------------|------|------|---------|
| 无择时 | +1.1% | -0.04 | -47% | — |
| RSRS | +5.7% | 0.23 | -42% | 无 |
| **LLT** | +29.5% | 1.97 | -11% | 延迟1天后骤降 |
| **高阶矩** | +31.9% | 2.17 | -16% | 延迟1天后骤降 |
| 波动剪刀差 | +16.8% | 0.92 | -17% | 待验证 |
| 价量共振 | +5.8% | 0.23 | -32% | 无 |
| ICU均线 | +89.5% | 6.35 | -9% | 过拟合 |
| **多数投票** | +28.5% | 1.87 | -12% | 月频可用 |

**注意**：LLT 和高阶矩在日频信号延迟 1 天后效果大幅下降。但在月频换仓中（月初换仓天然延迟）仍有效。

---

## 策略演进（v1 → v6）

| 版本 | 因子 | 择时 | 持股 | IS年化 | IS夏普 | IS回撤 | OOS年化 |
|------|------|------|------|--------|--------|--------|---------|
| v1 | 4等权含momentum | 无 | 30 | -17.7% | -0.83 | -95% | — |
| v2 | 3 IC加权 | 无 | 30 | +1.9% | -0.01 | -64% | +17.7% |
| v3 | 3 + RSRS | RSRS | 30 | +6.8% | 0.34 | -45% | — |
| v4 | 5 + 行业中性 | RSRS | 100 | +12.0% | 0.66 | -37% | +18.6% |
| v5 | 8 全因子 | RSRS | 100 | +10.6% | 0.51 | -46% | +19.3% |
| **v6** | **5 FM双杀** | **多数投票** | **100** | **+15.4%** | **0.88** | **-19%** | **+19.6%** |
| v6(lag1) | 同上 | 延迟1天 | 100 | +14.0% | 0.77 | -30% | +17.6% |

### Phase 5 门槛

| 指标 | 门槛 | v6 乐观 | v6 保守(lag1) |
|------|------|---------|-------------|
| 年化 > 15% | 15% | ✅ 15.4% | ❌ 14.0% (差1%) |
| 夏普 > 0.8 | 0.8 | ✅ 0.88 | ❌ 0.77 (差0.03) |
| 回撤 < 30% | 30% | ✅ 19.3% | ❌ 30.2% (差0.2%) |

**乐观估计三项全过，保守估计差一步之遥。**

---

## 数据体系

| 数据 | 来源 | 状态 | 覆盖 |
|------|------|------|------|
| 日线 OHLCV | BaoStock / AkShare | ✅ | 5477 只，2000-2026 |
| PE/PB/PS/PCF | 本地 CSV + parquet 缓存 | ✅ | 同上 |
| 换手率 | 本地 CSV | ✅ | 同上 |
| 行业分类 | BaoStock | ✅ | 83 行业 |
| 实时行情 | Sina Finance | ✅ | 800只/1.5秒 |
| 指数数据 | 本地 / AkShare | ✅ | HS300 |
| 财务(ROE等) | 从 PE/PB 推导 | ✅ | 近似值 |

---

## 工程基础设施

### 已完成

- **Control Plane** — CLI + API + Dashboard 统一入口，三轮 review 收敛
- **数据管道** — AkShare/BaoStock/Sina 三源自动降级
- **实时数据** — 盘中轮询 + 收盘 EOD + auto 模式
- **Dashboard** — 持仓/选股/因子/风险/回测/实时行情
- **测试** — 70+ 自动化测试
- **Autoloop** — opus supervisor + opus worker + 内存看门狗

### 待做

- 个股止损机制
- 组合优化（MVO 替代等权）
- 模拟盘 NAV 追踪修复
- 分钟线数据接入
- 北向资金/龙虎榜数据

---

## 下一步优先级

| 优先级 | 任务 | 预期效果 |
|--------|------|---------|
| 1 | 个股止损（-15% 强制卖出） | 回撤从 -30% → -20% |
| 2 | 双周换仓（月频 → 双周） | 反转/team_coin 更高频有效 |
| 3 | 组合优化（最小化 CVaR） | 夏普 +0.1~0.2 |
| 4 | 修复模拟盘 NAV 追踪 | 可以开始真正模拟运行 |
| 5 | 接入分钟线（BaoStock 30min） | 解锁 CPV/聪明钱/APM 完整版 |

**核心判断：策略差门槛 1%。个股止损 + 双周换仓两项合计大概率能突破。**
