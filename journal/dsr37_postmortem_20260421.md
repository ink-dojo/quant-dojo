# DSR #37 — 限售解禁后反弹 Post-mortem

**日期**: 2026-04-21
**状态**: FAIL 0/5 (long-only) + 0/5 (hedged)
**Pre-reg commit**: `6abecf9`

---

## 1. 结果

| 指标 | long-only | hedged | gate |
|---|---:|---:|---|
| ann | +7.34% | +6.51% | >15% FAIL |
| Sharpe | 0.358 | 0.377 | >0.8 FAIL |
| MDD | -33.84% | -36.29% | >-30% FAIL |
| PSR | 0.899 | 0.922 | >0.95 FAIL (接近) |
| CI_low | -0.25 | -0.36 | >0.5 FAIL |

mean_gross 0.556, ann_turnover 16.3x, n_events 3,223.

## 2. 年度收益

| year | lo_ret | lo_sr | hd_ret | hd_sr |
|---|---:|---:|---:|---:|
| 2018 | **-12.86%** | -0.49 | +8.23% | +0.64 |
| 2019 | +8.98% | +0.72 | -7.04% | -0.82 |
| 2020 | +7.20% | +0.61 | -10.79% | -1.31 |
| 2021 | +22.85% | +1.43 | +27.06% | +1.57 |
| 2022 | -5.02% | -0.11 | +15.96% | +1.07 |
| 2023 | +19.26% | +1.32 | +21.72% | +1.79 |
| 2024 | -0.27% | +0.15 | -11.69% | -0.46 |
| 2025 | +22.15% | +2.11 | +14.39% | +1.93 |

## 3. Sanity vs Portfolio 的 gap

Sanity (per-event):
- 8/8 年份 post_20d_return 全部正 (2018 +0.85%, 最低)
- 过滤后 n=3,223 mean +2.51%

Portfolio:
- 2/8 年份 long-only 负 (2018 -12.86%, 2022 -5%)
- ann +7.34% 净值

**差值来源** — 事件集中度 × 市场 beta:

| year | n_events | CSI300 ann | lo_ret | 推论 |
|---|---:|---:|---:|---|
| 2018 | 519 (最多之一) | ~-25% | -12.86% | 熊市事件多 → 满仓被 beta 拖 |
| 2022 | 596 (最多) | ~-22% | -5.02% | 熊市事件多 → 满仓 |
| 2019-2020 | 296/321 (少) | 牛 | +7-9% | 牛市事件少 → gross 低, 吃不到 |
| 2025 | 173 (最少) | 牛 | +22% | per-event 高达 +6.3%, 少即是多 |

核心问题: **pre_20d_return <= -10% filter 在熊市触发更多事件**. 因为熊市时
更多股票 20 日跌 >10%. 所以 selection rule 天然把最多仓位摆在市场最差时候
→ gross 被动加码在错误时机 → 被 beta 吃掉 alpha.

2018 月度分布验证: 6 月 88 事件, 7 月 65, 10 月 76 (都是 2018 深熊).
21 日 hold 意味着那几个月并发 60-80 仓位, gross cap 顶死.

## 4. Hedge 失效原因

Hedge (long − HS300 × gross) 的 Sharpe (0.377) 和 long-only (0.358) 差异不大:
- 2018: hedged +8.23% (救了长仓)
- 2019-2020: hedged -7/-11% (牛市对冲反噬)
- 2024: hedged -12% (结构性牛市年, HS300 抱团)

Beta 不稳定 → hedge 在不同 regime 方向反转. 信号 intrinsic 跟市场 correlate
(熊市事件多), hedge 把 correlation 又暴露一次.

## 5. 可以改吗? (答: Pre-reg 纪律禁止)

引用 DSR #37 spec: "≤3/5 → 记录 post-mortem, 不再调这个因子的参数".

**不改参数**. 但从学习角度记录可能改进方向 (未来新 pre-reg 再试):
1. **Volatility-adjusted weight**: 按 IV 反比定仓, 熊市天然降仓位
2. **Market regime filter**: HS300 20d MA 下行时不开新仓
3. **Pre_20d 区间条件** (而非阈值): -20%<pre<-5% 避免极端 tail
4. **持仓分阶段**: D+1 → D+5 → D+21 多段出清, 减 concentration
5. **放弃 long-only, 做 long-short cross-sectional**: 高 pre_20d 组作空头

但这些都是 post-hoc 猜想, 需要独立 pre-reg + 独立数据 (2026+ OOS) 才可信.

## 6. 累计结果 (Phase 3 event-driven 线)

| DSR # | 因子 | 结果 | 主要原因 |
|---|---|---|---|
| #35 | BTA amount-top30 | 0/5 FAIL | 选错 axis |
| #36 | BTA cluster 3+ | 1/5 FAIL | alpha 太薄 |
| #37 | 解禁后反弹 + pre sold-off | 0/5 FAIL | alpha 真实但事件集中在熊市 |

Event-driven 系列三次 pre-reg FAIL. 逻辑上一致发现: **A 股事件型 alpha 在
per-event 统计显著, 但实盘化遇到 (a) 信号稀疏 (b) 熊市集中, 都过不了 5/5 gate**.

## 7. 决策建议

候选 (等 jialong 选):

**B. 基本面 quality 复合因子 (ROE + 毛利 + 增长一致性)**
- 换赛道: 从 event-driven → cross-sectional
- 月频 rebalance, 容量大, A 股顶级私募路径
- 数据: fina_indicator (3100+ 股票 × 季度)

**C. 机构调研 × crowding 合成 (扩展 v17)**
- v17 已 OOS 通过, 在它之上加一层
- 低风险, 但 upside 有限

**D. 回到 v17 → v18 做风控精修 (regime overlay + 动态 cap)**
- 不追新 alpha, 专注现有策略的稳健性
- 适合下一步进模拟盘的准备

**E. 保守接受现状, 直接用 v17 进模拟盘**
- Phase 3 阶段性 closure
- 省时间, 下一步 Phase 4 实盘准备

个人建议: **D → E**. 三次 event-driven 失败说明散户可执行的事件型 alpha 很薄,
v17 已是能拿出来的最佳 cross-sectional 方案. 专注把 v17 打磨到能上模拟盘,
比继续追新因子更务实.
