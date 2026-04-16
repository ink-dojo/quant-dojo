# Portfolio 站点数据覆盖度审计 — 2026-04-16

> **作者**：jialong
> **关联 Issue**：[#18](https://github.com/ink-dojo/quant-dojo/issues/18)
> **关联脚本**：`scripts/audit_factor_data_coverage.py`
> **结构化结果**：`journal/portfolio_factor_coverage.json`

---

## 为什么要做这次审计

`PORTFOLIO_PLAN.md` 第四节给出的静态 JSON schema 假设每个因子都有完整的 IC 均值、ICIR、t-stat、衰减曲线、分层收益 5 组数据。但 quant-dojo 实际研究节奏下，这些数据散落在三处：

1. `utils/alpha_factors.py` — 因子函数定义（有代码）
2. `research/factors/{slug}/README.md` — 少数因子有完整研究说明
3. `journal/full_factor_analysis_20260325.md` — 2026-03 跑过一次全因子 IC 统计（12 因子）

脚本开工前，必须先把这个三层差距量化，否则 Phase A 的 `export_data.py` 会遇到 30% 空数据而返工。

---

## 核心数字

| 指标 | 数量 | 占比 |
|------|------|------|
| `alpha_factors.py` 里的因子函数 | 66 | 100% |
| 有 **IC 统计**（journal 里有数字） | 9 | 13.6% |
| 有 **research/factors 专属文件夹** | 9 | 13.6% |
| 在 **v7/v9/v10 核心 5 因子** | 5 | 7.6% |
| 在 **v16 生产 9 因子** | 9 | 13.6% |
| 在 **最新 factor_snapshot** parquet | 5 | 7.6% |

**结论**：全库 66 个因子，只有 ~10 个拥有"portfolio 面试级别"的完整证据链。其余 56 个只能展示代码 + docstring + 类别标签。

---

## 按类别分布

| 类别 | 数量 | 代表因子 |
|------|------|---------|
| technical（技术） | 11 | enhanced_momentum, low_vol_20d, high_52w_ratio, momentum_6m_skip1m |
| fundamental（基本面） | 7 | bp_factor, ep_factor, roe_factor, accruals_quality |
| microstructure（微观结构） | 6 | shadow_lower, shadow_upper, amplitude_hidden, price_volume_divergence |
| behavioral（行为金融） | 4 | team_coin, cgo, str_salience, relative_turnover |
| chip（筹码） | 2 | chip_arc, chip_vrc |
| liquidity（流动性） | 2 | amihud_illiquidity, bid_ask_spread_proxy |
| extended（扩展研究） | 34 | beta_factor, sharpe_20d, bollinger_pct, rsi_factor …（因子挖掘会话产物） |

`extended` 类是 Phase 7 因子挖掘阶段批量生成的实验性因子，大多没跑过严肃的 IC 验证。在 portfolio 网站上应该归到 "Extended Research" 子类，只展示名字+公式+docstring，不做深度页。

---

## 覆盖度 Top 10（英雄因子候选池）

| 排名 | 因子 | 类别 | score | 关键证据 |
|------|------|------|-------|---------|
| 1 | `low_vol_20d` | technical | 5/6 | research + IC=0.34 + v7 + v16 + snapshot |
| 2 | `team_coin` | behavioral | 4/6 | IC=0.45 (最高) + v7 + v16 + snapshot |
| 3 | `bp_factor` | fundamental | 3/6 | research + IC=0.28 + v7 |
| 4 | `enhanced_momentum` | technical | 3/6 | research + IC=0.27 + v7 |
| 5 | `ep_factor` | fundamental | 3/6 | research + notebook + IC=0.22 |
| 6 | `amihud_illiquidity` | liquidity | 2/6 | v16 + snapshot |
| 7 | `cgo` | behavioral | 2/6 | IC=0.33 + v7 |
| 8 | `momentum_6m_skip1m` | technical | 2/6 | research + v16 |
| 9 | `price_volume_divergence` | microstructure | 2/6 | v16 + snapshot |
| 10 | `shadow_lower` | microstructure | 2/6 | v16 + snapshot |

剩余 56 因子覆盖度 ≤1，包括很多 `extended` 类只有 compute 函数。

---

## 数据缺口清单（Phase B 必须补的数据）

为了给英雄 8 因子做深度详情页，以下数据目前**没有现成文件**，需要在 Phase B 之前重跑：

| 数据项 | 现状 | Phase B 如何解决 |
|--------|------|----------------|
| IC 时间序列（月度） | 只有 `full_factor_analysis_20260325.md` 的汇总均值 | 用 `utils/factor_analysis.compute_ic_series()` 跑 8 因子 × 月度序列 → 写 JSON |
| 分层回测（Q1-Q5）年化/夏普 | `full_factor_analysis` 只有 ICIR，没有 quintile | 用 `utils/factor_analysis.quintile_backtest()` 跑 8 因子 → 写 JSON |
| 因子衰减曲线（lag 1/5/10/21/42/63） | 无 | 用 `utils/factor_analysis.factor_decay_analysis()` 跑 8 因子 → 写 JSON |
| LaTeX 公式 + 经济学直觉 | docstring 部分有，格式不统一 | 手工在 `portfolio/data/factors/[slug].json` 写 formula/intuition（~8 条，可接受） |
| 因子间相关性矩阵 | `full_factor_analysis_20260325.md` 有少量 pairs，但不完整 | 跑 66×66 Spearman 矩阵一次，导出 |

**估算**：Phase B 之前要新增一个"因子深度分析重跑脚本"（`scripts/deep_analysis_hero_factors.py`），一次跑完 8 因子的 IC 时序 + 分层 + 衰减，输出到 `journal/hero_factor_stats_YYYYMMDD.json`。约 0.5 session。

---

## 对前端展示的影响（传递给 Phase A/B）

| 站点区域 | 可用数据 | 设计调整建议 |
|---------|---------|-------------|
| `/research/core-factors/[slug]` × 4 | 动量/价值/质量/低波 — 全部有 research 文件夹 + IC | 正常做深度页 |
| `/research/factor-library/[category]/[factor]` × 62 | 只有 ~8 个有 IC 数据 | 卡片墙能显示全部 66 因子；点进去非英雄因子只显示"公式 + docstring + 类别标签 + 在哪些策略里出现过"，不强塞空的 ICIR 圆环 |
| `/strategy/versions/[version]` | v7/v9/v16 的 run JSON 都有 metrics+equity_curve | 三个版本都能做详情页；v10 等回测完成再加 |
| `/validation/results` | v16 最新 run 最完整 | 用 v16 做门面（或 v9 + v16 做对比） |

---

## 下一步

1. **portfolio_hero_factors.md** — 定死 8 英雄因子名单
2. **portfolio_face_strategy.md** — 定死门面策略（v9 or v16）
3. **Phase B 前置**：新建 `scripts/deep_analysis_hero_factors.py` 补数据

---

## 审计脚本可重跑性

`scripts/audit_factor_data_coverage.py` 是幂等的：
- 未来新增因子（在 `alpha_factors.py` 加函数）→ 重跑自动纳入
- 未来新增策略版本（如 v10 通过）→ 改脚本顶部的 `V7_CORE_FACTORS` / `V16_FACTORS` 常量
- 未来新增 IC 统计 journal → 扩展 `parse_ic_stats_table()` 函数

这个脚本是 portfolio 维护的一部分，不是一次性产物。
