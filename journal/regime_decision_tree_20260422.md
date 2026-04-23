# Regime Shift 后的策略调整决策树
_2026-04-22, refs Issue #37 (regime boundary analysis)_

## 背景

`scripts/regime_boundary_analysis.py` (脚手架已推到 main) 在 jialong 机器上跑完后,
会产出 3 个判读材料:

1. `outputs/regime_boundary/breakpoint.json`
   - `first_negative_month` (跨因子健康指数首次掉负的月份)
   - `first_sustained_negative_month` (连续 3 月以上为负的起始月份)
   - `peak_to_trough_delta` (从最高月到最低月的下跌幅度)
2. `outputs/regime_boundary/lag_corr.json`
   - 5 个因子聚合健康度 vs HS300 4 个 macro 特征的滞后互相关 (lag -3 ~ +3 月)
3. `outputs/regime_boundary/regime_boundary.png`
   - 三联图: 因子月度 IC 折线 / 跨因子健康指数 / macro overlay

本文是 **决策框架**: 拿到上述材料后, jialong 应当把现状对应到下面 4 个 scenario 之一,
直接指向后续行动. 目的是把"研究结果到行动"的延迟降到 1 天内.

> 本文不是 pre-reg, 不替任何策略选项做 5-gate 判断. 它只规定"接下来开哪条 issue".

---

## 判读输入: 3 个 must-check 数字

| 维度 | 来源 | 解读 |
|---|---|---|
| `first_sustained_negative_month` | breakpoint.json | < 2024-09 → 早 ; 2024-09 ~ 2025-03 → 居中 ; > 2025-03 或 null → 晚 / 无 |
| `peak_to_trough_delta` | breakpoint.json | < -0.04 → 大 ; [-0.04, -0.02] → 中 ; > -0.02 → 小 |
| 最大 lag 相关性 (绝对值) | lag_corr.json | > 0.5 → 强 macro 联动 ; [0.3, 0.5] → 弱联动 ; < 0.3 → 无联动 |

**注意:** RIAD 单独的月度 IC 也要看 — 如果 RIAD 单独 2025-12 的 IC < -0.02 (effective_ic 转正向看)
**且** 跨因子聚合健康度持续负, 说明 spec v4 的 RIAD 腿确实进入新 regime.

---

## 4 个 Scenario

### Scenario A — Step Jump 型 (强 macro 联动)

**触发判读**:
- `first_sustained_negative_month` ∈ [2024-08, 2024-11] (短窗内突变)
- `peak_to_trough_delta` < -0.04 (大幅下跌)
- 最大 lag 相关性 > 0.5 (与某个 macro 特征强关联, 通常 lag = -1 或 0 月)

**含义**: 一个 macro 事件 (最可能 9·24 货币宽松) 把 5 个因子同步推翻.
不是 factor decay, 是 regime 切换.

**行动 → 路径 A: 加 Regime Gate**

具体动作:
1. 用 lag_corr.json 找出最强 macro 特征 (大概率 vol_ratio 或 ret_6m)
2. 以转折月对应的 macro 阈值, 定义 `regime_high_vol` / `regime_normal` 二元 gate
3. 在 `pipeline/regime_detector.py` 填入阈值常量 (本次 commit 已推框架)
4. 修改 `pipeline/riad_signal.py` (见 spec v4 §1.2) 在生成信号前调用 gate:
   - `regime_high_vol` → return None (不调仓, 现金)
   - `regime_normal` → 正常下信号
5. 回测 gate 的效果: `python -m pipeline.experiment_runner --gate regime_v1`
6. 必须 **重过 5-gate** (DSR 会因样本变少下降, 需 jialong 评估是否仍达标)

**Owner**: 本机我可做; jialong 提供阈值
**周期**: 3 天
**风险**:
- gate 本身在新 macro 下也可能失效 (regime 不止 2 个), 需持续 monitor
- 样本切割后 DSR 下降, 可能掉出 4/5 → spec v4 改成 spec v5

**产出新 issue**: "regime gate v1 实现 + spec v5 pre-reg"

---

### Scenario B — Gradual Decay 型 (无明显转折点)

**触发判读**:
- `first_sustained_negative_month` 模糊 / null (不连续, 反复进出负值)
- `peak_to_trough_delta` ∈ [-0.04, -0.02] (温和下跌)
- 最大 lag 相关性 < 0.3 (与 macro 无明显关联)

**含义**: 不是某个事件, 是 5 个因子各自慢慢被套利. RIAD 的衰减是结构性的,
不会因为某个 macro 翻转而恢复.

**行动 → 路径 B: 参数重估 + 预注册**

具体动作:
1. 把 RIAD 现有参数当作 v1, 不修改原 spec
2. 在 [2024-09, 2025-12] 上做 walk-forward 参数搜索:
   - `vol_window`: 10 / 20 / 40
   - `quantile_split`: (0.1,0.5)/(0.2,0.6)/(0.3,0.7)
   - `hold_days`: 10 / 20 / 30
3. 写 `journal/riad_v2_preregistration_YYYYMMDD.md` 锁死新参数
4. 用 v2 参数重过 5-gate
5. 与 v1 对比: SR 提升 > 0.3 才上线, 否则放弃

**Owner**: 本机我可做
**周期**: 4-5 天
**风险**:
- 参数调优 = 数据窥视的边缘. 必须严格 pre-reg, 严禁迭代调参
- 新参数可能只是"在新 regime 下的临时适应", 下个 regime 又死
- 5-gate 重新算时 DSR 选择偏差扣分会更重 (n_trials 增加)

**产出新 issue**: "RIAD v2 参数重估 + WF + pre-reg"

---

### Scenario C — RIAD 彻底失效型 (factor death)

**触发判读**:
- 不论 sustained_negative_month 如何, RIAD **单因子月度 IC** 在最近 6 个月有 ≥ 4 月 < -0.02
- 跨因子聚合健康指数最近 3 月平均 < 0
- macro 联动 < 0.3 (排除"等 macro 反转就能救")

**含义**: RIAD 这个因子的 alpha 已经被市场 price-in. 量化打板套利 + 监管放松 + 散户回流
导致它的反转假设不再成立. 不是参数问题, 是因子本身的问题.

**行动 → 路径 C: 替换因子**

具体动作:
1. 立刻砍掉 spec v4 的 RIAD 腿, 不等 jialong 批准
2. 候选替代品 (按优先级):
   - **C1: LULR v2 (动量假设)** — 见同日 `journal/lulr_v2_preregistration_20260422.md`,
     IC 已经 +0.042 显著, 翻转方向后即可上线. 最快.
   - **C2: DSR#30 BB-only 单腿** — 最保守. spec v3 已过 4/5 gate, 直接退回 v3.
   - **C3: 新挖因子** — 必须先 D 阶段挖到, 当前没现成的. 最慢.
3. 选定后写新 spec (v5), 重做组合 50/50 或 100% 单腿的 walk-forward + 5-gate
4. 如果选 C1, 先在 paper trade 跑 1 个月对照, 不直接 live

**Owner**: jialong 决策选哪个; xingyu 实现
**周期**:
- C1 路线 (LULR v2): 3 天
- C2 路线 (退回 v3): 1 天
- C3 路线 (新因子): 2-3 周
**风险**:
- C1: LULR 正 IC 持续性未验证, 也可能再翻转一次
- C2: 失去 RIAD 的多样化收益 (spec v4 文档显示 +0.47 Sharpe, MDD -41%)
- C3: 新因子在当前 regime 下挖出来的, 也可能是 regime-specific

**产出新 issue**: "spec v5: RIAD 退役 + 替代腿确定"

---

### Scenario D — 因子分散时间表型 (各自老去)

**触发判读**:
- 看 factor_panel.parquet 的逐因子月度 IC 时序
- 5 个因子的 sustained_negative_month 散布在不同月份 (跨度 > 6 月)
- 无统一转折点

**含义**: 不是 regime shift, 是 5 个因子各自有不同的"退休时间表".
每个因子的 alpha 半衰期不同, 看起来像 regime 是因为 2024-2025 恰好是几个因子的衰减交集.

**行动 → 路径 D: 因子级 sunset 策略 (无全局 gate)**

具体动作:
1. 不动 spec v4
2. 每月跑 `pipeline/rx_factor_monitor.py`, 给每个因子设独立的 sunset 阈值:
   - 6 月 effective IC < -0.02 → degraded warn
   - 12 月 effective IC < -0.02 → 强制 sunset, 从 registry 移除
3. 维持现有 RIAD + DSR#30 组合, 等下一个新因子接班 (D 阶段挖)
4. 不加 regime gate, 不调参

**Owner**: 自动化; 我加 monitor 阈值
**周期**: 1 天 (代码已存在, 加 sunset 逻辑即可)
**风险**:
- "无 regime shift" 假设可能错, RIAD 实际还是会在新 macro 下进一步衰减
- 没有保护机制, 实盘损失风险全靠 spec v4 自己的 kill switch

**产出新 issue**: "rx_factor_monitor 加 auto-sunset 逻辑"

---

## 决策矩阵 (一图速查)

| sustained_neg_month | peak_trough_delta | macro lag corr | RIAD 月度 IC | → Scenario |
|---|---|---|---|---|
| 2024-08 ~ 2024-11 | < -0.04 | > 0.5 | (可负可不负) | **A** Regime Gate |
| 模糊 / 反复 | [-0.04, -0.02] | < 0.3 | 慢慢负 | **B** 参数重估 |
| (任意) | (任意) | < 0.3 | 6 月内 ≥ 4 月 < -0.02 | **C** 替换因子 |
| 各因子分散 > 6 月 | (任意) | (任意) | 与其他不同步 | **D** Sunset 策略 |

> 多个 scenario 同时触发时, 优先级 **C > A > B > D** (C 最严重, D 最温和).

---

## 优先级排序

如果 jialong 不确定结果属于哪种, 按这个顺序行动:

1. **先看 RIAD 单因子月度 IC** — 如果最近 6 月有 4 月 < -0.02, 直接进 C, 不用看其他
2. **再看跨因子聚合健康指数** — 持续负 → A 或 B; 反复 → D
3. **看 lag_corr** — 强联动 → A; 弱联动 → B
4. **看分布** — 各因子时间不同步 → D 而不是 A/B

---

## 这次 commit 的相关产物 (已推 main)

- 本文 — 决策框架
- `journal/lulr_v2_preregistration_20260422.md` — Scenario C1 路径的预注册文档
- `pipeline/regime_detector.py` — Scenario A 路径的代码框架 (待 jialong 填阈值)

jialong 跑完 regime_boundary_analysis.py 后, 拿对应 scenario 的 follow-up
就能直接动工, 不用从零设计.

---

## 红线 (必读)

1. **不能基于 lag_corr.json 直接调 RIAD 参数** — 那是 monitoring 数据, 调参必须独立 pre-reg
2. **不能 cherry-pick scenario** — 决策矩阵给的是哪条就走哪条, 不能"因为不喜欢 C 就改判 D"
3. **C1 路径的 LULR v2 必须先过 5-gate**, 不能因为"现成的就上"绕过门槛
4. **A 路径的 regime gate 必须用 [2024-09, 2025-12] **以外**的数据验证**,
   不然就是用结果验证假设, 必然过拟合

---

— 记录: jialong + xingyu 协作框架
— 更新: 2026-04-22
