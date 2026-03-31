# Goal: V7 Industry-Neutral Candidate Research (2026-03-31)

## Goal

定义并验证一条新的候选策略线：

```text
不是继续 patch v6
而是把行业中性化正式纳入策略定义
并用统一研究流程判断它是否值得进入 admission gate
```

这条 goal 的目标不是“把策略调到过线”，而是回答：

```text
当行业中性化成为策略定义的一部分后，
当前 5 因子组合是否仍然成立？
如果成立，它是否值得成为 v7 candidate？
```

## Why This Matters

- 行业中性化从方法论上本就应该更早进入主链路
- 过去 `v6` 的推进顺序偏向“先把 alpha 跑出来，再补组合工程”
- 现在 admission 连续 `DENY` 后，最该补的不是更多 tweak，而是更干净的组合定义
- 如果行业中性化做完仍然没有明显改善，系统就能更诚实地知道问题不在暴露控制，而在更深层的 alpha / 组合逻辑

## Scope

### In Scope
- [ ] 明确行业中性化在当前研究框架中的定义与实现位置
- [ ] 选择一套最小、稳定、可解释的行业中性化方案
- [ ] 在现有 5 因子组合上做 raw vs industry-neutral 对照
- [ ] 评估中性化前后的：
  - IC / ICIR
  - 分层收益
  - 组合表现
  - 回撤与暴露变化
- [ ] 明确是否形成新的 `v7 candidate`

### Out Of Scope
- [ ] 同时引入新的因子集合
- [ ] 同时做 MVO / CVaR / 权重优化
- [ ] 同时改持仓数、换仓频率、止损
- [ ] 直接把结果推进到 Phase 5

## Current Verified State

### Already Exists
- [x] 当前 5 因子主组合已明确：`team_coin + low_vol_20d + cgo_simple + enhanced_mom_60 + bp`
- [x] 因子分析工具链已存在，支持 IC / ICIR / 分层分析
- [x] admission 机制已存在，且 `v6` 已被正式拒绝

### Current Gaps
- [ ] 行业中性化还不是当前候选策略定义的默认部分
- [ ] 缺少 raw vs industry-neutral 的统一对照模板
- [ ] 缺少“行业中性后仍成立吗”的清晰结论

### Current Progress (2026-03-31)
- [x] 已完成第一轮 `raw vs industry-neutral` 离线对照
- [x] 已产出 [v7_industry_neutral_eval_20260331.md](/Users/karan/Documents/GitHub/quant-dojo/journal/v7_industry_neutral_eval_20260331.md)
- [x] 第一轮结论：保留为观察线，不直接升级为正式 `v7 candidate`
- [ ] 仍缺真实 `HS300` 指数缓存，因此当前结果不能与 admission 文档直接混写

## Operational Outcome

当本 goal 完成时，系统应该能明确回答：

- [ ] 现有 5 因子在行业中性化后是否仍具备组合意义
- [ ] 行业中性化是否显著改善回撤、稳定性或 admission 相关指标
- [ ] 这条线是否值得成为新的候选策略版本

## Implementation Plan

### Phase A: Neutralization Spec
- [ ] 明确使用的行业分类来源和频率
- [ ] 明确中性化方法（如截面回归残差 / 行业内标准化）
- [ ] 说明为什么选择该方法，而不是更复杂版本

### Phase B: Factor-Level Comparison
- [ ] 对当前 5 因子逐个做 raw vs industry-neutral 比较
- [ ] 输出每个因子的：
  - IC 均值
  - ICIR
  - 分层收益
  - 保留 / 观察 / 剔除结论

### Phase C: Portfolio-Level Comparison
- [ ] 用同一组因子、同一股票池、同一持仓数构建两个组合：
  - raw 版本
  - industry-neutral 版本
- [ ] 比较样本内 / 样本外 / walk-forward
- [ ] 只要出现其他变动，一律视为本 goal 失效

### Phase D: Candidate Decision
- [ ] 写出一份结论文档：
  - 是否形成 `v7 industry-neutral candidate`
  - 如果形成，它与 `v6` 的定义差异是什么
  - 如果未形成，说明行业中性化没有解决什么问题

## File-Level Work

### Research Runtime
- [ ] `utils/factor_analysis.py`
  - 明确行业中性化接口和默认使用方式
- [ ] `scripts/strategy_eval.py` 或新评估入口
  - 允许明确区分 raw vs industry-neutral

### Documentation
- [ ] [GOAL_v7_industry_neutral_candidate.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v7_industry_neutral_candidate.md)
  - 持续更新为该 candidate line 的执行入口
- [ ] `journal/`
  - 新增对照报告与 candidate decision

## Hard Constraints

- [ ] 本轮唯一主变量是“行业中性化是否进入策略定义”
- [ ] 不得把行业中性化与其他改动绑在一起
- [ ] 不得为了让结果好看重新改 admission 门槛
- [ ] 不得把研究结论偷换成“接近可用”

## Definition Of Done

- [ ] raw vs industry-neutral 对照完整存在
- [ ] 因子层与组合层都有结果
- [ ] 至少一份正式 journal 文档总结结论
- [ ] 明确写出：形成 candidate / 不形成 candidate
- [ ] 结果被正确挂回 `GOAL_factor_to_portfolio_pipeline.md`

## Must-Pass Commands

```bash
python -m compileall /Users/karan/Documents/GitHub/quant-dojo
python -m pytest -q /Users/karan/Documents/GitHub/quant-dojo/tests
```

## Risks To Watch

- [ ] 行业中性化只是让结果看起来更稳，但真实 alpha 被削空
- [ ] 把行业中性化误当成 admission 营救，而不是新策略定义
- [ ] 同时混入权重优化、持仓数调整等其他变量

## Status

### STATUS: ACTIVE
