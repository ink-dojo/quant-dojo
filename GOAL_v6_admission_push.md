# Goal: V6 Admission Push To Phase 5

> 执行型目标。当前日期：2026-03-25
> 定位：承接 `GOAL_strategy_validation_gate.md` 的后半段，不是新主线。
> 作用：把当前“v6 乐观口径已过线、保守口径只差一点”的状态，推进到“有一份可信保守基线 + 最小改动重评估 + 明确 admission decision”。

## Goal

把 `quant-dojo` 当前主策略从：

```text
研究结果看起来接近可用
但乐观/保守口径仍混在一起
```

推进到：

```text
保守基线被锁定
只做最小必要改动
重新评估后明确是否允许进入 Phase 5 模拟盘
```

这个 goal 不是为了继续无限优化策略。
这个 goal 只解决一个问题：

```text
v6(lag1) 到底能不能在诚实口径下过 admission gate？
```

## Why This Exists

截至 `2026-03-25`，仓库状态已经明显前进：

- 免费数据接入和 freshness 已基本收口
- 全因子库筛查、FM 检验、相关性去重、择时对比都已经完成
- `v6` 组合已经形成：
  - `team_coin`
  - `low_vol_20d`
  - `cgo_simple`
  - `enhanced_mom_60`
  - `bp`
- 月频场景下，多数投票择时已成为当前最佳候选

但当前还存在一个危险状态：

- 乐观口径（不延迟）已过 Phase 5 门槛
- 保守口径（lag1）仍差很小一步
- 文档、脚本、决策文件还没有完全锁定“以保守口径为准”

如果现在继续同时推进很多优化，会很容易出现：

- 又做出一批更漂亮但不可比较的新结果
- admission gate 重新变得模糊
- 工程团队开始围绕“快过线”的故事推进模拟盘

所以现在最重要的不是发散，而是收口。

## Non-Goals

以下内容明确不属于本 goal：

- 再新开多个正式策略 ID
- 大规模参数扫描平台
- 分钟线 / 北向 / 龙虎榜新数据扩展
- 组合优化器大重构
- Dashboard UI 重做
- 实盘接入
- 把所有历史研究材料一次性重写

## Single Primary Objective

用一份统一、诚实、可复现的保守评估基线，验证当前 `v6` 策略是否能通过 admission gate；如果不能，只允许做一个最小改动方向去重试。

## Decision Rule

从本 goal 开始，以下规则强制生效：

1. admission 判断默认只看 `lag1` 保守口径
2. 乐观口径可以保留，但只能作为对照，不得作为是否入模的主依据
3. 每轮只允许变动一个关键维度
4. 若本轮实验未过线，不得用“接近了”替代正式准入

## Scope

### In Scope

- 固化 `v6(lag1)` 为当前 admission baseline
- 统一策略评估脚本、报告、门禁文案的口径
- 选择一个最小改动方向并实施
- 重新跑样本内 / 样本外 / walk-forward
- 输出更新后的 admission decision
- 如果过线，给出进入 Phase 5 模拟盘前的保护措施清单

### Out Of Scope

- 同时并行推进止损、换仓频率、行业上限、MVO 等多项改动
- 引入大量新因子
- 重做因子研究框架
- 将策略直接推进到实盘

## Current Reality

基于当前 journal 和记要：

- `v6` 乐观口径：
  - 年化约 `15.4%`
  - 夏普约 `0.88`
  - 回撤约 `-19%`
  - 三项全过
- `v6(lag1)` 保守口径：
  - 年化约 `14.0%`
  - 夏普约 `0.77`
  - 回撤约 `-30.2%`
  - 三项都只差一点
- 样本外 `2025` 表现已明显改善
- 当前数据 freshness 已正常，已不是主阻塞项

这意味着：

- 当前问题不再是“有没有策略雏形”
- 当前问题是“能否把接近可用的候选，变成可批准的候选”

## Ordered Workstreams

### WS1. Freeze The Honest Baseline

目标：把 `v6(lag1)` 固化成唯一 admission baseline，防止研究口径继续漂移。

必须完成：

- 明确 `strategy_eval.py` 或等价主脚本中的默认评估口径
- 明确择时信号延迟规则
- 明确回测股票池、持股数、换仓频率、成本、过滤条件
- 明确哪些结果属于：
  - `optimistic`
  - `honest_baseline`

出口标准：

- 仓库里存在一份清楚写明的 baseline 定义
- 重新跑一次主脚本时，不需要靠人脑解释“这次是不是 lag1”
- journal 中 admission 判断与脚本默认口径一致

### WS2. Pick One Minimal Delta

目标：只选择一个最有希望跨线、且最不破坏可比性的改动。

优先顺序默认是：

1. 个股止损
2. 双周换仓
3. 行业上限微调

本轮严格限制：

- 只能选一个方向
- 不允许同时更改：
  - 因子集合
  - 择时方案
  - 持股数
  - 成本模型

出口标准：

- 在 goal / journal 中明确写出“本轮只改了什么”
- 存在清晰对照：`v6(lag1)` vs `v6 + one_delta`

### WS3. Re-Run The Full Admission Pack

目标：在最小改动后，重新跑完整 admission 所需结果，而不是只看一两个指标。

至少重跑：

- 样本内
- 样本外
- walk-forward
- 年度表现
- 关键回撤诊断

至少输出：

- 年化
- 夏普
- 最大回撤
- 胜率或稳定性摘要
- 与 baseline 的增减变化

出口标准：

- 新旧版本结果能并排比较
- 不存在“只挑对自己有利的窗口”

### WS4. Write The Admission Decision

目标：把这轮结果变成正式结论，而不是口头判断。

必须明确：

- 当前版本是否允许进入 Phase 5 模拟盘
- 如果允许，带哪些保护措施
- 如果不允许，还差哪一项指标
- 下一轮唯一允许尝试的改动是什么

出口标准：

- 形成新的 `journal/strategy_admission_decision_*.md`
- 结论是二元的：允许 / 不允许

### WS5. Prepare The Phase 5 Handoff

目标：只有在 admission 通过时，才把结果转交给 Phase 5。

必须准备：

- 进入模拟盘使用的正式策略版本说明
- 必须启用的保护措施：
  - lag1 保守执行
  - 风险监控
  - 运行频率
  - 人工批准点
- 下一步需要补齐的 Phase 5 工程项

出口标准：

- `WORKPLAN.md` 可以把主任务从“策略 admission”切回“Phase 5 模拟盘运行”
- 如果 admission 未通过，则不得进入本工作流

## Hard Constraints

### 1. Honest Baseline First

任何结果若不能确认属于 `lag1` 保守口径，不得用于 admission 决策。

### 2. One Change Per Round

每轮只允许一个主改动。禁止“止损 + 双周 + 行业上限 + 新因子”一起上。

### 3. No Fake Convergence

以下状态禁止视为完成：

- 乐观口径过线，但保守口径没过
- 样本内过线，但 walk-forward 明显退化
- 只写“差一点”但没有正式 admission decision

### 4. Preserve Comparability

所有重评估必须能与当前 `v6(lag1)` baseline 直接比较。

## Definition Of Done

Do not close this goal unless all are true:

- [x] `v6(lag1)` 已被明确固化为 admission baseline（`journal/v6_baseline_definition.md`）
- [x] 本轮只实施了一个最小改动方向（个股止损 -10%）
- [x] 新版本完成样本内 / 样本外 / walk-forward 重评估（`journal/v6_admission_eval_2026-03-25.md`）
- [x] 形成新的正式 admission decision 文档（`journal/strategy_admission_decision_v6_20260325.md`）
- [x] 已明确”允许进入 Phase 5”或”仍不允许”的二元结论（DENY）
- [x] 如果允许，已写清进入模拟盘时必须带的保护措施（N/A — DENY，下一步：双周换仓）

## Acceptance Commands

以下命令或等价脚本入口必须可运行：

```bash
python scripts/strategy_eval.py
python scripts/single_factor_gate.py
python -m pipeline.cli data status
python -m pytest -q tests/test_phase5_smoke.py
```

如果引入单独的 v6 admission 脚本，也必须补上等价入口并写进文档。

## Deliverables

至少产出：

```text
journal/strategy_eval_*.md
journal/strategy_admission_decision_*.md
journal/v6_admission_push_*.md
```

## Recommended Autoloop Boundary

推荐按 3 段跑，不要一把梭：

1. 固化 baseline + 对齐 admission 文案
2. 只做一个最小改动并重评估
3. 写决议并决定是否 handoff 到 Phase 5

## Relationship To Other Goals

- 承接 [GOAL_strategy_validation_gate.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_strategy_validation_gate.md)
- 如果通过，将结果移交 [GOAL_phase5_infra.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md)
- 不替代 `Phase 5 infra`
- 不替代长期策略研究主线
