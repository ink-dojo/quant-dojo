# DSR #31 Pre-registration — 3-way ensemble w/ insider purchase

**创建**: 2026-04-18
**前提**: DSR #30 BB-only 主板 rescaled 达到 4/5 PASS, 仅 CI_low 0.20 fail.
第 3 个 uncorrelated alpha 如果有效, 通过诊断降低 Sharpe CI 宽度 应能过门.

## 动机

BB-only 2018-2025 Sharpe 0.84 的 bootstrap CI [0.20, 1.48] 太宽 ≈ 单 alpha
年度方差 (2018=-6%, 2019=+35%, 2024=+39%, 2025=+27%) 导致. 3 个 uncorrelated
alpha 的 ensemble 应把 Sharpe CI 宽度减至 ~1/√3 = 58%, 若 mean Sharpe 保持
~0.84, 新 CI_low 约 0.84 - (1.48-0.84)/√3 ≈ 0.47 — 接近 gate 阈值.

若 insider purchase alpha 独立 Sharpe 显著 > 0, 且与 bb/pv correlation < 0.4,
ensemble CI_low 有机会 > 0.5.

## Pre-registration spec (零 DoF, 执行前 git commit 锁)

### 数据与 alpha 列表
1. **BB 主板 rescaled**: `research/event_driven/dsr30_mainboard_bb_oos.parquet`
   - 已有 DSR #30 产物, 不重算
2. **PV 主板 rescaled**: `research/event_driven/dsr30_mainboard_pv_oos.parquet`
   - 已有 DSR #30 产物, 不重算
3. **Insider (NEW)**: `research/event_driven/insider_purchase_strategy.py` 主板过滤 +
   相同 UNIT rescale formula pattern 到 mean_gross ~0.8

### Insider alpha spec (固定在本文件前)
- events: stock_ggcg_em 2018-2025
- 方向: 持股变动信息-增减 == '增持' only
- 信号: 持股变动信息-占总股本比例 (%), filter (0.1, 20)
- 宇宙: 主板 (60x/00x) only, 与 #29/#30 一致
- 选股: monthly cross-section top 30% signal
- 窗口: T+1 ~ T+20 (与 bb/pv 一致)
- base UNIT: 1/30 (ex-ante, 如果 main-board 后 ~50 concurrent → gross ~0.67)
- UNIT rescale: 如果实测 mean_gross ≠ 0.8 ± 0.2, 按 formula scale = 0.8/measured
- gross cap: 1.0
- cost: round-trip 0.3%

### Ensemble spec
- 权重: 1/3 / 1/3 / 1/3 (equal, no optimization)
- 不 re-normalize ensemble 到 vol target (Phase 4 #25 已证无效)

### 诊断指标 (报告, 不用于选择)
- pairwise correlation: bb-pv, bb-insider, pv-insider
- 各 alpha 年度 Sharpe
- ensemble 年度 + rolling 126d Sharpe

### Gate (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线
- 5/5 PASS → paper-trade candidate #2 (DSR #31 3-way ensemble 主板 rescaled)
- 4/5 PASS (仍 miss CI_low) → 承认 A 股 event-driven 日频 8 年 sample
  无法到 CI_low 0.5, 接受 paper-trade 门槛 modification (option A)
- ≤ 3/5 PASS → insider alpha 拖 ensemble, 不 promote, 写 terminal

## DSR 计数
- 起点: n=30 (Phase 3.5)
- DSR #31 = 1 新 trial (insider alpha + 3-way ensemble 算 1 个 hypothesis)

## 执行顺序
1. 数据 backfill 完成 → sanity check (rows/date range/direction 分布)
2. 跑 insider_purchase_strategy.py full universe → 看是否有 signal
3. 加 主板 filter + UNIT rescale → 跑 DSR #31 main script
4. 落 parquet + journal + terminal 判定

**Pre-registration lock time**: 2026-04-18
