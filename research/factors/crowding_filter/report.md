# 拥挤度复合因子研究报告 v2 (修复版)

**日期**：2026-04-21 修订  **窗口**：2022-01-01~2025-12-31  **前瞻**：20 日

## 修复摘要

- F3 survey_attention 增加预热期 (2021-08 ~ 2022-01)，att_60d 在 IS 起点已有效
- F6 institutional_holdings 改用 ann_date 生效对齐（原 end_date+60d 过滞后），inst_ratio ICIR 0.04 → 0.30
- nb/inst 不再 `fillna(0)`：缺失值保留 NaN，仅在各自 universe 内 z-score；composite 用可用维度均值
- 新增 size-neutralize 变体：`-composite` 对 `log(circ_mv)` 回归取残差，验证真实 alpha

## A. -composite_crowding（原始）

- IC +0.0774  ICIR +0.685  HAC t +6.04  IC>0 78.7%
- 多空年化 +13.02%  夏普 1.05

## A2. -composite_crowding (size-neutralized)

- IC +0.0888  ICIR +0.827  HAC t +7.13  IC>0 80.5%
- 多空年化 +17.58%  夏普 1.56

## B. 单维度拆解（-z）

| 维度 | IC | ICIR | HAC t |
| --- | ---: | ---: | ---: |
| -att | +0.0098 | +0.285 | +2.43 |
| -turn | +0.0909 | +0.496 | +4.36 |
| -nb | +0.0185 | +0.129 | +0.91 |
| -inst | +0.0061 | +0.150 | +1.35 |

## C. 分层年化（原始）

|    |    ann |
|:---|-------:|
| Q1 | 0.0254 |
| Q2 | 0.124  |
| Q3 | 0.1261 |
| Q4 | 0.1669 |
| Q5 | 0.1652 |

## C2. 分层年化（size-neutral）

|    |    ann |
|:---|-------:|
| Q1 | 0.017  |
| Q2 | 0.1183 |
| Q3 | 0.1387 |
| Q4 | 0.1641 |
| Q5 | 0.1928 |

## 结论

- ✅ size-neutral 版本 ICIR 0.827 / HAC t 7.13 仍通过双门槛
- 去掉 size 后 IC 衰减 -15%，但仍显著 → 拥挤度是真 alpha，不是单纯 size/reversal 伪装
