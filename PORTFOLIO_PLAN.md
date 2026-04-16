# QuantDojo Portfolio Website — 完整实现规划

> **目标**：在 `quant-dojo/portfolio/` 目录下构建一个面向量化金融面试官的研究展示网站。
> 展示完整的量化研究流程、60+ 因子库、策略构建方法论及工程深度。
>
> **核心原则**：图表和可视化为主体，代码为次要可折叠内容；多层级下钻导航（最深4层）；数据驱动，不堆砌文字。

---

## 技术栈

| 层 | 技术 | 用途 |
|---|---|---|
| 框架 | Next.js 14 (App Router) | 文件路由、SSG、TypeScript |
| 样式 | Tailwind CSS | 工具类样式系统 |
| 图表 | Recharts | 净值曲线、IC走势、分层回测 |
| 动画 | Framer Motion | 滚动驱动动画、卡片悬浮、页面切换 |
| 代码高亮 | Shiki | 因子代码块展示 |
| 公式 | KaTeX (react-katex) | 因子数学公式渲染 |
| 数据 | 静态 JSON（Python 脚本导出） | 无需运行时 quant-dojo |

---

## 一、色彩系统与设计 Token

```css
/* src/styles/globals.css */
:root {
  /* Backgrounds — 深色主题，Bloomberg Terminal 风格 */
  --bg-base:      #0B0F19;   /* 主背景 */
  --bg-surface:   #141928;   /* 卡片/面板 */
  --bg-elevated:  #1C2438;   /* 悬浮层/下拉菜单 */
  --bg-hover:     #222D45;

  /* Borders */
  --border:       #2A3350;
  --border-soft:  #1E2840;

  /* Text */
  --text-primary:   #E8EDF5;
  --text-secondary: #7A8BA8;
  --text-tertiary:  #4A5A70;
  --text-mono:      #B8C8E8;   /* 数字/代码专用 */

  /* 语义色 */
  --green:   #00C896;   /* 正收益 */
  --red:     #E84545;   /* 负收益 */
  --blue:    #4F8EF7;   /* 数据/链接 */
  --gold:    #F5A623;   /* 高亮/核心因子 */
  --purple:  #9B72F7;   /* 研究/因子 */
  --cyan:    #00D4FF;   /* 流动性因子 */

  /* 因子类别色 */
  --cat-technical:      #4F8EF7;
  --cat-fundamental:    #00C896;
  --cat-microstructure: #9B72F7;
  --cat-behavioral:     #F5A623;
  --cat-chip:           #E84545;
  --cat-liquidity:      #00D4FF;
  --cat-extended:       #7A8BA8;

  /* 字体 */
  --font-body: 'Inter', sans-serif;
  --font-mono: 'IBM Plex Mono', monospace;
}
```

---

## 二、完整文件结构

```
quant-dojo/portfolio/
│
├── package.json
├── next.config.ts
├── tailwind.config.ts
├── tsconfig.json
│
├── public/
│   └── data/                         ← Python 脚本生成的静态 JSON（只读）
│       ├── factors/
│       │   ├── index.json            ← 全部因子摘要（卡片墙数据源）
│       │   ├── categories.json       ← 类别元数据（名称、颜色、数量）
│       │   ├── momentum.json         ← 单因子详情（含时间序列）
│       │   ├── value.json
│       │   ├── quality.json
│       │   ├── low_volatility.json
│       │   └── [factor_slug].json    ← 每个因子一个文件，共 60+
│       ├── strategy/
│       │   ├── construction.json     ← 7步构建流程 + 因子权重
│       │   └── versions.json         ← v7-v16 版本历史对比
│       ├── backtest/
│       │   ├── equity_curve.json     ← 净值时间序列（策略 vs CSI 300）
│       │   ├── monthly_returns.json  ← 月度收益矩阵（年 × 月）
│       │   ├── drawdown.json         ← 回撤时间序列
│       │   ├── metrics.json          ← Sharpe/Calmar/最大回撤等汇总
│       │   └── walk_forward.json     ← OOS 各窗口结果
│       ├── live/
│       │   ├── portfolio.json        ← 当前持仓（30只）
│       │   └── nav_history.json      ← NAV 走势
│       └── journey/
│           └── phases.json           ← 8个开发阶段详情
│
├── scripts/
│   └── export_data.py                ← 从 quant-dojo 导出所有 JSON（见第四节）
│
└── src/
    ├── app/
    │   ├── layout.tsx                ← 全局布局（Navbar + 字体 + providers）
    │   ├── page.tsx                  ← 主页 Home
    │   │
    │   ├── research/
    │   │   ├── page.tsx              ← 研究总览（入口卡片网格）
    │   │   ├── methodology/
    │   │   │   └── page.tsx          ← 方法论（IC理论、分层回测、衰减分析）
    │   │   ├── core-factors/
    │   │   │   ├── page.tsx          ← 4大核心因子网格
    │   │   │   └── [slug]/
    │   │   │       └── page.tsx      ← 核心因子详情（含 notebook viewer）
    │   │   ├── factor-library/
    │   │   │   ├── page.tsx          ← 全因子库（可筛选卡片墙，60+）
    │   │   │   └── [category]/
    │   │   │       ├── page.tsx      ← 类别视图（该类别所有因子）
    │   │   │       └── [factor]/
    │   │   │           └── page.tsx  ← 最深层：单因子完整详情
    │   │   └── studies/
    │   │       └── page.tsx          ← 专项研究（行业中性、因子相关性等）
    │   │
    │   ├── strategy/
    │   │   ├── page.tsx              ← 策略总览
    │   │   ├── framework/
    │   │   │   └── page.tsx          ← 滚动驱动7步构建流程动画
    │   │   ├── versions/
    │   │   │   ├── page.tsx          ← 版本时间线（v7→v16）
    │   │   │   └── [version]/
    │   │   │       └── page.tsx      ← 单版本详情（改动点+性能对比）
    │   │   └── risk/
    │   │       └── page.tsx          ← 风险管理（仓位/止损/集中度）
    │   │
    │   ├── validation/
    │   │   ├── page.tsx              ← 验证体系总览
    │   │   ├── methodology/
    │   │   │   └── page.tsx          ← 生存者偏差修正、前视偏差防止
    │   │   ├── results/
    │   │   │   └── page.tsx          ← 回测结果（净值曲线+热力图+指标）
    │   │   ├── walk-forward/
    │   │   │   └── page.tsx          ← 样本外验证（各窗口Sharpe分布）
    │   │   └── stress-tests/
    │   │       └── page.tsx          ← 压力测试（2015/2020/2022情景）
    │   │
    │   ├── live/
    │   │   └── page.tsx              ← 实盘模拟（持仓/NAV/漂移分析）
    │   │
    │   ├── infrastructure/
    │   │   ├── page.tsx              ← 工程架构总览
    │   │   ├── data-pipeline/
    │   │   │   └── page.tsx          ← 数据管道（AkShare/CSV/版本控制）
    │   │   ├── system/
    │   │   │   └── page.tsx          ← 系统架构（模块图/CLI命令）
    │   │   ├── testing/
    │   │   │   └── page.tsx          ← 测试体系（30文件/300+用例）
    │   │   └── ai-agents/
    │   │       └── page.tsx          ← Phase 7 AI 研究助手（15个模块）
    │   │
    │   └── journey/
    │       └── page.tsx              ← 开发历程（8 Phase 可点击时间线）
    │
    ├── components/
    │   ├── layout/
    │   │   ├── Navbar.tsx            ← 顶部导航（6个主导航项 + 面包屑）
    │   │   ├── Breadcrumb.tsx        ← 多级面包屑（research > factor-library > behavioral > cgo）
    │   │   └── PageHeader.tsx        ← 页面标题区域（标题+副标题+描述）
    │   │
    │   ├── home/
    │   │   ├── Hero.tsx              ← 全屏英雄区（动态计数器 + 系统流程图）
    │   │   ├── MetricCounter.tsx     ← 数字计数动画（60+ factors, 8 phases...）
    │   │   ├── SystemFlowDiagram.tsx ← 可点击流程图（数据→因子→策略→验证→实盘）
    │   │   └── SectionCard.tsx       ← 各模块预览入口卡片
    │   │
    │   ├── factor/
    │   │   ├── FactorCard.tsx        ← 因子卡片（迷你sparkline + ICIR圆环 + 悬浮效果）
    │   │   ├── FactorGrid.tsx        ← 可筛选网格容器
    │   │   ├── FactorFilter.tsx      ← 筛选栏（类别/状态/IC阈值/搜索）
    │   │   ├── FormulaDisplay.tsx    ← KaTeX 数学公式渲染（含经济学直觉说明）
    │   │   ├── ICTrendChart.tsx      ← IC 时间序列折线图（Recharts）
    │   │   ├── QuintileChart.tsx     ← Q1-Q5 分层回测柱状图（含 Long-Short 标注）
    │   │   ├── DecayChart.tsx        ← 因子衰减曲线（半衰期标注）
    │   │   └── CodeCollapsible.tsx   ← Shiki 高亮代码块（默认折叠）
    │   │
    │   ├── strategy/
    │   │   ├── ConstructionFlow.tsx  ← 滚动驱动7步流程（左侧sticky导航+右侧内容）
    │   │   ├── StepDetail.tsx        ← 单步详情（图标/说明/代码片段）
    │   │   ├── WeightRadar.tsx       ← 因子权重雷达图（Recharts RadarChart）
    │   │   └── VersionTimeline.tsx   ← 版本演进时间线
    │   │
    │   ├── backtest/
    │   │   ├── EquityCurve.tsx       ← 交互式净值曲线（hover显示日期/收益/alpha）
    │   │   ├── DrawdownChart.tsx     ← 回撤面积图
    │   │   ├── MonthlyHeatmap.tsx    ← 月度收益热力图（年×月，颜色编码）
    │   │   └── MetricGrid.tsx        ← 性能指标卡片组（Sharpe/Calmar/MDD等）
    │   │
    │   ├── live/
    │   │   ├── HoldingsTable.tsx     ← 当前持仓表（股票/权重/浮盈）
    │   │   ├── NAVChart.tsx          ← NAV走势图
    │   │   └── DriftAnalysis.tsx     ← 实盘 vs 回测漂移分析
    │   │
    │   ├── journey/
    │   │   ├── PhaseTimeline.tsx     ← 竖向时间线容器
    │   │   └── PhaseCard.tsx         ← 可展开的阶段卡片（交付物/关键决策/指标）
    │   │
    │   └── ui/                       ← 基础 UI 原子组件
    │       ├── GaugeRing.tsx         ← SVG 圆环仪表（ICIR可视化，绿/橙/红三档）
    │       ├── MiniSparkline.tsx     ← 迷你折线图（因子卡片用，SVG）
    │       ├── ScrollReveal.tsx      ← Framer Motion 滚动进入动画包装器
    │       ├── Badge.tsx             ← 类别/状态标签（带类别色）
    │       ├── Tooltip.tsx           ← 悬浮提示（热力图/图表用）
    │       └── StatBar.tsx           ← 水平进度条指标（IC+% 等）
    │
    └── lib/
        ├── data.ts                   ← fetch JSON 辅助函数（带缓存）
        ├── formatters.ts             ← 数字/日期/百分比格式化
        └── constants.ts              ← 路由/类别/颜色常量
```

---

## 三、完整路由站点地图（约 200 个视图）

```
/ ─────────────────────────────────── 主页 Home
│
├── /research ─────────────────────── 研究总览
│   ├── /research/methodology ──────── 方法论
│   ├── /research/core-factors ─────── 4大核心因子网格
│   │   ├── /…/momentum ─────────────── 动量因子（含 notebook）
│   │   ├── /…/value ────────────────── 价值因子
│   │   ├── /…/quality ──────────────── 质量因子
│   │   └── /…/low-volatility ───────── 低波动因子
│   ├── /research/factor-library ───── 全因子库（60+，可筛选）
│   │   ├── /…/technical ──────────────  技术类（6个）
│   │   │   ├── /…/reversal-1m
│   │   │   ├── /…/low-vol-20d
│   │   │   ├── /…/enhanced-momentum
│   │   │   ├── /…/quality-momentum
│   │   │   ├── /…/ma-ratio-momentum
│   │   │   └── /…/turnover-rev
│   │   ├── /…/fundamental ────────────  基本面类（7个）
│   │   │   ├── /…/ep-factor
│   │   │   ├── /…/bp-factor
│   │   │   ├── /…/roe-factor
│   │   │   ├── /…/accruals-quality
│   │   │   ├── /…/earnings-momentum
│   │   │   ├── /…/dividend-yield
│   │   │   └── /…/cfo-accrual-quality
│   │   ├── /…/microstructure ─────────  微观结构类（6个）
│   │   │   ├── /…/shadow-upper
│   │   │   ├── /…/shadow-lower
│   │   │   ├── /…/amplitude-hidden
│   │   │   ├── /…/w-reversal
│   │   │   ├── /…/price-volume-divergence
│   │   │   └── /…/insider-buying-proxy
│   │   ├── /…/behavioral ─────────────  行为金融类（4个）
│   │   │   ├── /…/cgo
│   │   │   ├── /…/str-salience
│   │   │   ├── /…/team-coin
│   │   │   └── /…/relative-turnover
│   │   ├── /…/chip ───────────────────  筹码结构类（4个）
│   │   │   ├── /…/chip-arc
│   │   │   ├── /…/chip-vrc
│   │   │   ├── /…/chip-src
│   │   │   └── /…/chip-krc
│   │   ├── /…/liquidity ──────────────  流动性类（2个）
│   │   │   ├── /…/amihud-illiquidity
│   │   │   └── /…/bid-ask-spread-proxy
│   │   └── /…/extended ───────────────  扩展研究（28个）
│   │       ├── /…/high-52w-ratio
│   │       ├── /…/return-skewness-20d
│   │       ├── /…/beta-factor
│   │       ├── /…/max-ret-1m
│   │       ├── /…/bollinger-pct
│   │       ├── /…/volume-surge
│   │       ├── /…/rsi-factor
│   │       ├── /…/chaikin-money-flow
│   │       ├── /…/sharpe-20d
│   │       └── … 其余19个因子
│   └── /research/studies ──────────── 专项研究
│
├── /strategy ─────────────────────── 策略总览
│   ├── /strategy/framework ─────────── 7步构建流程（scroll动画）
│   ├── /strategy/versions ──────────── 版本演进时间线
│   │   ├── /…/v7 ───────────────────── 当前活跃（IC权重+行业中性）
│   │   ├── /…/v8 ───────────────────── 制度自适应变体
│   │   ├── /…/v9  /…/v10  /…/v11
│   │   ├── /…/v13  /…/v16
│   └── /strategy/risk ──────────────── 风险管理
│
├── /validation ───────────────────── 验证体系
│   ├── /validation/methodology ─────── 方法论（生存者偏差/前视偏差）
│   ├── /validation/results ─────────── 回测结果（图表中心页）
│   ├── /validation/walk-forward ─────── 样本外验证
│   └── /validation/stress-tests ─────── 压力测试
│
├── /live ─────────────────────────── 实盘模拟
│
├── /infrastructure ───────────────── 工程架构
│   ├── /infrastructure/data-pipeline
│   ├── /infrastructure/system
│   ├── /infrastructure/testing
│   └── /infrastructure/ai-agents
│
└── /journey ──────────────────────── 开发历程（8 Phases）
```

---

## 四、静态 JSON 数据 Schema

### `public/data/factors/index.json`
```json
{
  "factors": [
    {
      "slug": "cgo",
      "name": "CGO",
      "label": "处置效应",
      "category": "behavioral",
      "categoryLabel": "行为金融",
      "status": "experimental",
      "direction": -1,
      "ic_mean": 0.023,
      "ic_std": 0.056,
      "icir": 0.41,
      "t_stat": 3.8,
      "ic_positive_pct": 0.62,
      "half_life_days": 22,
      "rebalance_freq": "monthly",
      "sparkline": [0.018, 0.024, 0.021, 0.027, 0.019, 0.023, 0.025, 0.022],
      "long_short_return_annual": 21.0,
      "long_short_sharpe": 1.34,
      "in_strategy_v7": false
    }
  ],
  "categories": [
    { "id": "technical",      "label": "技术类",   "count": 6,  "color": "#4F8EF7" },
    { "id": "fundamental",    "label": "基本面",   "count": 7,  "color": "#00C896" },
    { "id": "microstructure", "label": "微观结构", "count": 6,  "color": "#9B72F7" },
    { "id": "behavioral",     "label": "行为金融", "count": 4,  "color": "#F5A623" },
    { "id": "chip",           "label": "筹码结构", "count": 4,  "color": "#E84545" },
    { "id": "liquidity",      "label": "流动性",   "count": 2,  "color": "#00D4FF" },
    { "id": "extended",       "label": "扩展研究", "count": 28, "color": "#7A8BA8" }
  ],
  "summary": {
    "total_factors": 62,
    "active_factors": 4,
    "avg_icir": 0.43,
    "avg_half_life_days": 19
  }
}
```

### `public/data/factors/[slug].json`（单因子详情）
```json
{
  "slug": "momentum",
  "name": "Enhanced Momentum",
  "label": "风险调整动量",
  "category": "technical",
  "status": "active",
  "formula_latex": "Mom = \\frac{P_t - P_{t-60}}{P_{t-60}} - 3000\\cdot\\sigma^2",
  "economic_intuition": "动量效应源于投资者对信息的缓慢反应（under-reaction）。风险调整项 3000σ² 剔除了高波动股票的虚假动量，使因子更稳定。",
  "stats": {
    "ic_mean": 0.031,
    "ic_std": 0.058,
    "icir": 0.53,
    "t_stat": 4.2,
    "ic_positive_pct": 0.67,
    "half_life_days": 18,
    "rebalance_freq": "monthly",
    "long_short_annual": 22.1,
    "long_short_sharpe": 1.45
  },
  "ic_series": [
    { "date": "2024-01", "ic": 0.031 },
    { "date": "2024-02", "ic": 0.028 }
  ],
  "decay_curve": [
    { "lag": 1,  "ic": 0.031 },
    { "lag": 5,  "ic": 0.027 },
    { "lag": 10, "ic": 0.021 },
    { "lag": 21, "ic": 0.012 },
    { "lag": 42, "ic": 0.006 },
    { "lag": 63, "ic": 0.003 }
  ],
  "quintile": {
    "labels": ["Q1 (多)", "Q2", "Q3", "Q4", "Q5 (空)"],
    "annual_returns": [22.1, 14.3, 10.8, 7.2, 1.4],
    "sharpes":        [1.45, 0.98, 0.72, 0.51, 0.12]
  },
  "implementation_code": "def enhanced_momentum(close: pd.DataFrame, lookback: int = 60) -> pd.Series:\n    ret = close.pct_change(lookback)\n    sigma2 = close.pct_change().rolling(20).var()\n    return ret - 3000 * sigma2",
  "notebook_path": "research/notebooks/03_momentum_factor.ipynb",
  "related_factors": ["quality_momentum", "ma_ratio_momentum", "momentum_6m_skip1m"],
  "in_strategy_v7": true,
  "v7_weight": 0.32
}
```

### `public/data/backtest/equity_curve.json`
```json
{
  "benchmark_label": "CSI 300",
  "series": [
    { "date": "2015-01-01", "strategy": 1.000, "benchmark": 1.000 },
    { "date": "2015-02-01", "strategy": 1.038, "benchmark": 1.021 }
  ],
  "metrics": {
    "annual_return":  0.213,
    "total_return":   2.847,
    "sharpe":         1.23,
    "sortino":        1.67,
    "calmar":         0.87,
    "max_drawdown":  -0.183,
    "max_dd_start":  "2015-06-01",
    "max_dd_end":    "2015-08-26",
    "win_rate":       0.627,
    "volatility":     0.168,
    "beta":           0.62,
    "alpha":          0.156
  },
  "benchmark_metrics": {
    "annual_return": 0.072,
    "sharpe": 0.41,
    "max_drawdown": -0.467
  }
}
```

### `public/data/backtest/monthly_returns.json`
```json
{
  "returns": {
    "2026": { "Jan": 0.021, "Feb": -0.013, "Mar": 0.045, "Apr": 0.018 },
    "2025": { "Jan": 0.031, "Feb": 0.018, "Mar": -0.022, "Apr": 0.041,
              "May": -0.008, "Jun": 0.032, "Jul": 0.041, "Aug": -0.022,
              "Sep": 0.015, "Oct": 0.028, "Nov": 0.019, "Dec": 0.033 },
    "2024": {}
  }
}
```

### `public/data/strategy/construction.json`
```json
{
  "steps": [
    {
      "id": 1,
      "title": "宇宙定义",
      "subtitle": "Universe Definition",
      "description": "从5477只A股出发，动态过滤ST股、新股（上市<180天）、停牌股",
      "detail": "每日基于当期 listing_metadata 重建可交易宇宙，确保历史回测不引入生存者偏差。每期约剩 3,800 只可交易标的。",
      "stat": "5,477 → ~3,800 stocks",
      "code_snippet": "universe = universe[\n    (universe.is_st == 0) &\n    (universe.listed_days >= 180) &\n    (universe.is_trading == 1)\n]"
    },
    {
      "id": 2,
      "title": "因子计算",
      "subtitle": "Factor Computation",
      "description": "每日截面计算4个核心因子原始值",
      "stat": "4 factors × ~3,800 stocks",
      "code_snippet": "scores = {\n    'momentum': enhanced_momentum(close),\n    'value':    bp_factor(pb),\n    'quality':  roe_factor(pe, pb),\n    'low_vol':  low_vol_20d(close)\n}"
    },
    {
      "id": 3,
      "title": "标准化",
      "subtitle": "Winsorize + Z-Score",
      "description": "截面 3σ 缩尾后 Z-score 标准化，消除极端值影响",
      "stat": "均值 0，标准差 1",
      "code_snippet": "def normalize(s):\n    mu, std = s.mean(), s.std()\n    s = s.clip(mu - 3*std, mu + 3*std)\n    return (s - s.mean()) / s.std()"
    },
    {
      "id": 4,
      "title": "行业中性化",
      "subtitle": "Industry Neutralization",
      "description": "按申万一级行业分组，组内重新标准化，消除行业暴露",
      "stat": "29 行业中性化",
      "code_snippet": "def industry_neutralize(scores, industry_map):\n    return scores.groupby(industry_map).transform(\n        lambda g: (g - g.mean()) / g.std()\n    )"
    },
    {
      "id": 5,
      "title": "IC 加权合成",
      "subtitle": "IC-Weighted Synthesis",
      "description": "基于滚动60日 ICIR 的 Softmax 权重动态合成复合因子",
      "stat": "权重每月自动更新",
      "code_snippet": "icir = rolling_icir(factor_scores, forward_returns, window=60)\nweights = softmax(np.abs(icir.values))\ncomposite = sum(w * f for w, f in zip(weights, factors))"
    },
    {
      "id": 6,
      "title": "选股",
      "subtitle": "Stock Selection",
      "description": "信号延迟1日（防前视偏差），取复合因子 TOP 30",
      "stat": "30 stocks / month",
      "code_snippet": "signals_lagged = composite.shift(1)  # no look-ahead\nselected = signals_lagged.nlargest(30).index"
    },
    {
      "id": 7,
      "title": "建仓与交易成本",
      "subtitle": "Portfolio Construction",
      "description": "等权建仓，月初再平衡，扣除双边 0.3% 手续费",
      "stat": "双边 0.3% / 月",
      "code_snippet": "weights = {s: 1/n_stocks for s in selected}\ntransaction_cost = turnover * 0.003 * 2\nnet_return = gross_return - transaction_cost"
    }
  ],
  "factor_weights_v7": {
    "momentum": 0.32,
    "value":    0.28,
    "quality":  0.25,
    "low_vol":  0.15
  }
}
```

### `public/data/journey/phases.json`
```json
{
  "phases": [
    {
      "id": 0,
      "title": "环境搭建",
      "subtitle": "Environment Setup",
      "period": "2026-01",
      "status": "complete",
      "deliverables": [
        "Python venv + pyproject.toml",
        "AkShare 数据接入（免费）",
        "5477 只 A股 CSV 本地存储",
        "数据质量检查脚本"
      ],
      "key_decision": "选择免费的 AkShare 而非付费数据源，降低研究门槛，聚焦方法论。",
      "metrics": null
    },
    {
      "id": 1,
      "title": "数学统计基础",
      "subtitle": "Quant Foundations",
      "period": "2026-01",
      "status": "complete",
      "deliverables": [
        "统计学基础 notebook (02_statistics_basics.ipynb)",
        "IC/ICIR 理论框架",
        "分层回测方法论"
      ],
      "key_decision": "以 IC > 0 且 |ICIR| > 0.3 且 |t-stat| > 2 作为因子入库门槛。",
      "metrics": null
    },
    {
      "id": 2,
      "title": "回测引擎",
      "subtitle": "Backtesting Framework",
      "period": "2026-02",
      "status": "complete",
      "deliverables": [
        "向量化回测引擎 (backtest/engine.py)",
        "MA Cross 第一个策略（验证框架）",
        "性能指标：Sharpe / Calmar / 最大回撤",
        "HTML 报告生成"
      ],
      "key_decision": "选择向量化回测而非事件驱动，A股月度再平衡下性能足够且实现简洁。",
      "metrics": { "first_strategy_sharpe": 0.71 }
    },
    {
      "id": 3,
      "title": "因子研究",
      "subtitle": "Core Factor Research",
      "period": "2026-03",
      "status": "complete",
      "deliverables": [
        "动量因子 (03_momentum_factor.ipynb)",
        "价值因子 (06_value_factor.ipynb)",
        "质量因子 (07_quality_factor.ipynb)",
        "低波动因子 (08_low_vol_factor.ipynb)",
        "因子验证框架 (09_factor_validation.ipynb)"
      ],
      "key_decision": "4个因子全部通过双重门槛（ICIR > 0.3 + t-stat > 2），全员入库。",
      "metrics": {
        "factors_researched": 4,
        "factors_admitted": 4,
        "avg_icir": 0.48,
        "avg_t_stat": 3.9
      }
    },
    {
      "id": 4,
      "title": "多因子策略",
      "subtitle": "Multi-Factor Strategy",
      "period": "2026-03",
      "status": "complete",
      "deliverables": [
        "IC 加权合成（Softmax + 滚动 ICIR）",
        "行业中性化 (10_industry_neutral.ipynb)",
        "策略 v7：30只/月度/行业中性",
        "v7 入场决策审查通过"
      ],
      "key_decision": "IC 加权显著优于等权（Sharpe +0.18），正式采用动态权重。",
      "metrics": {
        "sharpe": 1.23,
        "annual_return": 0.213,
        "max_drawdown": -0.183
      }
    },
    {
      "id": 5,
      "title": "Paper Trading 基础设施",
      "subtitle": "Live Execution Infrastructure",
      "period": "2026-04",
      "status": "complete",
      "deliverables": [
        "PaperTrader：虚拟组合追踪",
        "SQLite WAL ACID 账本 (ledger.db)",
        "生存者偏差修正 (listing_metadata.py)",
        "数据版本控制（SHA256 manifest）",
        "实盘 vs 回测漂移分析（-2.05% 成本差）"
      ],
      "key_decision": "使用 SQLite WAL 保证账本 ACID 属性，防止进程崩溃丢失交易记录。",
      "metrics": { "live_vs_backtest_drift": -0.0205 }
    },
    {
      "id": 6,
      "title": "控制平面",
      "subtitle": "Control Plane — CLI + Dashboard",
      "period": "2026-04",
      "status": "complete",
      "deliverables": [
        "统一 CLI (python -m quant_dojo)：17 个命令",
        "FastAPI Dashboard (port 8888)",
        "策略版本注册与切换",
        "日常运行流程自动化"
      ],
      "key_decision": "单一 CLI 入口封装所有操作，减少运维认知负担。",
      "metrics": { "cli_commands": 17 }
    },
    {
      "id": 7,
      "title": "AI 研究助手",
      "subtitle": "Agentic Research System",
      "period": "2026-04",
      "status": "complete",
      "deliverables": [
        "15 个 AI 研究 Agent 模块",
        "research_planner：研究方向自动规划",
        "factor_miner：新因子挖掘",
        "experiment_runner：自动回测运行",
        "risk_gate：实验审批门控",
        "多智能体辩论框架 (debate.py)"
      ],
      "key_decision": "保留人工审批门控（risk_gate），AI 提案，人工最终决策，防止自动化过拟合。",
      "metrics": { "agent_modules": 15 }
    }
  ]
}
```

---

## 五、关键组件实现细节

### FactorCard（因子卡片）

**视觉结构：**
- 左上：因子 slug（等宽字体，灰色）+ 中文名（主色）
- 右上：类别色 Badge
- 中：ICIR 圆环仪表（SVG，绿≥0.5 / 橙≥0.3 / 红<0.3）+ 数值统计
- 下：MiniSparkline（最近8个月 IC 走势，SVG折线）
- 底部：状态点（active/experimental）+ 半衰期天数
- hover：卡片上浮 4px + 蓝色光晕阴影 `0 12px 40px rgba(79,142,247,0.12)`
- click：整张卡片可点，跳转因子详情页

```tsx
// components/factor/FactorCard.tsx
import { motion } from 'framer-motion';
import Link from 'next/link';
import { GaugeRing } from '@/components/ui/GaugeRing';
import { MiniSparkline } from '@/components/ui/MiniSparkline';
import { Badge } from '@/components/ui/Badge';

export function FactorCard({ factor }: { factor: FactorSummary }) {
  return (
    <Link href={`/research/factor-library/${factor.category}/${factor.slug}`}>
      <motion.div
        whileHover={{ y: -4, boxShadow: '0 12px 40px rgba(79,142,247,0.12)' }}
        transition={{ type: 'spring', stiffness: 400, damping: 25 }}
        className="bg-[var(--bg-surface)] border border-[var(--border)]
                   rounded-xl p-4 cursor-pointer h-full"
      >
        {/* Header */}
        <div className="flex justify-between items-start mb-3">
          <div>
            <p className="text-[10px] text-[var(--text-tertiary)] font-mono uppercase tracking-wider">
              {factor.slug}
            </p>
            <h3 className="text-sm font-semibold text-[var(--text-primary)] mt-0.5">
              {factor.label}
            </h3>
          </div>
          <Badge category={factor.category} />
        </div>

        {/* ICIR + Stats */}
        <div className="flex items-center gap-3 mb-4">
          <GaugeRing value={factor.icir} max={1.0} size={48} />
          <div className="space-y-1 text-xs font-mono">
            <div className="flex gap-3">
              <span className="text-[var(--text-secondary)]">ICIR</span>
              <span className="text-[var(--blue)]">{factor.icir.toFixed(2)}</span>
            </div>
            <div className="flex gap-3">
              <span className="text-[var(--text-secondary)]">t</span>
              <span className="text-[var(--text-mono)]">{factor.t_stat.toFixed(1)}</span>
            </div>
            <div className="flex gap-3">
              <span className="text-[var(--text-secondary)]">IC+</span>
              <span className="text-[var(--text-mono)]">
                {(factor.ic_positive_pct * 100).toFixed(0)}%
              </span>
            </div>
          </div>
        </div>

        {/* Sparkline */}
        <MiniSparkline data={factor.sparkline} height={28} color="var(--blue)" />

        {/* Footer */}
        <div className="flex justify-between items-center mt-3 pt-3
                        border-t border-[var(--border-soft)]">
          <div className="flex items-center gap-1.5">
            <span className={`w-1.5 h-1.5 rounded-full ${
              factor.status === 'active' ? 'bg-[var(--green)]' : 'bg-[var(--gold)]'
            }`} />
            <span className="text-[10px] text-[var(--text-tertiary)]">
              {factor.status === 'active' ? '已入策略' : '实验中'}
            </span>
          </div>
          <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
            半衰期 {factor.half_life_days}d
          </span>
        </div>
      </motion.div>
    </Link>
  );
}
```

---

### GaugeRing（ICIR 圆环仪表）

```tsx
// components/ui/GaugeRing.tsx
'use client';
import { motion } from 'framer-motion';

interface Props { value: number; max?: number; size?: number; }

export function GaugeRing({ value, max = 1, size = 48 }: Props) {
  const pct = Math.min(Math.abs(value) / max, 1);
  const r = (size - 6) / 2;
  const circ = 2 * Math.PI * r;
  const color = value >= 0.5 ? '#00C896' : value >= 0.3 ? '#F5A623' : '#E84545';

  return (
    <svg width={size} height={size}>
      {/* Track */}
      <circle cx={size/2} cy={size/2} r={r}
        stroke="var(--border)" strokeWidth={3} fill="none" />
      {/* Progress — rotated to start from top */}
      <motion.circle cx={size/2} cy={size/2} r={r}
        stroke={color} strokeWidth={3} fill="none"
        strokeLinecap="round"
        strokeDasharray={circ}
        initial={{ strokeDashoffset: circ, rotate: -90 }}
        animate={{ strokeDashoffset: circ * (1 - pct) }}
        transition={{ duration: 1.2, ease: 'easeOut' }}
        style={{ transformOrigin: '50% 50%', transform: 'rotate(-90deg)' }}
      />
      {/* Center value */}
      <text x="50%" y="50%"
        dominantBaseline="middle" textAnchor="middle"
        fill={color} fontSize={size * 0.22}
        fontFamily="IBM Plex Mono, monospace">
        {value.toFixed(2)}
      </text>
    </svg>
  );
}
```

---

### ConstructionFlow（滚动驱动 7 步动画）

**交互设计：**
- 左侧：sticky 步骤导航，当前激活步骤有蓝色左边框高亮
- 右侧：每步内容区，滚动到视口中央时触发进入动画
- 每步包含：步骤编号 + 标题 + 描述 + 统计数字 + 代码片段（Shiki）
- Step 5（IC加权）额外显示雷达图（4个因子权重）

```tsx
// components/strategy/ConstructionFlow.tsx
'use client';
import { useState } from 'react';
import { motion } from 'framer-motion';

export function ConstructionFlow({ steps, factorWeights }: Props) {
  const [activeStep, setActiveStep] = useState(0);

  return (
    <div className="flex gap-12 relative">
      {/* Left sticky nav */}
      <div className="sticky top-24 h-fit w-52 shrink-0">
        {steps.map((step, i) => (
          <button key={i}
            onClick={() => document.getElementById(`step-${i}`)?.scrollIntoView({ behavior: 'smooth', block: 'center' })}
            className={`w-full text-left px-3 py-2.5 rounded-lg mb-1 text-sm transition-all duration-200 ${
              activeStep === i
                ? 'bg-[var(--blue)]/10 text-[var(--blue)] border-l-2 border-[var(--blue)] pl-2.5'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)] border-l-2 border-transparent'
            }`}
          >
            <span className="font-mono text-xs mr-2 opacity-60">
              {String(i + 1).padStart(2, '0')}
            </span>
            {step.title}
          </button>
        ))}
      </div>

      {/* Right scrollable content */}
      <div className="flex-1 space-y-32 pb-32">
        {steps.map((step, i) => (
          <motion.div key={i} id={`step-${i}`}
            initial={{ opacity: 0, x: 24 }}
            whileInView={{ opacity: 1, x: 0 }}
            onViewportEnter={() => setActiveStep(i)}
            viewport={{ margin: '-35% 0px -35% 0px', once: false }}
            transition={{ duration: 0.5, ease: 'easeOut' }}
            className="min-h-[50vh] flex flex-col justify-center"
          >
            <StepDetail step={step} index={i} factorWeights={i === 4 ? factorWeights : null} />
          </motion.div>
        ))}
      </div>
    </div>
  );
}
```

---

### EquityCurve（交互式净值曲线）

**交互设计：**
- 策略线（实线蓝色）vs CSI 300（虚线灰色）
- hover tooltip：显示日期 / 策略净值 / 基准净值 / 超额收益（绿色/红色）
- 可选：时间区间快捷按钮（1Y / 3Y / 5Y / All）
- 图表下方紧贴：回撤面积图（红色填充，对应上方净值曲线时间轴）

```tsx
// components/backtest/EquityCurve.tsx
'use client';
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer, ReferenceLine } from 'recharts';

const CustomTooltip = ({ active, payload, label }: any) => {
  if (!active || !payload?.length) return null;
  const strategy  = payload[0]?.value as number;
  const benchmark = payload[1]?.value as number;
  const alpha     = ((strategy - benchmark) / benchmark * 100);

  return (
    <div className="bg-[var(--bg-elevated)] border border-[var(--border)]
                    rounded-lg p-3 text-xs font-mono shadow-xl">
      <p className="text-[var(--text-secondary)] mb-2">{label}</p>
      <p className="text-[var(--blue)]">策略  {((strategy - 1) * 100).toFixed(2)}%</p>
      <p className="text-[var(--text-tertiary)]">
        CSI300 {((benchmark - 1) * 100).toFixed(2)}%
      </p>
      <p className={`mt-1.5 pt-1.5 border-t border-[var(--border-soft)] ${
        alpha >= 0 ? 'text-[var(--green)]' : 'text-[var(--red)]'
      }`}>
        Alpha {alpha >= 0 ? '+' : ''}{alpha.toFixed(2)}%
      </p>
    </div>
  );
};

export function EquityCurve({ data, metrics }: Props) {
  return (
    <div>
      <ResponsiveContainer width="100%" height={340}>
        <LineChart data={data} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: 'var(--text-tertiary)' }}
                 tickLine={false} axisLine={false} />
          <YAxis tickFormatter={v => `${((v-1)*100).toFixed(0)}%`}
                 tick={{ fontSize: 10, fill: 'var(--text-tertiary)' }}
                 tickLine={false} axisLine={false} />
          <Tooltip content={<CustomTooltip />} />
          <ReferenceLine y={1} stroke="var(--border)" strokeDasharray="4 4" />
          <Line dataKey="strategy"  stroke="var(--blue)"           strokeWidth={2} dot={false} />
          <Line dataKey="benchmark" stroke="var(--text-tertiary)" strokeWidth={1.5}
                dot={false} strokeDasharray="6 3" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
```

---

### MonthlyHeatmap（月度收益热力图）

**视觉设计：**
- 网格：年份（行）× 月份（列）
- 颜色编码：深绿（>+4%）→ 淡绿（0~+4%）→ 淡红（0~-4%）→ 深红（<-4%）
- 每格显示百分比数值
- hover：格子放大 + tooltip 显示精确数值

```tsx
// components/backtest/MonthlyHeatmap.tsx
const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];

function cellColor(v: number): string {
  if (v >  0.04) return '#00C896';
  if (v >  0.02) return '#00C89666';
  if (v >  0)    return '#00C89622';
  if (v > -0.02) return '#E8454522';
  if (v > -0.04) return '#E8454566';
  return '#E84545';
}

export function MonthlyHeatmap({ data }: { data: Record<string, Record<string, number>> }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono border-separate border-spacing-0.5">
        <thead>
          <tr>
            <th className="text-left text-[var(--text-tertiary)] font-normal w-14 pb-2">Year</th>
            {MONTHS.map(m => (
              <th key={m} className="text-[var(--text-tertiary)] font-normal pb-2 text-center min-w-[52px]">
                {m}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {Object.entries(data).sort(([a], [b]) => Number(b) - Number(a)).map(([year, months]) => (
            <tr key={year}>
              <td className="text-[var(--text-secondary)] py-1 pr-2">{year}</td>
              {MONTHS.map(m => {
                const v = months[m];
                if (v === undefined) return <td key={m} />;
                return (
                  <td key={m} className="py-0.5">
                    <div
                      title={`${m} ${year}: ${v > 0 ? '+' : ''}${(v*100).toFixed(2)}%`}
                      className="h-8 rounded flex items-center justify-center
                                 transition-transform hover:scale-110 cursor-default select-none"
                      style={{ backgroundColor: cellColor(v) }}
                    >
                      <span className="text-[var(--text-primary)] text-[10px] font-semibold">
                        {v > 0 ? '+' : ''}{(v*100).toFixed(1)}
                      </span>
                    </div>
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
```

---

### PhaseTimeline（开发历程时间线）

**视觉设计：**
- 竖向时间线，圆点节点
- 完成阶段：绿色实心圆点 + 正常亮度
- 未来阶段：灰色空心圆点 + 降低透明度
- 点击展开：Framer Motion AnimatePresence 展开交付物列表 + 关键决策 + 指标

```tsx
// components/journey/PhaseCard.tsx
'use client';
import { useState } from 'react';
import { motion, AnimatePresence } from 'framer-motion';

export function PhaseCard({ phase, isLast }: { phase: Phase; isLast: boolean }) {
  const [open, setOpen] = useState(false);
  const done = phase.status === 'complete';

  return (
    <div className="flex gap-4">
      {/* Timeline track */}
      <div className="flex flex-col items-center">
        <div className={`w-3 h-3 rounded-full mt-1 shrink-0 ${
          done ? 'bg-[var(--green)]' : 'bg-[var(--border)] border-2 border-[var(--text-tertiary)]'
        }`} />
        {!isLast && <div className="w-px flex-1 bg-[var(--border)] mt-1" />}
      </div>

      {/* Content */}
      <div className={`pb-10 flex-1 ${!done ? 'opacity-50' : ''}`}>
        <button onClick={() => setOpen(!open)} className="w-full text-left group">
          <div className="flex items-center justify-between">
            <div>
              <span className="text-[10px] text-[var(--text-tertiary)] font-mono">
                Phase {phase.id} · {phase.period}
              </span>
              <h3 className="text-base font-semibold text-[var(--text-primary)] mt-0.5">
                {phase.title}
              </h3>
              <p className="text-sm text-[var(--text-secondary)]">{phase.subtitle}</p>
            </div>
            <span className={`text-[var(--text-secondary)] transition-transform duration-200 ${
              open ? 'rotate-180' : ''
            }`}>▾</span>
          </div>
        </button>

        <AnimatePresence>
          {open && (
            <motion.div
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: 'auto', opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.25 }}
              className="overflow-hidden"
            >
              <div className="pt-4 space-y-4">
                {/* Deliverables */}
                <div>
                  <p className="text-xs text-[var(--text-secondary)] mb-2 uppercase tracking-wider">交付物</p>
                  <ul className="space-y-1">
                    {phase.deliverables.map((d, i) => (
                      <li key={i} className="flex items-center gap-2 text-sm text-[var(--text-primary)]">
                        <span className="text-[var(--green)] text-xs">✓</span> {d}
                      </li>
                    ))}
                  </ul>
                </div>

                {/* Key decision */}
                <div className="bg-[var(--bg-elevated)] border border-[var(--border)]
                                rounded-lg p-3">
                  <p className="text-xs text-[var(--gold)] mb-1 font-mono">关键决策</p>
                  <p className="text-sm text-[var(--text-primary)]">{phase.key_decision}</p>
                </div>

                {/* Metrics */}
                {phase.metrics && (
                  <div className="flex gap-4 flex-wrap">
                    {Object.entries(phase.metrics).map(([k, v]) => (
                      <div key={k} className="text-center">
                        <p className="text-lg font-mono font-semibold text-[var(--blue)]">
                          {typeof v === 'number' && v < 1 ? (v * 100).toFixed(1) + '%' : v}
                        </p>
                        <p className="text-[10px] text-[var(--text-tertiary)]">{k}</p>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </motion.div>
          )}
        </AnimatePresence>
      </div>
    </div>
  );
}
```

---

## 六、Python 数据导出脚本

```python
#!/usr/bin/env python3
# portfolio/scripts/export_data.py
# 运行方式：cd /path/to/quant-dojo && python portfolio/scripts/export_data.py

import json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

OUT = os.path.join(os.path.dirname(__file__), "../public/data")
os.makedirs(f"{OUT}/factors", exist_ok=True)
os.makedirs(f"{OUT}/backtest", exist_ok=True)
os.makedirs(f"{OUT}/strategy", exist_ok=True)
os.makedirs(f"{OUT}/live", exist_ok=True)
os.makedirs(f"{OUT}/journey", exist_ok=True)

def write(path, data):
    with open(os.path.join(OUT, path), "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"✓ {path}")


def export_factors():
    """
    从以下来源读取因子数据：
    - utils/alpha_factors.py         → 因子函数定义（用 inspect 提取代码）
    - journal/full_factor_analysis_*.md  → IC/ICIR/t-stat 数据
    - journal/factor_library_report_*.md → 因子描述
    """
    from utils import alpha_factors
    import inspect

    # 读取 IC 数据（从 journal 中解析，或从 live/factor_snapshot/ 读取）
    # TODO: 对接 pipeline/factor_monitor.py 的输出
    factors_index = []
    # ... 构建每个因子的 summary 数据
    write("factors/index.json", {"factors": factors_index, "categories": CATEGORIES})


def export_backtest():
    """
    从 live/runs/ 读取最新 v7 回测结果
    对接 backtest/report.py 的 JSON 输出
    """
    import glob
    run_files = sorted(glob.glob("live/runs/v7_*.json"))
    if run_files:
        with open(run_files[-1]) as f:
            run_data = json.load(f)
        # 转换为 equity_curve.json 格式
        write("backtest/equity_curve.json", run_data)


def export_live():
    """从 live/portfolio/ 读取实盘状态"""
    import json
    if os.path.exists("live/portfolio/positions.json"):
        with open("live/portfolio/positions.json") as f:
            positions = json.load(f)
        write("live/portfolio.json", positions)

    if os.path.exists("live/portfolio/nav.csv"):
        import csv
        with open("live/portfolio/nav.csv") as f:
            rows = list(csv.DictReader(f))
        write("live/nav_history.json", {"series": rows})


def export_strategy():
    """从 pipeline/active_strategy.py 和 strategies/multi_factor.py 读取"""
    # 构建 construction.json（步骤数据，含代码片段）
    # 构建 versions.json（v7-v16 历史）
    pass


if __name__ == "__main__":
    print("Exporting quant-dojo data to portfolio/public/data/...\n")
    export_factors()
    export_backtest()
    export_live()
    export_strategy()
    # journey/phases.json 为手动维护，已写入 PORTFOLIO_PLAN.md Schema 中
    print("\n✓ All exports complete.")
```

---

## 七、实现阶段计划

### Phase A — 骨架搭建（约 1 session）
1. `cd quant-dojo && npx create-next-app@latest portfolio --typescript --tailwind --app`
2. 配置 `globals.css` 写入设计 token（见第一节）
3. 实现 `Navbar.tsx` + `Breadcrumb.tsx` + `layout.tsx`
4. 实现 `lib/data.ts`（fetch JSON 辅助）和 `lib/formatters.ts`
5. 创建 `public/data/` 目录，手动写几条 mock JSON 用于开发
6. 验证路由：`/research`、`/strategy`、`/validation` 页面可访问

### Phase B — 因子库（约 1-2 sessions，视觉核心）
1. 实现 `GaugeRing.tsx`、`MiniSparkline.tsx`、`Badge.tsx`
2. 实现 `FactorCard.tsx`（先用 mock 数据）
3. 实现 `FactorFilter.tsx`（类别 + 状态 + 搜索）
4. 实现 `/research/factor-library/page.tsx`（卡片墙 + 筛选）
5. 实现 `FormulaDisplay.tsx`（KaTeX）、`QuintileChart.tsx`、`ICTrendChart.tsx`、`DecayChart.tsx`
6. 实现 `/research/factor-library/[category]/[factor]/page.tsx`（单因子详情）
7. 实现 `/research/core-factors/[slug]/page.tsx`（4个核心因子，结构同上 + 更丰富）

### Phase C — 策略与验证（约 1 session）
1. 实现 `ConstructionFlow.tsx`（滚动7步 + sticky导航）
2. 实现 `WeightRadar.tsx`（Recharts RadarChart）
3. 实现 `/strategy/framework/page.tsx`
4. 实现 `EquityCurve.tsx`、`DrawdownChart.tsx`、`MonthlyHeatmap.tsx`、`MetricGrid.tsx`
5. 实现 `/validation/results/page.tsx`（图表中心页）
6. 实现 `/validation/walk-forward/page.tsx`
7. 实现 `/validation/stress-tests/page.tsx`

### Phase D — 主页与历程（约 0.5 session）
1. 实现 `MetricCounter.tsx`（Framer Motion 数字计数动画）
2. 实现 `SystemFlowDiagram.tsx`（可点击流程图）
3. 实现 `Hero.tsx` + `/page.tsx`（主页）
4. 实现 `PhaseTimeline.tsx` + `PhaseCard.tsx`
5. 实现 `/journey/page.tsx`

### Phase E — 数据接入（约 0.5 session）
1. 完善 `portfolio/scripts/export_data.py`
2. 对接 `utils/alpha_factors.py` 提取因子代码
3. 对接 `live/runs/` 提取回测结果
4. 对接 `live/portfolio/` 提取实盘数据
5. 运行导出，替换所有 mock 数据为真实数据

### Phase F — 收尾与补全
1. 补全 60+ 因子的详情 JSON 文件
2. 实现 `/infrastructure/ai-agents/page.tsx`（15个 Agent 卡片）
3. 实现 `/strategy/versions/[version]/page.tsx`（各版本对比）
4. 实现 `/live/page.tsx`（实盘模拟面板）
5. 性能优化（`next/image`、图表懒加载）
6. `npm run build` 验证无错误

---

## 八、package.json 依赖

```json
{
  "dependencies": {
    "next": "^14.2.0",
    "react": "^18.3.0",
    "react-dom": "^18.3.0",
    "framer-motion": "^11.0.0",
    "recharts": "^2.12.0",
    "react-katex": "^3.0.1",
    "katex": "^0.16.0",
    "shiki": "^1.0.0",
    "clsx": "^2.1.0",
    "tailwind-merge": "^2.3.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "@types/react": "^18.3.0",
    "@types/node": "^20.12.0",
    "tailwindcss": "^3.4.0",
    "autoprefixer": "^10.4.0",
    "postcss": "^8.4.0"
  }
}
```

---

*文档版本：2026-04-16*
*基于 quant-dojo Phase 7 完成后的内容清单生成*
