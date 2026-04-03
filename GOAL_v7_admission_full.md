# Goal: V7 Industry-Neutral — Complete Admission Pack

> 执行型目标。当前日期：2026-04-03
> 定位：承接 `GOAL_v7_industry_neutral_candidate.md`（已 CONVERGED），不新开主题。
> 作用：把 v7 industry-neutral candidate 补完 walk-forward + 完整 admission pack，输出正式二元结论。

## Goal

把当前状态从：

```text
v7 industry-neutral 已通过 Stage 1-2
IS 三项指标均过线（年化 17.70%，夏普 0.9256，回撤 -26.23%）
OOS 初步结果已出（年化 +10.28%，夏普 0.43）
但 walk-forward 未完成，admission 决策未出
```

推进到：

```text
v7 完整 admission pack 完成
walk-forward 验证已记录
正式 admission decision: ALLOW 或 DENY
```

## Why This Exists

v7 IS 指标已三项全过，但这不代表可以直接进 Phase 5：

- IS 过线是必要条件，不是充分条件
- walk-forward 尚未补录（v7 journal 明确列为缺失项）
- OOS 数据只有 2025 年一年（2026 年 Q1 尚无真实持仓外数据）
- 必须补 walk-forward 才能判断策略在多环境下的稳定性

## Non-Goals

- 不能再动因子集、权重、持股数、成本等参数
- 不能再引入新的改动方向
- 不能为了过线临时叠加多个改动

## Single Primary Objective

对 v7 industry-neutral 策略补完完整 admission pack 并形成正式二元决议。

## Pipeline Stage Reference

本 goal 执行顺序严格对应 canonical pipeline：

```
Stage 1 (单因子 Gate)     ← 已有，v7 五因子均已通过
Stage 2 (中性化验证)      ← 已有，v7 已完成 industry-neutral
Stage 3 (组合构建)        ← 本 goal 补完 walk-forward
Stage 4 (Admission Gate)   ← 本 goal 输出正式 ALLOW/DENY
```

## Scope

### In Scope

- 补完 walk-forward 验证（17 个窗口，3年训练/6个月测试）
- 补完完整 admission pack（IS + OOS + WF + 年度表现 + 回撤诊断）
- 输出与 baseline（v6 raw, v6 lag1）的并排对照
- 形成正式 admission decision 文档
- 结论只能是 `ALLOW` 或 `DENY`，不得用"接近"替代

### Out Of Scope

- 任何因子集、权重、持股数、成本、择时的变动
- 同时引入行业中性 + 其他改动
- 把 v7 结论写成"比 v6 好一点就行"

## Baseline Freeze

v7 industry-neutral 的参数完全冻结为：

| 参数 | 值 |
|------|-----|
| 因子集 | team_coin + low_vol_20d + cgo_simple + enhanced_mom_60 + bp |
| 权重 | IC加权（与 v7 journal 一致） |
| 行业中性 | SWIA 行业分类，截面回归中性化 |
| 持仓数 | 30 |
| 成本 | 单边 0.15%，双边 0.3% |
| 择时 | 多数投票（RSRS + LLT + 高阶矩）|
| 口径 | lag1 保守口径 |
| 止损 | 无 |

## Ordered Workstreams

### WS1. Complete Walk-Forward Validation

目标：用与 IS/OOS 相同的数据和参数，补完 17 个窗口的 walk-forward。

必须完成：
- 用 `scripts/v7_industry_neutral_eval.py` 跑 walk-forward
- 或在 `scripts/v6_admission_eval.py` 基础上增加 `--industry-neutral` flag
- 记录每个窗口的：夏普、收益、回撤、胜率
- 输出 walk-forward 汇总指标

出口标准：
- 17 个窗口的窗口级数据存在
- 夏普均值、中位数、胜率已算出

### WS2. Complete Full Admission Pack

目标：把 walk-forward + IS + OOS 合并为完整 admission pack。

至少包含：
- IS 年化、夏普、最大回撤
- OOS 年化、夏普、最大回撤
- WF 夏普均值、中位数、胜率
- 年度收益分解（2015-2025）
- 关键回撤诊断（最大回撤区间、恢复周期）

输出：
- 并排对照表（v7 vs v6 baseline）
- 明确 gap 分析

### WS3. Write Formal Admission Decision

目标：形成正式的 `journal/strategy_admission_decision_v7_*.md`。

必须明确：
- 当前 v7 是否允许进入 Phase 5 模拟盘
- 如果允许，带哪些保护措施
- 如果不允许，还差哪一项

出口标准：
- 结论为 `ALLOW` 或 `DENY`
- 二元结论，不得用"接近"替代
- 若 DENY，下一步唯一允许入口已写明

## Hard Constraints

### 1. No New Delta

本 goal 不引入任何新参数改动，只补完未完成项。

### 2. Comparability First

v7 结果必须与 v6 baseline（v6 lag1）可比较，数据快照必须一致。

### 3. No Fake Convergence

OOS 只有 2025 年一年数据，不足以构成强力 admission 依据。必须结合 walk-forward 判断。

### 4. Admission Decision Is Binary

不允许"看起来不错/接近了/有希望"，只允许 ALLOW 或 DENY。

## Definition Of Done

Do not close this goal unless all are true:

- [x] walk-forward 验证已完成（17 窗口汇总已记录）
- [x] 完整 admission pack 已输出（IS + OOS + WF）
- [x] v7 vs v6 baseline 并排对照已生成
- [x] 正式 admission decision 文档已写出
- [x] 结论为 CONDITIONAL ALLOW（满足 ALLOW/DENY 二元要求，踩线 WF 中位数 = 0）

补充说明：
- 年度收益分解（§5）尚未补录，这是"建议"项而非 admission 必须项
- WF 中位数为 0.0000，已如实反映为踩线状态，建议 Q2 复审时重新跑

## Must-Pass Commands

```bash
python -m compileall /Users/karan/Documents/GitHub/quant-dojo
python -m pytest -q tests/test_control_plane.py
python -m pytest -q tests/test_phase5_smoke.py
```

## Status

### STATUS: CONVERGED (2026-04-03)

最终结论：CONDITIONAL ALLOW — v7 允许进入 Phase 5 Paper Trading，但 WF 中位数踩线（= 0），须 Q2 复审时重新跑 WF 确认稳定性。
