# Goal: Phase 5 Paper Trading Readiness (2026-04-04)

## Goal

把 `quant-dojo` 当前状态从：

```text
v7 industry-neutral 已拿到 CONDITIONAL ALLOW
主链路组件基本存在
但 Phase 5 仍主要停留在“可以跑一次”而不是“可以连续运行并被信任”
```

推进到：

```text
v7 可以作为唯一 active strategy 进入 Phase 5 paper trading
signal -> rebalance -> positions/nav -> risk -> weekly report 成为可信闭环
重启、重复执行、无数据周、异常价格、风险预警等边界行为可解释
```

这不是新策略研究 goal，也不是 dashboard goal。
这是一个**把“条件允许”推进到“运营可用”**的执行型 goal。

## Why This Matters

- `v7` 已在 [`GOAL_v7_admission_full.md`](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v7_admission_full.md) 中拿到 `CONDITIONAL ALLOW`，如果不把 Phase 5 跑起来，这个 admission 结论没有运营价值。
- 当前仓库最缺的不是新因子，而是对 paper trading 链路的真实信任。
- 如果现在跳去做 dashboard 扩展或新策略研究，会把注意力从唯一已获准进入 Phase 5 的策略上移开。
- “能跑一遍”不等于“可连续运行”。如果 restart-safe、artifact、一致性、周报、回归验证不到位，后续任何收益结论都不可靠。

## Scope

### In Scope
- [ ] 把 `v7 industry-neutral` 明确接入并固定为当前 Phase 5 active strategy
- [ ] 跑通并加固 `signal -> rebalance -> positions/nav -> risk -> weekly report` 主链路
- [ ] 明确 paper trader 的重复执行、状态恢复、NAV 记录和交易记录语义
- [ ] 提升 weekly report 的审计价值，使其能作为每周运营 artifact
- [ ] 增加针对 Phase 5 主链路的最小 regression 验证
- [ ] 让当前 workplan / readme / active goal 描述与实际主线一致

### Out of Scope
- [ ] 新因子研究、新候选策略 admission、v8 方向探索
- [ ] 再次围绕 `v6` 做任何 retry
- [ ] 大规模 dashboard 视觉或交互开发
- [ ] 实盘接券商 API
- [ ] 多用户、云部署、任务调度系统
- [ ] “证明策略一定赚钱”

## Current Verified State

只记录当前已能从仓库文档或代码里确认的事实。

### Already Exists
- [x] `v7 industry-neutral` 已在 2026-04-03 获得 `CONDITIONAL ALLOW`，允许进入 Phase 5 paper trading，但需 Q2 复审 walk-forward
- [x] `pipeline.daily_signal.run_daily_pipeline()` 已存在，且 smoke test 已覆盖基础返回结构
- [x] `live.paper_trader.PaperTrader` 已存在，支持 `positions.json` / `trades.json` / `nav.csv`
- [x] `live.risk_monitor.check_risk_alerts()` 已存在，且已输出标准化风险字段
- [x] `pipeline.weekly_report.py` 已存在，能生成 Markdown 周报
- [x] CLI 命令树已存在：`signal run / rebalance run / risk check / report weekly / positions / performance / factor-health / data status`
- [x] 免费数据更新与 freshness 主线已基本收口，不再是当前唯一阻塞项

### Current Gaps
- [ ] 当前主策略虽已 admission allow，但尚未被正式定义为唯一 active paper-trading line
- [ ] `PaperTrader` 的 restart 语义、自一致性与重复执行语义还不够硬
- [ ] weekly report 更像“存在的文档输出”，还不够像“可审计的运营产物”
- [ ] 现有自动化验证以 smoke 为主，还未覆盖更真实的 Phase 5 失败模式
- [ ] workplan 已切到 Phase 5 paper trading，但 README 仍把 active subgoal 标成 free data ingestion，状态描述不完全一致

## Operational Outcome

当这个 goal 完成时，系统应该能做到：

- [ ] 把 `v7 industry-neutral` 作为当前唯一 active strategy，稳定生成某日信号并执行调仓
- [ ] 在进程重启后恢复持仓、现金、NAV 和记账状态，而不会出现明显漂移
- [ ] 在重复运行同一交易日时，行为明确、可预测、可解释
- [ ] 每周生成一份足够可信的运营周报，而不是仅有格式的 Markdown 文件
- [ ] 用一组明确的命令和测试，证明主链路没有被最近改动悄悄破坏

## Implementation Plan

### Phase A: Canonicalize The Active Phase-5 Line
- [ ] 新建或更新一处 canonical 说明，明确 `v7 industry-neutral` 是当前唯一 active paper-trading strategy
- [ ] 对齐 [`WORKPLAN.md`](/Users/karan/Documents/GitHub/quant-dojo/WORKPLAN.md)、[`README.md`](/Users/karan/Documents/GitHub/quant-dojo/README.md) 与本 goal 的状态陈述
- [ ] 明确本阶段不再围绕 `v6` 和新 candidate 做主线开发

### Phase B: Harden Paper-Trading State
- [ ] 收紧 `PaperTrader` 的恢复与自一致性逻辑
- [ ] 明确同日重复调仓、无 picks、价格缺失、nav 缺失等情形的语义
- [ ] 确保 CLI `positions` / `performance` 与持久化状态字段完全对齐

### Phase C: Make Weekly Review Operational
- [ ] 让 weekly report 明确展示本周调仓、期末持仓、周度 NAV、风险摘要、因子健康度、下周待确认事项
- [ ] 空周、无交易周、无风险周仍要生成“空但可读”的报告
- [ ] 明确 weekly report 和 live artifacts 的依赖契约

### Phase D: Raise Verification To Regression Grade
- [ ] 增加针对 `signal -> rebalance -> risk -> weekly report` 的最小端到端验证
- [ ] 为 `PaperTrader` 增加重复执行 / restart-safe / nav 防重的测试
- [ ] 为 weekly report 增加结构和内容级别的测试，而不是只验证返回类型

## File-Level Work

### Canonical Status / Docs
- [ ] [README.md](/Users/karan/Documents/GitHub/quant-dojo/README.md)
  - 把 active subgoal 和当前主线描述从 “free data ingestion” 更新到 “Phase 5 paper trading readiness / v7 active line”
- [ ] [WORKPLAN.md](/Users/karan/Documents/GitHub/quant-dojo/WORKPLAN.md)
  - 若当前 active stack 与本 goal 不一致，补充这一 goal 在 Phase 5 中的位置
- [ ] [GOAL_v7_admission_full.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_v7_admission_full.md)
  - 如有必要，仅加一小段 forward pointer，说明 post-admission 的唯一下一步是本 goal

### Runtime / Execution
- [ ] [pipeline/daily_signal.py](/Users/karan/Documents/GitHub/quant-dojo/pipeline/daily_signal.py)
  - 检查 active strategy / factor snapshot / metadata 是否足够支撑后续审计
- [ ] [pipeline/cli.py](/Users/karan/Documents/GitHub/quant-dojo/pipeline/cli.py)
  - 对齐 `signal / rebalance / report weekly / positions / performance` 的帮助文本与真实语义
- [ ] [live/paper_trader.py](/Users/karan/Documents/GitHub/quant-dojo/live/paper_trader.py)
  - 收紧状态恢复、NAV 防重、重复执行、调仓摘要和自一致性校验
- [ ] [live/risk_monitor.py](/Users/karan/Documents/GitHub/quant-dojo/live/risk_monitor.py)
  - 确认输出结构稳定，并让 skipped / info 项目在 weekly report 中可消费

### Weekly Ops Artifact
- [ ] [pipeline/weekly_report.py](/Users/karan/Documents/GitHub/quant-dojo/pipeline/weekly_report.py)
  - 提升周报的结构完整性和审计价值
- [ ] [journal/weekly/](/Users/karan/Documents/GitHub/quant-dojo/journal/weekly)
  - 以真实生成的周报为基准，验证输出格式可读、可重复、可对账

### Tests
- [ ] [tests/test_phase5_smoke.py](/Users/karan/Documents/GitHub/quant-dojo/tests/test_phase5_smoke.py)
  - 从 smoke 提升对 weekly report / trader state / risk structure 的断言强度
- [ ] [tests/test_control_plane.py](/Users/karan/Documents/GitHub/quant-dojo/tests/test_control_plane.py)
  - 保持 control plane 契约稳定
- [ ] [tests/test_e2e_control_plane.py](/Users/karan/Documents/GitHub/quant-dojo/tests/test_e2e_control_plane.py)
  - 保持 execute -> store -> dashboard 这条契约不回归
- [ ] 新增一个 focused Phase 5 regression test 文件
  - 覆盖同日重复调仓、状态恢复、周报生成、风险摘要消费

## Definition Of Done

Do not close this goal unless all are true:

- [ ] `v7 industry-neutral` 已被正式定义为当前唯一 active paper-trading strategy
- [ ] `signal -> rebalance -> positions/nav -> risk -> weekly report` 端到端可运行
- [ ] `PaperTrader` 的 restart 和重复执行语义明确且经测试验证
- [ ] 周报不只是“能生成”，而是具备最小运营审计价值
- [ ] 至少一组针对 Phase 5 主链路的 regression tests 成功
- [ ] README / WORKPLAN / 相关 active-goal 说明与当前系统现实一致
- [ ] 本 goal 文件反映最终验证后的真实状态

## Exit Gates

`STATUS: CONVERGED` is allowed only if all of the following are true:

- [ ] 没有未记录的 scoped P0/P1 运行风险
- [ ] 验证命令和相关测试已成功
- [ ] active strategy、运行产物、状态恢复语义都可以清楚解释
- [ ] 任何残余风险都被明确写下并有 intentional forward path

如果任何一项没过，不要写 `CONVERGED`。

## Must-Pass Commands

这些命令是最小必过集合；如果某条命令不适用于当前环境，必须说明原因并给出替代。

```bash
python -m compileall /Users/karan/Documents/GitHub/quant-dojo
python -m pytest -q /Users/karan/Documents/GitHub/quant-dojo/tests/test_phase5_smoke.py
python -m pytest -q /Users/karan/Documents/GitHub/quant-dojo/tests/test_control_plane.py
python -m pytest -q /Users/karan/Documents/GitHub/quant-dojo/tests/test_e2e_control_plane.py
python -m pipeline.cli --help
```

## Manual Verification

- [ ] 以本地代表性日期运行一次 `signal run`
- [ ] 使用生成的 picks 和价格运行一次 `rebalance run`
- [ ] 检查 `positions.json`、`trades.json`、`nav.csv` 是否自洽
- [ ] 重启后重新读取 `positions` / `performance`，确认状态稳定
- [ ] 生成一份 weekly report，核对调仓、NAV、风险摘要、因子健康度摘要是否对得上
- [ ] 如当周无交易或无风险，也验证报告仍然可读

## Risks To Watch

- [ ] README / workplan / goal 状态继续分叉，导致 autoloop 走错主线
- [ ] 以 smoke test 通过替代真正的 paper-trading state integrity
- [ ] `PaperTrader` 表面能跑，但重复执行和恢复语义不稳定
- [ ] weekly report 只是“格式完整”，但并不能作为运营复盘 artifact
- [ ] CLI 帮助文本与真实行为不一致，误导后续 agent 或操作者

## Self-Review Checklist

Before marking done, the agent must verify:

- [ ] 本 goal 解决的是运营可信度，而不是代码洁癖
- [ ] active strategy 的定义没有含糊空间
- [ ] 测试覆盖了这个 goal 真正要修的失败模式
- [ ] 文档和 workplan 没有继续停留在旧状态
- [ ] 这个 goal 完成后，下一步自然衔接的是“连续模拟盘运行”，而不是再补基础 correctness

## If Not Converged

如果必须停下，必须写回：

- current status
- exact blocker
- what was verified
- what remains
- next highest-value step

不要停在“还需要继续观察”这种空话上。

## Status

### STATUS: ACTIVE
