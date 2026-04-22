# MD&A drift Tier 1b — IC 评估结果 (2026-04-22)

战略锚: `research/space_c_llm_alpha/alpha_theory_space_c_research_20260421.md`
Pre-reg: `scripts/mda_drift_tier1_eval.py` + Issue #28

## Panel 统计

- 观测数 (symbol × publish_date): **2958**
- 覆盖 fiscal_year: 2019..2025
- 覆盖 symbol: 500
- drift 分布: mean=0.562, std=0.111, q25=0.491, q75=0.638
- forward_20d_return 分布: mean=0.0223, std=0.1403

## IC 总表 (Spearman rank, 月度 cross-section)

| 区间 | N 月 | IC 均值 | IC std | ICIR | NW t | IC>0 占比 |
|---|---:|---:|---:|---:|---:|---:|
| 全样本 (2019-2026 发布) | 12 | 0.0036 | 0.0783 | 0.045 | 0.15 | 41.7% |
| pre-2023 (2019-2022 发布) | 6 | -0.0004 | 0.0765 | -0.005 | -0.01 | 33.3% |
| post-2023 (2023-2026 发布) | 6 | 0.0075 | 0.0872 | 0.086 | 0.22 | 50.0% |

Regime shift (pre vs post 2023): -1757.7% (post vs pre, 衰减 > 50% → regime shift)

## Decile spread (10 分位, top - bottom forward return)

- N=2958, top 10%=0.0358, bot 10%=0.0203
- spread = **0.0155** (正值 → 高 drift 跑赢, 与 Lazy Prices 预测相反)

## 决策

🔴 **KILL**. |IC|=0.0036 < 0.015. 空间 C MD&A 方向封死, 转 Tier 3 跨文档.

## 备注

- 本次 IC 计算只看 Spearman, 未做行业中性化. 如 |IC| ∈ [0.01, 0.025] 再加 sector-neutral 版本重测.
- 成本假设: 单边 15.0 bp, 双边 30 bp.
- forward window: 20 交易日; publish → as_of 用 T+1.