# Goal: Strategy Validation Gate Before Phase 5

> 执行型目标。当前日期：2026-03-24
> 作用：在继续推进模拟盘基础设施之前，先判断当前主策略是否具备进入 Phase 5 的资格。

## Goal

把 `quant-dojo` 当前“有研究结果，但策略真实性和可交易性尚未被严谨验证”的状态，推进到“有一套可信、可复现、可比较的策略验证门禁”。

这个 goal 不是为了马上把策略调到赚钱。
这个 goal 是为了先回答：

```text
当前主策略到底是不成熟，还是根本不值得进入模拟盘主链路？
```

## Why This Exists

根据 `journal/session_report_20260324.md` 和 `journal/strategy_eval_20260324.md`：

- 当前 `multi_factor` 在真实数据下表现远弱于此前 notebook 的合成数据结果
- 当前结论已经足够强，足以否定“直接进入 Phase 5 模拟盘”
- 但当前研究回测仍然偏粗糙，尚未加入最小可交易约束和统一验证门禁

这意味着：

- 现在不能把策略当成“已经通过”
- 也不能仅凭一轮粗研究，就永久判死刑

继续推进 Phase 5 infra 而不先加策略验证门禁，会导致：

- 工程链路越来越完整
- 但基础 alpha 仍然可能是伪信号
- 最终得到的是“运行得很稳定的坏策略”

## Non-Goal

以下内容不属于本 goal：

- 真实券商接入
- 自动化调度
- 云部署
- dashboard UI 重构
- control plane 架构扩展
- 一次性研究十几个新因子

## Primary Objective

建立一套**策略入模门禁**：

- 研究脚本输出必须可信
- 单因子有效性必须先被确认
- 组合策略必须在“最小可交易约束”下复核
- 未达标策略不得进入 Phase 5 模拟盘主链路

## Scope

### In Scope

- 修正现有评估脚本中的统计/方法问题
- 统一 notebook 与脚本的真实数据口径
- 建立单因子验证流程
- 加入最小可交易约束后的组合回测
- 明确“可进入模拟盘 / 不可进入模拟盘”的门槛
- 产出标准化结论文档

### Out Of Scope

- 多策略组合优化
- 实盘资金管理
- 高频/分钟级回测
- 大规模参数搜索平台
- 因子自动发现

## Current Known Problems

### 已知问题 1：历史 notebook 结果存在合成数据假象

`12_strategy_report.ipynb` 曾在真实数据失败后回退到合成数据，导致：

- 年化收益、夏普、回撤等结果被误读
- notebook 结论不能直接作为策略真实性依据

### 已知问题 2：评估脚本口径仍不够硬

`scripts/strategy_eval.py` 已经比 notebook 更可信，但仍存在风险：

- 统计项需进一步校验
- 尚未完全纳入最小可交易约束
- 研究回测口径与未来模拟盘执行口径还未完全统一

### 已知问题 3：当前主策略尚未达到 Phase 5 门槛

当前结论应视为：

- **不得进入模拟盘**
- 需要先走验证门禁，再决定继续救还是砍

## Ordered Workstreams

### WS1. Fix The Evaluation Baseline

目标：把 `scripts/strategy_eval.py` 变成可信的研究基线，而不是“一次性分析脚本”。

必须完成：

- 修正明显统计错误
- 固化输出字段
- 明确配置来源
- 统一 benchmark、成本、调仓、股票池口径

出口标准：

- 同一输入重复运行结果稳定一致
- 报告中的每个指标都可解释来源

### WS2. Add Minimum Tradability Constraints

目标：在研究回测中加入最低限度的可交易约束，避免垃圾票或极端小票污染结果。

至少要加入：

- ST 过滤
- 最小上市天数
- 最低价格
- 最低流动性 / 成交额
- 最大单票权重
- 最大行业暴露

出口标准：

- 能对比“无约束” vs “最小可交易约束”
- 明确哪些约束改变了结果

### WS3. Single-Factor Gate

目标：先确认每个候选因子本身是否值得进入组合。

每个候选因子必须输出：

- IC 均值
- ICIR
- 分层收益
- 压力期表现
- 样本外表现
- 保留 / 观察 / 剔除结论

优先验证：

1. `reversal_1m`
2. `low_vol_20d`
3. `turnover_rev`
4. `momentum_12_1`

后续可加：

- `value`
- `quality`

出口标准：

- 每个候选因子都有明确结论
- 不再把“未经验证的因子”直接送进组合

### WS4. One Hard Candidate Portfolio

目标：只保留一个最强候选组合进行复核，不同时推进多个半成品组合。

第一优先候选：

- `reversal + low_vol + turnover`

默认不带：

- `momentum_12_1`

验证方式：

- 样本内
- 样本外
- walk-forward

出口标准：

- 得到一个清晰结论：值得继续 / 暂缓 / 砍掉

### WS5. Admission Decision

目标：把结果转成明确门禁，而不是停留在“感觉还行/不太行”。

必须明确写出：

- 是否允许进入 Phase 5 模拟盘
- 如果不允许，还差什么
- 如果允许，进入模拟盘时必须带哪些保护措施

出口标准：

- 有一份正式 admission decision 文档

## Definition Of Done

Do not close this goal unless all are true:

- [x] `scripts/strategy_eval.py` 已被修正为可信评估基线
- [x] notebook 与脚本不再依赖合成数据假象
- [x] 至少 4 个候选因子完成单因子门禁验证
- [x] 最小可交易约束已接入组合回测
- [x] 只保留一个候选组合完成样本内 / 样本外 / walk-forward 复核
- [x] 形成明确的”允许 / 不允许进入 Phase 5”结论
- [x] 结论文档已写清楚，不留模糊空间

## Acceptance Commands

以下命令或等价脚本入口必须可运行：

```bash
python scripts/strategy_eval.py
python -m pytest -q tests/test_notebook_compat.py
python -m pytest -q tests
```

并产出至少以下文档或等价产物：

```text
journal/strategy_eval_*.md
journal/strategy_admission_decision_*.md
```

## Hard Gate

在本 goal 完成之前，以下行为默认禁止：

- 把当前主策略当成“已达标策略”推进到 Phase 5 模拟盘
- 用 notebook 的历史合成数据结果作为策略优劣依据
- 同时新增多个正式策略 ID 进入 control plane

## Relationship To Other Goals

- 与 `GOAL_phase5_infra.md` 并行存在，但逻辑上先于“策略进入模拟盘”这一步
- 不替代 `GOAL_phase5_infra.md`
- 不改变 `WORKPLAN.md` 的总主线优先级

更准确地说：

- `Phase 5 infra` 解决“能不能稳定运行”
- 本 goal 解决“值不值得让这个策略进入稳定运行”

## Status

- `ACTIVE`: 正在执行验证门禁
- `BLOCKED`: 被数据口径、研究回测实现、或方法冲突阻塞
- `CONVERGED`: 已完成门禁验证，得出清晰 admission decision

**当前状态：`CONVERGED`**
