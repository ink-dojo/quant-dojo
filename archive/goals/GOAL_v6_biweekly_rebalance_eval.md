# Goal: V6 Biweekly Rebalance Admission Eval

> 执行型目标。当前日期：2026-03-26
> 定位：承接 `GOAL_v6_admission_push.md`，不是新主线。
> 作用：在 `v6(lag1)` 可信基线已经锁定、止损实验已关闭后，只测试一个新的最小改动：双周换仓。
>
> 更新（2026-03-31）：本 goal 已完成，结果为正式 `DENY`。保留本文件作为历史评估记录，不再作为当前 active retry。

## Goal

把当前状态从：

```text
v6(lag1) honest baseline 已可信
止损实验已完成但未过线
下一步方向已锁定为双周换仓
```

推进到：

```text
双周换仓被单独评估
与月频 baseline 可直接比较
形成新的正式 admission decision
```

这个 goal 只回答一个问题：

```text
在不改变其他参数的前提下，双周换仓能否让 v6(lag1) 通过 admission gate？
```

## Why This Exists

截至 `2026-03-26`：

- `v6(lag1)` baseline 已完成 critical 修复，基线数字可信
- 个股止损实验已完成，风险指标改善明显，但单独不足以推过门槛
- `strategy_admission_decision_v6_20260325.md` 已将“下一轮唯一允许变动”收口为双周换仓
- 研究结论也反复指向：`reversal` / `team_coin` 可能在更短换仓周期下更有效

因此，当前最合理的下一步不是继续发散，而是：

- 保持因子、择时、持股数、成本、过滤条件全部冻结
- 只修改换仓频率
- 重跑完整 admission pack

## Non-Goals

以下内容明确不属于本 goal：

- 同时启用止损 + 双周换仓
- 调整因子集合
- 调整择时模型
- 调整持股数
- 改交易成本假设
- 启用行业中性化 / MVO / 新组合优化
- 推进 Phase 5 连续模拟盘

## Single Primary Objective

用唯一变动“月频 -> 双周换仓”重跑 admission 评估，并形成新的二元决议：`ALLOW` 或 `DENY`。

## Decision Rule

从本 goal 开始，以下规则强制生效：

1. admission 仍只看 `lag1` 保守口径
2. 本轮唯一允许变动是换仓频率：`月频 -> 双周`
3. 任何结果如果混入止损或其他附加改动，一律视为无效
4. 结论必须是 `ALLOW` 或 `DENY`，不得用“接近通过”收尾

## Scope

### In Scope

- 冻结并复述当前 baseline 定义
- 实现或启用双周换仓模式
- 用双周换仓重跑 admission 所需评估
- 输出 baseline vs biweekly 的并排对照
- 更新正式 admission decision

### Out Of Scope

- 新因子研究
- 止损参数复试
- 持股数从 100 改到其他值
- 新增风险控制开关
- Phase 5 运行链路联调

## Baseline Freeze

除换仓频率外，以下参数必须与当前 canonical baseline 完全一致：

- 因子集：`team_coin + low_vol_20d + cgo_simple + enhanced_mom_60 + bp`
- 择时：多数投票制
- 口径：`lag1`
- 持股数：`100`
- 成本模型：保持 baseline 当前设定
- 股票池 / 过滤条件：保持 baseline 当前设定
- 不启用个股止损

## Ordered Workstreams

### WS1. Lock The Baseline Inputs

目标：确保本轮实验与当前 admission baseline 可直接比较。

必须完成：

- 引用当前 baseline 权威文档
- 明确脚本入口和数据前置条件
- 明确本轮未启用止损
- 明确双周换仓的实现方式与时间点定义

出口标准：

- 文档中清楚写明 baseline 与本轮 delta 的唯一区别
- 不需要人工猜测“这次到底改了什么”

### WS2. Implement Biweekly Rebalancing As The Only Delta

目标：仅修改换仓频率，不破坏其他策略口径。

必须完成：

- 在评估脚本或底层策略实现中增加双周换仓支持
- 明确定义“双周”
- 确认 lag1 规则在双周场景下仍成立
- 确认交易成本按实际换仓次数自然反映，不额外手调

出口标准：

- 可以明确运行“月频 baseline”与“双周版本”
- 双周版本除了换仓频率外无其他改动

### WS3. Re-Run The Full Admission Pack

目标：不要只看样本内年化，必须重跑完整准入材料。

至少重跑：

- 样本内
- 样本外
- walk-forward
- 年度表现
- 关键回撤诊断

至少输出：

- 年化收益
- 夏普比率
- 最大回撤
- 波动率
- 与 baseline 的 delta

出口标准：

- 存在 baseline vs biweekly 并排结果
- 不存在只挑有利指标汇报

### WS4. Write The New Admission Decision

目标：把本轮结果正式写入决议，而不是停留在实验记录。

必须明确：

- 双周换仓是否让策略通过 admission gate
- 若通过，进入 Phase 5 前必须启用哪些保护措施
- 若未通过，下一轮是否还有唯一允许入口

出口标准：

- 生成新的 `journal/strategy_admission_decision_*.md`
- 结论为 `ALLOW` 或 `DENY`

## Hard Constraints

### 1. No Hidden Delta

本轮除了换仓频率，不允许再变动任何策略维度。

### 2. Honest Evaluation Only

任何未明确标注 `lag1` 的结果，不得用于 admission 决策。

### 3. Stop-Loss Is Closed For This Round

本轮禁止把止损重新带回实验，避免双变量混淆。

### 4. Comparability First

双周结果必须能与当前 canonical baseline 直接比较；如果数据快照不同，必须明确标注差异，不得混写。

## Acceptance Commands

以下命令为参考验收入口；若脚本参数最终略有不同，必须在 journal 中说明实际命令。

```bash
python scripts/v6_admission_eval.py --output auto
python scripts/v6_admission_eval.py --biweekly --output auto
```

如需单独指定不启用止损，也必须明确写入命令与文档。

## Definition Of Done

Do not close this goal unless all are true:

- [ ] 当前 `v6(lag1)` baseline 已被明确引用且无歧义
- [ ] 双周换仓已作为唯一 delta 实现
- [ ] 样本内 / 样本外 / walk-forward 已完成重评估
- [ ] baseline vs biweekly 已形成并排对照
- [ ] 已形成新的正式 admission decision 文档
- [ ] 已明确 `ALLOW` 或 `DENY`
- [ ] 若 `ALLOW`，已写清 Phase 5 handoff 条件；若 `DENY`，已写清下一步唯一入口或明确暂停

## Artifacts

至少应产生或更新以下类型材料：

- `journal/v6_biweekly_eval_*.md`
- `journal/strategy_admission_decision_*.md`
- 必要时更新 `journal/v6_baseline_definition.md`
- 必要时更新 `WORKPLAN.md`

## Notes

这不是“继续优化直到过线”的开放式研究任务。
这是一轮严格受控的 admission retry：

- baseline 已锁定
- 单变量实验
- 完整重评估
- 二元决议

## Final Outcome

本 goal 已完成，其正式结论见：

- [strategy_admission_decision_v6_biweekly_20260326.md](/Users/karan/Documents/GitHub/quant-dojo/journal/strategy_admission_decision_v6_biweekly_20260326.md)

结果摘要：

- 双周换仓在样本内、样本外均明显劣化
- 三项硬性门槛全部未通过
- 该变动方向已被明确关闭
- `v6` 不再继续围绕双周换仓发起新一轮 retry

因此，本 goal 的当前含义仅为：

- 保存一次受控、诚实、单变量的 admission 评估记录
- 为仓库提供“停止继续 patch v6”的历史依据

## Status

### STATUS: CONVERGED
