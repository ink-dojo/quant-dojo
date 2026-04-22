# BGFD — Broker Gold-stock Fade Divergence

**状态**: 2026-04-22 原假设 (crowded → fade) **被推翻**, 反向 (follow consensus) 2024-2025 有强 alpha, 2020-2023 无效.
**Issue**: #33

## 原假设 (被证伪)

券商月度金股共识度高的股票 = 研究拥挤 = late retail follower 接盘 → 后续 fade.
**预期**: 做空 top-crowded, 做多 fresh/single-broker pick = 正 alpha.

## 实证 (67 个月, 2020-03 ~ 2026-04)

| Segment | Strategy | N | Ann% | Sharpe | Win% |
|---|---|---:|---:|---:|---:|
| FULL | LS (long fresh - short crowded) | 67 | **-5.67** | **-0.67** | 41.8% |
| FULL | long_only fresh | 67 | 7.48 | 0.33 | 52.2% |
| FULL | short_only crowded | 67 | -13.16 | -0.59 | 49.3% |
| IS 2020-2023 | LS | 45 | -5.65 | -0.65 | 40.0% |
| IS 2024 | LS | 12 | -4.19 | -0.45 | 58.3% |
| **IS 2024** | **long_only** | 12 | **20.18** | **0.78** | 41.7% |
| **IS 2024** | **short_only** | 12 | **-24.38** | **-1.06** | 58.3% |
| **OOS 2025** | **long_only** | 10 | **36.86** | **2.23** | 70.0% |
| **OOS 2025** | **short_only** | 10 | **-44.43** | **-2.29** | 20.0% |

结论:
1. LS 是 negative Sharpe 的全段一致 → fade 假设**失败**
2. Long crowded / Long fresh 都有正 alpha (long_only 整体 0.33, 2024-2025 迅速升高)
3. Short 整个金股榜是灾难 (2025 Ann -44.43%)
4. 2020-2023 alpha 不稳 (各策略 Sharpe 接近 0)
5. **近 2 年 regime change**: 券商金股 alpha 被价值发现, "follow smart money" > "fade crowded"

## 和 RIAD 的交叉验证

RIAD OOS 2025 Q1_long_only Sharpe=1.43 (Long 机构关注高 + 散户关注低)
BGFD OOS 2025 long_only Sharpe=2.23 (Long 上金股榜的股票)

两者都指向: **2024-2025 年 A 股 "追机构观点" 有正 alpha, "追散户观点" 有负 alpha**.

## 差异化价值

虽然单独 BGFD 不过门槛 (OOS LS Sharpe -1.04), 但作为 **"机构观点 heatmap"** 的数据源,
可以 validate RIAD 的 Long leg, 或 stack 成 universe 过滤器 (只在金股榜 ∪ 机构调研榜
内做 RIAD 打分, 避免垃圾股稀释).

## 代码

- `factor.py` — consensus + streak + zscore
- `evaluate_bgfd.py` — 月频 top/bot 30% 三种策略评估 (双边 0.3%)
- `logs/bgfd_eval_20260422.json` — per-month 明细 + 分段 summary

## 下一步 (次优先)

- [ ] BGFD long-only 作为 Universe 过滤器, 再叠加 RIAD 打分
- [ ] Broker-level 拆分: 某些头部券商 (中金/中信) 的金股是否比尾部 alpha 更稳
- [ ] Fresh pick (streak=1) vs Persistent pick (streak ≥ 2) 未来收益对比
- [ ] 和 Insider Trading / Lockup / PEAD 等事件因子 correlation, 看能否做 stacking
