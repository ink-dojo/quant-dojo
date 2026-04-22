# Goal: Factor-To-Portfolio Pipeline Reset (2026-03-31)

## Goal

把 `quant-dojo` 从“围绕单一候选策略做 admission 营救”重置为“一条可持续产出、验证、淘汰策略的标准化研究生产线”。

最终目标不是让 `v6` 想办法过线，而是让系统能够稳定回答以下问题：

```text
这个因子为什么存在
→ 它是否有效
→ 它在中性化后是否仍有效
→ 它如何进入组合
→ 这个组合在可交易约束下表现如何
→ 它是否值得进入 admission gate
→ 它如果被拒，应该如何被归档和替换
```

这条 goal 的产出应该是一套更干净的“因子 -> 组合 -> 门禁”流水线，而不是某个 lucky strategy。

## Why This Matters

- 当前 `v6(lag1)` baseline、止损、双周换仓已连续被正式 `DENY`
- 继续围绕 `v6` 做单变量过线尝试，已经开始接近 result shopping
- 现有系统工程层已经明显强于策略层，必须把“策略如何被生产出来”这条链路补规范
- 如果不重置主线，项目会继续陷入：

```text
工程越来越完整
但主策略仍未成立
然后不断用局部补丁试图让它过线
```

这会同时伤害研究诚实性和系统可信度。

## Scope

### In Scope
- [ ] 明确停止把 `v6` 作为当前 admission retry 主线
- [ ] 定义统一的因子研究标准：原始因子、行业/市值中性化、IC/ICIR/FM、分层收益、压力期
- [ ] 定义统一的组合构建标准：可交易过滤、持仓数、行业暴露、权重规则
- [ ] 定义“候选策略如何进入 admission gate”的前置条件
- [ ] 产出一条新的研究主线，作为下一代候选策略（可叫 `v7 candidate`，但不预设一定成功）
- [ ] 让 journal / workplan / goal 状态与真实结论一致

### Out Of Scope
- [ ] 继续对 `v6` 做第三轮 admission retry
- [ ] 直接推进 Phase 5 连续模拟盘
- [ ] 单纯扩更多 dashboard 展示
- [ ] 为了追求收益曲线好看而临时叠加多项组合技巧

## Current Verified State

### Already Exists
- [x] 数据层、provider 层、CLI、control plane、dashboard、paper trader 基础骨架已存在
- [x] 因子研究、样本内/样本外、walk-forward、admission gate 基础框架已存在
- [x] `v6(lag1)` honest baseline 已完成关键 correctness 修复
- [x] 个股止损评估已完成并关闭
- [x] 双周换仓评估已完成并关闭
- [x] `journal/strategy_admission_decision_v6_biweekly_20260326.md` 已正式写明：维持 `DENY`

### Current Gaps
- [ ] `WORKPLAN.md` 仍把“双周换仓 retry”写成当前主任务，和真实状态不一致
- [ ] 行业中性化、组合约束、风险暴露控制未成为研究生产线的默认环节
- [ ] admission gate 之前缺少“候选策略是否具备入闸资格”的更上游标准
- [ ] 当前系统容易把“改到过线”误当成“研究进步”

## Operational Outcome

当本 goal 完成时，系统应该能做到：

- [ ] 不再把 `v6` 当作当前 Phase 5 候选主策略
- [ ] 任何新候选策略都必须经过同一套标准研究流程
- [ ] 因子研究结果、组合规则、admission 结论之间有明确衔接
- [ ] 研究失败也能被系统化记录，而不是继续用补丁推进

## Implementation Plan

### Phase A: Canonical Reset
- [ ] 更新 `WORKPLAN.md`，停止把双周换仓写为 active retry
- [ ] 在相关 goal / journal 中明确：`v6` 当前退出 admission 主线
- [ ] 补一份短文档，说明为什么此时不能再继续做 `v6` 救火式 retry

### Phase B: Standard Research Pipeline
- [ ] 定义单因子标准验证模板
- [ ] 定义组合前置要求：行业中性化、暴露检查、可交易约束
- [ ] 定义策略进入 admission gate 的准入前提
- [ ] 明确哪些指标属于“研究阶段看”，哪些属于“admission 阶段看”

### Phase C: Next Candidate Strategy Definition
- [ ] 选择下一代候选策略的唯一研究起点
- [ ] 默认优先方向：**行业中性化作为新策略定义的一部分**
- [ ] 明确它不是 `v6 patch`，而是新的 candidate line
- [ ] 给下一轮研究限定单一主变量，避免重新回到 result shopping

当前首个具体执行入口：

- [GOAL_v7_industry_neutral_candidate.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v7_industry_neutral_candidate.md)
  - 作为下一代 candidate line 的第一条正式研究目标

## File-Level Work

### Canonical Planning
- [ ] [WORKPLAN.md](/Users/karan/Documents/GitHub/quant-dojo/WORKPLAN.md)
  - 收口当前优先级，移除“继续双周换仓 retry”的表述

### Strategy / Admission Context
- [ ] [GOAL_v6_biweekly_rebalance_eval.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v6_biweekly_rebalance_eval.md)
  - 标注结果已完成且为 `DENY`
- [ ] [GOAL_v6_admission_push.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v6_admission_push.md)
  - 标注该系列已停止作为当前主任务
- [ ] [GOAL_strategy_validation_gate.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_strategy_validation_gate.md)
  - 与新的 pipeline 逻辑对齐，明确“不是用 admission 补研究缺口”

### New Research Definition
- [ ] [GOAL_factor_to_portfolio_pipeline.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_factor_to_portfolio_pipeline.md)
  - 作为新的 canonical pipeline goal 持续更新
- [ ] `journal/` 新增一份 reset / direction note
  - 记录为什么从 `v6 rescue` 转向 `pipeline-first`

## Definition Of Done

Do not close this goal unless all are true:

- [ ] `WORKPLAN.md` 与最新 admission 结论一致
- [ ] `v6` 不再被表述为当前 active admission retry 主线
- [ ] 统一的“因子 -> 中性化 -> 组合 -> admission”流程被写清
- [ ] 下一代候选策略研究入口已被定义
- [ ] 已明确行业中性化在新候选策略中的定位
- [ ] 文档中不再出现“继续围绕 deny 的 v6 做过线优化”的隐含指向

## Exit Gates

`STATUS: CONVERGED` is allowed only if all of the following are true:

- [ ] Canonical planning docs match actual repo state
- [ ] The next strategy research loop is defined without result-shopping bias
- [ ] Residual risks and open research questions are explicitly written down
- [ ] The repo now distinguishes clearly between:
  - system infrastructure progress
  - strategy research progress
  - admission readiness

## Must-Pass Commands

```bash
python -m compileall /Users/karan/Documents/GitHub/quant-dojo
python -m pytest -q tests/test_control_plane.py
python -m pytest -q tests/test_phase5_smoke.py
```

## Manual Verification

- [ ] Read `WORKPLAN.md` and confirm it no longer points to a closed retry as active work
- [ ] Read the latest admission decision and confirm the new pipeline goal matches it
- [ ] Confirm the next research direction is framed as a new candidate line, not a patch-on-deny loop

## Risks To Watch

- [ ] Dressing up a strategy reset as “just one more retry”
- [ ] Confusing factor research with admission rescue
- [ ] Letting infrastructure completeness mask strategy weakness
- [ ] Reopening multiple strategy dimensions at once

## Self-Review Checklist

- [ ] Does this change reduce research self-deception rather than just rewrite docs?
- [ ] Does the new plan make it easier to reject weak strategies cleanly?
- [ ] Does it clarify where industry neutralization belongs in the pipeline?
- [ ] Does it preserve the long-term goal of building a full quant system?

## Status

### STATUS: ACTIVE
