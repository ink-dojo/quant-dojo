# BTA (大宗交易机构吸筹) 因子线 — 终结记录

**日期**: 2026-04-21
**作者**: jialong
**状态**: 两次 pre-reg 均 FAIL, 该因子线按 pre-reg 纪律终止

---

## 1. 实验线路回顾

### 1.1 Sanity (2026-04-21 早)

文件: `research/event_driven/block_trade_sanity.py` + `block_trade_sanity_v2.py`

方向: 检验"大宗交易折价+买方身份"能否预测未来 21 日收益.

关键发现 (v2 四象限分析):

| 象限 (buyer × seller) | n | mean fwd_21d | wr |
|---|---:|---:|---:|
| 买机构 + 卖非机构 (机构吸筹) | 16,661 | **+1.07%** | 0.520 |
| 买机构 + 卖机构 (对倒) | 3,303 | +0.48% | 0.509 |
| 买非机构 + 卖机构 (出货) | 20,150 | +0.36% | 0.502 |
| 散户/游资互换 | 97,942 | +0.21% | 0.497 |

- 机构吸筹 vs 非机构吸筹 Welch t = **+8.52** (p≈0, n=16.6k vs 97.9k).
- Cluster 单调: 1+ 次 +0.79% → 2+ +1.05% → 3+ **+1.26%** (960 样本).
- 主板 vs 非主板: 主板 +1.17%, 非主板 +0.60% (主板更干净).

sanity 层面看 signal 存在, 且在主板上更强.

### 1.2 DSR #35 (2026-04-21 午): amount-ranked top-30

文件: `research/event_driven/block_trade_inst_accum_strategy.py`
Pre-reg commit: `52d0225`, FAIL commit: `35ece51`.

参数 (锁定):
- Universe: 主板
- Filter: buyer=机构专用 AND seller != 机构专用
- Selection: 月度 cross-section 按累计 amount top-30
- Hold 21d, weight 1/30, gross cap 1.0, cost 0.30% 双边.

结果: **0/5 FAIL**
- Long-only: ann -3.96%, SR -0.22, MDD -62.82%
- Hedged: ann -6.80%, SR -0.35, MDD -53%

### 1.3 Post-mortem (2026-04-21 午)

文件: `research/event_driven/bta_postmortem.py`

诊断四个假设:
- **(A) 选错 axis** ✓: top-30 by amount 平均 +0.36% ≈ 全体均值, 但 amount 最小 decile +2.79% > 最大 decile +1.35%. 即 amount ranking 选到的是白马大盘, 平均效应被 *稀释* 而不是 *浓缩*.
- **(C) 2022 concentration** ✓: 主板机构吸筹 2022 -0.54% (抱团瓦解年), 2016/2019/2020/2025 均 >+1%.
- **核心结论**: 最强 subset 是 **cluster 3+ events/month/stock: +1.29%** (960 样本), 不是 amount-ranked.

推论: 信号不在"最大单笔交易", 而在"同股反复机构吸筹"的 **high-conviction** pattern.

### 1.4 DSR #36 (2026-04-21 下午): cluster-count variant

文件: `research/event_driven/dsr36_bta_cluster_strategy.py`
Pre-reg commit: `5ec92d3`.

参数 (锁定):
- Universe: 主板
- Filter: buyer=机构专用 AND seller != 机构专用
- Selection: 过去 30 天同股累计机构吸筹 ≥ 3 次时开仓
- Hold 21d, unit weight 1/30, gross cap 1.0, cost 0.30% 双边.

结果: **1/5 FAIL**

Long-only:
- ann **+1.81%**, SR **+0.022**, MDD **-29.21%** (PASS), PSR 0.549, CI_low -0.22
- 5/5 仅 MDD 通过

Hedged (vs HS300):
- ex_ann +0.86%, ex_SR -0.168, ex_MDD -16.82% (PASS), ex_PSR 0.298, ex_CI_low -0.36
- 5/5 仅 ex_MDD 通过

Risk/turnover:
- mean_gross **0.294** (低仓位, 信号稀疏)
- ann_turnover **7.06x** (低频成功)

年度 long-only 收益:
| 年 | lo_ret | lo_sr |
|---|---:|---:|
| 2016 | -0.03 | -0.41 |
| 2017 | +0.04 | +1.05 |
| 2018 | -0.07 | -1.45 |
| 2019 | +0.07 | +1.29 |
| 2020 | **+0.15** | +0.96 |
| 2021 | -0.01 | -0.17 |
| 2022 | **-0.18** | -2.10 |
| 2023 | +0.05 | +0.80 |
| 2024 | +0.00 | -0.02 |
| 2025 | **+0.24** | +2.25 |

---

## 2. 为什么 FAIL?

两个事实 co-exist 必须解释:
- sanity Welch t=+8.52 的 per-event effect 真实存在
- 组合层面 10 年 +1.81% 年化, 夏普 0.02

解释:

1. **信号稀疏 → gross 低 (0.294)**: mean_gross 只 29.4%, 大部分时间空仓. 即使 per-event edge 1%+, 乘以低 exposure 就稀释成年化 1-2%.
2. **2018/2022 两次大熊拖**: 10 年里有 2 年 -7% 和 -18%, 抱团瓦解/mean-reversion 时机构吸筹信号反转 (已在 sanity v2 看到: 2022 diff 为负). 单边多头无法对冲.
3. **Hedge 不是 free lunch**: 对冲 HS300 后夏普更差 (-0.168), 因为 beta 不稳定, 对冲掉的 market return > alpha, 净 alpha 太薄.
4. **Cost 0.30% 双边**: 虽然换手只 7x/年, 但对薄 alpha 仍明显. gross ann 估 +3-4%, net +1.8%.

核心诊断: **alpha 真实但不够厚**, 在散户可执行的主板 universe + 低频约束下, 不足以越过 admission gate.

---

## 3. 两次尝试的 variance 分析

| 变体 | ann | SR | MDD | n_pass | 主要原因 |
|---|---:|---:|---:|---:|---|
| DSR #35 amount-top30 | -3.96% | -0.22 | -62.8% | 0/5 | 选错 axis (amount ≠ edge) |
| DSR #36 cluster 3+ | +1.81% | +0.02 | -29.2% | 1/5 | 选对 axis 但 signal 太稀薄 |

差值: axis 修对后 ann 提升 5.77pp, MDD 减半, 但仍不过 gate.

---

## 4. Pre-reg 纪律执行

引用 DSR #36 spec line 36-37:
> ≤3/5 → 记录 post-mortem, 不再调参

以及:
> 独立 trial: 基于 DSR #35 post-mortem 的发现设计新 selection rule, 独立 pre-reg, 独立执行, 不合并结果. 若 FAIL, **不再试第三次 amount/count 变体**.

**决定**: BTA 因子线在这两次 pre-reg 后按纪律终止. 不再试 cluster 2+/4+, 不再试 holding 5d/60d, 不再试其他加权方式. 这避免 p-hacking.

---

## 5. 后续方向 (待 jialong 选择)

用户原始 requirement: 低频 + 散户可执行 + 严谨回测. 候选:

**A. 限售解禁 (unlock) 逆向因子**
- 假设: 解禁前负收益, 解禁后反弹 (已被学术文献 confirm)
- 数据: tushare share_float 已爬
- 低频: 月度 rebalance, 每股一年 1-2 次触发
- 散户友好: 公开日历, 信号不稀缺

**B. 基本面 quality 复合因子 (ROE + gross margin + 增长一致性)**
- 假设: A 股 value 薄但 quality 厚 (私募高毅/景林路径)
- 数据: fina_indicator 已爬
- 低频: 季度 rebalance
- 需要: 至少 3 个子因子组合 + cross-sectional zscore

**C. 机构调研频率 (institutional survey) revisit**
- 已做过 survey_attention 研究 (见 research/factors/survey_attention/)
- 可考虑跟其他因子合成 (如 x crowding filter)
- 已有 v17 胜出 baseline, 扩展成本低

**D. 放弃 event-driven, 专攻 v17 → v18 cross-sectional 精修**
- v17 已 OOS 通过
- Phase 3 原计划的终点
- 风险: 无新 alpha, 容量不增

建议优先序: **A > B > D > C** (A 数据现成且逻辑独立, 最容易用 pre-reg 纪律验证).

等用户指令.
