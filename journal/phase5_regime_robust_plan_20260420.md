# Phase 5 研究计划 — Regime-Robust Cross-Sectional Alpha
_2026-04-20 预注册草案_

## 问题定义

v16 被证伪（A 股日频 cross-sectional factor premium 被套利）→ event-driven 方向找到 5/5 paper-trade ensemble。但 ensemble **2024 alpha 单调衰减到 -7%**，说明 event-driven 也在退化。

**问题**: 是否存在第三条路 —— 非事件驱动、非 v16 因子族、但确实 regime-robust 的 cross-sectional alpha？

2026-04-19 regime-robust 扫描给出**初步证据**：2022-2025 OOS，16 个因子同时在熊市 IC>0 且 t>1.5 且 bear/bull ratio>0.2。这些因子是否能在 2018-2025 全样本上过标准 gate 门？

## Phase 5 假设（零 DoF）

**H0**：任何 regime-robust 候选因子在 2018-2025 全样本上都**不能**过 5/5 gate（暗示仍是短样本 overfit）

**H1 (测试)**：从 16 候选中选出 **3 个机制正交** 的因子，各自独立 pre-register → 其中至少 1 个 4/5 PASS

## 3 个候选因子（mechanism-orthogonal）

| 因子 | IC_bear | t_bear | ratio | 机制类别 | 学术锚 |
|---|---|---|---|---|---|
| **cgo** | 0.1024 | 15.0 | 1.23 | Prospect theory / 浮盈浮亏 | Grinblatt-Han 2005 |
| **str_salience** | 0.0966 | 18.1 | 1.09 | Salience theory 短期 reversal | Bordalo-Gennaioli-Shleifer 2013 |
| **reversal_skip1m** | 0.0782 | 12.2 | **1.94** | 传统 6m-skip-1m momentum 负号 (reversal) | Jegadeesh-Titman 1993 |

为何这 3 个（非 top-3-by-bear_IC）：
- **cgo** 捕捉 behavioral finance (disposition effect)，机制与 reversal 截然不同
- **str_salience** 是 salience-weighted，机制与 cgo/reversal 又不同（注意力驱动）
- **reversal_skip1m** ratio **1.94**（熊市 IC 接近牛市 2×），最强 regime-neutral 证据

Skip reasons：
- reversal_1m / w_reversal：与 reversal_skip1m 高相关
- low_vol_20d：ratio 0.71 熊差牛好，不是 regime-robust
- high_52w：ratio 4.22 异常大（低牛市 IC 分母），可能 spurious
- enhanced_mom / quality_mom：ratio < 0.7 熊市弱

## DSR Trial 编号预留

Phase 5 首批：**DSR #35 / #36 / #37**（cross-sectional factor 族，非 event-driven）

| Trial | 因子 | 文件 | Strategy |
|---|---|---|---|
| #35 | cgo | `research/factors/cgo_standalone.py` | Monthly rebal, top/bottom 30% long-short |
| #36 | str_salience | `research/factors/str_salience_standalone.py` | 同上 |
| #37 | reversal_skip1m | `research/factors/reversal_skip1m_standalone.py` | 同上 |

通用设计（预注册锁定）：
- 样本: 2018-2025（与 ensemble 保持一致，可比）
- 股票池: 5477 股全池（不做板块过滤）
- 频率: **月末**截面（不是日频，为降低换手）
- 方向: 按因子自然方向 long top 30% / short bottom 30%（市场中性）或仅做 long top 30%（A 股禁空现实）
- UNIT: 0.05 每持仓（20 只分散）
- 成本: 单边 15 bps（与 ensemble spec 一致）
- Gross cap: 1.0

**Admission gates**：标准 5 门（ann>15%, SR>0.8, MDD>-30%, PSR>0.95, CI_low>0.5）

## 必要前置（数据）

1. **`data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet`** —— regime_robust_factor_scan.py 依赖，当前本地缺失。Task #92 负责重建
2. **`data/processed/volume_wide_2014-01-01_2025-12-31_5477stocks.parquet`** —— 成交量宽表（如 scan 逻辑需要）
3. **市值/流通市值** —— 因子标准化时的 size-neutral 权重（tushare daily_basic 模块下载完提供）

## DSR n_trials 追加协议

当前 DSR 总计数: 34 (截至 #34)。Phase 5 加 3 个 → 39。

DSR 校正（跨 Phase 3/4/5 的全 portfolio 门）：
- 原 34 trials 时，标准门 α=0.05 → 单样本 α=0.05/34 ≈ **0.00147**
- 加 3 trials 后 α=0.05/37 ≈ **0.00135**
- PSR 和 CI_low 评估在新 α 下是否仍过门

触发点: 若 #35/#36/#37 任何一个 4/5 或 5/5 过门, **必须** 跑一遍新 DSR 修正，确认 ensemble 5/5 verdict 不被削弱。

## Paper-Trade 影响

**零影响**：Phase 5 是研究轨，paper-trade ensemble 独立运行。仅当 Phase 5 出 5/5 PASS 且正交分析 (ρ < 0.3 with ensemble) 通过后才讨论加入实盘。

## 优先级与时间

- Week 1 (本周)：重建 price_wide_close (Task #92) + tushare 下载完成
- Week 2：跑 3 个 standalone DSR trials (#35 #36 #37)
- Week 3：结果评估 + DSR 修正 + 正交分析
- Week 4：若有 PASS，进入 WF + stress + trade-level 验证（mirror Phase 4.1 协议）

## 红线

- **不允许** 在看到结果后"调整" top 30% 阈值 / hold 窗口 / UNIT 权重 —— 本文件锁定
- **不允许** 用 2022-2025 的 IC 结果调因子选择（已经 pre-registered 在上方）
- **不允许** 将 Phase 5 因子加入 paper-trade ensemble，直到跑完全套 5/5 gate + WF

---

— 预注册日期：**2026-04-20**
— 策略 owner: jialong
