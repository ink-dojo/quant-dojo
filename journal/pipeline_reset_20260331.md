# Pipeline Reset Note — 2026-03-31

## Why This Note Exists

截至 `2026-03-31`，`quant-dojo` 已进入一个需要明确收口的节点：

- 系统工程层已经明显成型
- admission gate 机制已经存在
- 但当前 `v6` 系列主策略经过基线、止损、双周换仓三轮验证后，仍未能进入 Phase 5

如果此时继续围绕 `v6` 做“再试一个单变量”的救火式推进，项目会越来越接近：

```text
为了让结果过线而调整方法
```

这会伤害研究诚实性，也会让工程系统看起来比策略真实性更成熟。

## Canonical Conclusion

当前仓库的 canonical 结论应当是：

1. `v6(lag1)` 是一条被认真评估过的候选策略线，但当前**不具备进入 Phase 5 的资格**
2. 个股止损与双周换仓都已作为受控 admission retry 完成评估，并被关闭
3. 当前不应继续围绕 `v6` 做“怎么过线”的局部补丁
4. 下一步应切换到：

```text
因子构建
→ 中性化 / 暴露控制
→ 组合构建
→ admission 前置验证
→ 正式 admission gate
```

## What Changes From Here

从这份 note 开始，项目主线的理解方式发生变化：

### 旧理解

```text
v6 快要过线了
→ 再试一个 tweak
→ 争取进 Phase 5
```

### 新理解

```text
v6 已提供足够研究信息
→ admission 已给出明确拒绝
→ 现在要补的是“下一代策略是如何被生产出来的”
```

## Immediate Implications

- `Phase 5` 连续模拟盘不再以 `v6` 为默认主策略推进
- `WORKPLAN.md` 不再把双周换仓视为 active 主任务
- 行业中性化如果继续做，应被定义为**新 candidate line 的组成部分**，而不是 `v6 patch`
- 新一轮研究必须优先回答：
  - 因子在中性化后是否仍有效
  - 组合是否在可交易与风险暴露约束下仍成立
  - 候选策略是否值得进入 admission gate

## Linked Canonical Files

- [WORKPLAN.md](/Users/karan/Documents/GitHub/quant-dojo/WORKPLAN.md)
- [GOAL_factor_to_portfolio_pipeline.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_factor_to_portfolio_pipeline.md)
- [strategy_admission_decision_v6_20260325.md](/Users/karan/Documents/GitHub/quant-dojo/journal/strategy_admission_decision_v6_20260325.md)
- [strategy_admission_decision_v6_biweekly_20260326.md](/Users/karan/Documents/GitHub/quant-dojo/journal/strategy_admission_decision_v6_biweekly_20260326.md)

## One-Sentence Rule

从现在开始，`quant-dojo` 的主任务不再是“让 `v6` 过线”，而是“把一条诚实、可复现、可持续的量化研究生产线做完整”。
