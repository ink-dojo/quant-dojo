# qlib Alpha158 baseline vs DSR #30 对照（2026-04-29）

> 关联 Issue #48；输入: `research/qlib_baseline/runs/20260429_223928/`
> 决策对象: jialong, xingyu

## 一句话结论

**DSR #30 BB 主板 rescaled 在外部 ML baseline 对照下显著有 edge** —— net Sharpe 1.03 vs qlib Alpha158-LightGBM 的 0.42（~2.5x），年化超额 6.26% vs 3.08%（~2x）。但 ensemble 版（BB+PV 50/50 RIAD 等）反而被 PV 腿拖累到 excess 1.21%，与 jialong 2026-04-28 否决 spec v4 RIAD+DSR#30 50/50 的判断一致。

## 数据范围（重要 caveat）

| 项 | 值 |
|---|---|
| 重叠期 | 2018-01-02 ~ 2020-09-25 (~667 交易日, 2.5y) |
| 受限于 | qlib v3 PIT universe end 2020-09-25 |
| CLAUDE.md 红线 | "回测时间跨度 > 3 年" → **本次 < 3y 不达标** |

⚠️ 这意味着对照表只能作**参考性外部基线**，不能单独 go/no-go DSR #30 paper-trade —— 真正决策仍要看 DSR 完整 2018-2026 区间。

## 对照表（全部对齐 CSI300 benchmark + 单边 0.15% 成本）

| 候选 | n_days | 年化 net | 年化 excess | net Sharpe | excess Sharpe | MaxDD | 胜率 | 累计 net |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| qlib Alpha158-LightGBM | 667 | 7.74% | 3.08% | 0.42 | 0.35 | -28.6% | 51.9% | +21.8% |
| CSI300 benchmark | 667 | 4.86% | — | 0.33 | — | -32.5% | 51.4% | +13.4% |
| **DSR #30 BB 主板 rescaled** | **667** | **14.62%** | **6.26%** | **1.03** | **0.44** | **-17.5%** | **42.9%** | **+43.5%** |
| DSR #30 ensemble (BB+PV+recal) | 667 | 8.63% | 1.21% | 0.63 | 0.16 | -18.3% | 50.2% | +24.5% |

## 关键判断

### 1. DSR #30 BB 主板 rescaled 真有 edge
- net Sharpe **1.03 通过 CLAUDE.md 门槛 > 0.8**
- 年化 14.62% **接近**（但略低于）门槛 15%
- MaxDD -17.5% **远低于**门槛 30%
- 胜率 42.9% < 50% — 但事件驱动 + 反转策略正常（盈亏比 > 1 即可，本策略累计 net 43.5% 证明盈亏比足够）

### 2. ensemble 比 BB 单脚显著差 → 印证 spec v4 否决
- BB 单脚 excess 6.26% / Sharpe 0.44
- ensemble excess 1.21% / Sharpe 0.16
- 差距 ~5pct/年化，**说明 PV 腿和 recal 三足拖累 BB 单脚**
- 这与 jialong 2026-04-28 否决 spec v4 RIAD + DSR#30 50/50 双腿的逻辑一致：50/50 摊薄了 BB 的 edge

### 3. qlib baseline 在 CLAUDE.md 成本下挣扎
- without cost: 年化超额 10.67% / IR 1.16
- with cost (单边 0.15%): 年化超额 3.08% / IR 0.35 / Sharpe 0.42
- **成本一刀砍掉 ~7pct 超额** —— A 股 cross-sectional ML 对换手敏感的本质在这里
- 这跟 `feedback_ashare_alpha_nuance` 的判断一致：A 股 cross-sectional factor premium 薄

## 给 jialong 的建议

1. **DSR #30 BB 主板 rescaled 单脚值得进 paper-trade 评估** —— 但只在
   - 完整 2018-2026 区间复跑结果（这次重叠期 2.5y 不够）
   - DSR #30 #30 4/5 候选评审里那个 CI_low 0.20 fail 项有缓解（jialong 2026-04-18 选项 A/B/C 待定）
   - 同时确认 capacity / live-vs-backtest tracking 框架没问题
2. **不再考虑 ensemble / 50-50 双腿** —— 数据明确显示 PV 腿稀释 BB 单脚
3. 这次外部 baseline 对照**不能单独触发 go-live 决策**，但提供了一个有用的「外部独立证据」侧面：BB 主板单脚的 alpha 不是 ML 标准 pipeline 能轻易复制的

## 局限与下一步

- 2.5y 重叠期 < 3y 评审门槛
- qlib v3 universe 2020-09-25 截止 —— 错过了 2021-2022 风格切换 + 2023-2024 中特估行情
- 想扩到 2024 需要 akshare 补 OHLCV 全量，约 1 周工作量，**作为未来 issue**（不在 #48 范围）

## artifacts

- baseline run: `research/qlib_baseline/runs/20260429_223928/`
  - `meta.json` — qlib 0.9.7, lightgbm 4.6.0, seed=2026, deterministic=True
  - `test_report.parquet` — 911 日 portfolio metric
  - `test_signals.parquet` — 273300 行预测分
  - `test_risk_analysis.csv` — qlib 标准 risk metrics
  - `compare_dsr30.json` — 本对照表的 JSON 版
- DSR #30 OOS 来源（已有，未改动）：
  - `research/event_driven/dsr30_mainboard_bb_oos.parquet`
  - `research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet`
- 对照脚本: `research/qlib_baseline/compare_dsr30.py`
