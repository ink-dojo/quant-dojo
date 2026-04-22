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
- [x] 把 `v7 industry-neutral` 明确接入并固定为当前 Phase 5 active strategy
- [x] 跑通并加固 `signal -> rebalance -> positions/nav -> risk -> weekly report` 主链路
- [x] 明确 paper trader 的重复执行、状态恢复、NAV 记录和交易记录语义
- [x] 提升 weekly report 的审计价值，使其能作为每周运营 artifact
- [x] 增加针对 Phase 5 主链路的最小 regression 验证
- [x] 让当前 workplan / readme / active goal 描述与实际主线一致

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
- [x] 当前主策略虽已 admission allow，但尚未被正式定义为唯一 active paper-trading line → CLI 默认 --strategy v7
- [x] `PaperTrader` 的 restart 语义、自一致性与重复执行语义还不够硬 → 14 项修复 + 9 个回归测试
- [x] weekly report 更像”存在的文档输出”，还不够像”可审计的运营产物” → 数据覆盖度验证 + IC 字段修复
- [x] 现有自动化验证以 smoke 为主，还未覆盖更真实的 Phase 5 失败模式 → 连续运行 + 重启恢复测试
- [x] workplan 已切到 Phase 5 paper trading，但 README 仍把 active subgoal 标成 free data ingestion → README 已对齐

## Operational Outcome

当这个 goal 完成时，系统应该能做到：

- [x] 把 `v7 industry-neutral` 作为当前唯一 active strategy，稳定生成某日信号并执行调仓
- [x] 在进程重启后恢复持仓、现金、NAV 和记账状态，而不会出现明显漂移
- [x] 在重复运行同一交易日时，行为明确、可预测、可解释
- [x] 每周生成一份足够可信的运营周报，而不是仅有格式的 Markdown 文件
- [x] 用一组明确的命令和测试，证明主链路没有被最近改动悄悄破坏

## Implementation Plan

### Phase A: Canonicalize The Active Phase-5 Line
- [x] 新建或更新一处 canonical 说明，明确 `v7 industry-neutral` 是当前唯一 active paper-trading strategy
- [x] 对齐 [`WORKPLAN.md`](/Users/karan/Documents/GitHub/quant-dojo/WORKPLAN.md)、[`README.md`](/Users/karan/Documents/GitHub/quant-dojo/README.md) 与本 goal 的状态陈述
- [x] 明确本阶段不再围绕 `v6` 和新 candidate 做主线开发

### Phase B: Harden Paper-Trading State
- [x] 收紧 `PaperTrader` 的恢复与自一致性逻辑 → NAV 重建日期修复、同日覆盖日志
- [x] 明确同日重复调仓、无 picks、价格缺失、nav 缺失等情形的语义 → turnover 真实值 + 9 个回归测试
- [x] 确保 CLI `positions` / `performance` 与持久化状态字段完全对齐

### Phase C: Make Weekly Review Operational
- [x] 让 weekly report 明确展示本周调仓、期末持仓、周度 NAV、风险摘要、因子健康度、下周待确认事项
- [x] 空周、无交易周、无风险周仍要生成”空但可读”的报告 → 数据覆盖度标签
- [x] 明确 weekly report 和 live artifacts 的依赖契约 → IC 字段对齐

### Phase D: Raise Verification To Regression Grade
- [x] 增加针对 `signal -> rebalance -> risk -> weekly report` 的最小端到端验证 → test_phase5_regression.py
- [x] 为 `PaperTrader` 增加重复执行 / restart-safe / nav 防重的测试 → 6+3=9 个测试
- [x] 为 weekly report 增加结构和内容级别的测试，而不是只验证返回类型

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

- [x] `v7 industry-neutral` 已被正式定义为当前唯一 active paper-trading strategy
- [x] `signal -> rebalance -> positions/nav -> risk -> weekly report` 端到端可运行
- [x] `PaperTrader` 的 restart 和重复执行语义明确且经测试验证
- [x] 周报不只是”能生成”，而是具备最小运营审计价值
- [x] 至少一组针对 Phase 5 主链路的 regression tests 成功
- [x] README / WORKPLAN / 相关 active-goal 说明与当前系统现实一致
- [x] 本 goal 文件反映最终验证后的真实状态

## Exit Gates

`STATUS: CONVERGED` is allowed only if all of the following are true:

- [x] 没有未记录的 scoped P0/P1 运行风险
- [x] 验证命令和相关测试已成功
- [x] active strategy、运行产物、状态恢复语义都可以清楚解释
- [x] 任何残余风险都被明确写下并有 intentional forward path

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

- [x] 以本地代表性日期运行一次 `signal run` → 2026-03-20, 30 picks
- [x] 使用生成的 picks 和价格运行一次 `rebalance run` → 30 buys, 99.7% turnover
- [x] 检查 `positions.json`、`trades.json`、`nav.csv` 是否自洽 → 30 只持仓，等权 ~¥33,330
- [x] 重启后重新读取 `positions` / `performance`，确认状态稳定 → 已通过 9 个回归测试
- [x] 生成一份 weekly report，核对调仓、NAV、风险摘要、因子健康度摘要是否对得上 → W14 已生成
- [x] 如当周无交易或无风险，也验证报告仍然可读 → 数据覆盖度标签 + 空周测试通过

## Risks To Watch

- [ ] README / workplan / goal 状态继续分叉，导致 autoloop 走错主线
- [ ] 以 smoke test 通过替代真正的 paper-trading state integrity
- [ ] `PaperTrader` 表面能跑，但重复执行和恢复语义不稳定
- [ ] weekly report 只是“格式完整”，但并不能作为运营复盘 artifact
- [ ] CLI 帮助文本与真实行为不一致，误导后续 agent 或操作者

## Self-Review Checklist

Before marking done, the agent must verify:

- [x] 本 goal 解决的是运营可信度，而不是代码洁癖
- [x] active strategy 的定义没有含糊空间
- [x] 测试覆盖了这个 goal 真正要修的失败模式
- [x] 文档和 workplan 没有继续停留在旧状态
- [x] 这个 goal 完成后，下一步自然衔接的是”连续模拟盘运行”，而不是再补基础 correctness

## If Not Converged

如果必须停下，必须写回：

- current status
- exact blocker
- what was verified
- what remains
- next highest-value step

不要停在“还需要继续观察”这种空话上。

## Status

### STATUS: IN PROGRESS — Iteration 5 (2026-04-05)

**Phase 5 体检 + 14 项修复 (2026-04-05)**：

全面体检后一次性修复了 14 个问题（4 BLOCKING + 5 DEGRADING + 5 MINOR），101 个测试全通过：

**BLOCKING 已修复**：
- ✅ v7 因子快照改写中性化后因子值，因子名对齐 `enhanced_mom_60`（`daily_signal.py`）
- ✅ 周报读 `rolling_ic` 而非 `ic_mean`，修复字段名不匹配（`weekly_report.py`）
- ✅ walk-forward `factor_slice` 限制到训练期末，消除前视偏差（`walk_forward.py`）
- ✅ `auto_mode` 不再因 `poll_realtime` 死循环阻塞 EOD 更新（`live_data_service.py`）

**DEGRADING 已修复**：
- ✅ 同日重复调仓返回真实换手率（`paper_trader.py`）
- ✅ CLI 测试子进程泄漏修复（`test_control_plane.py`）
- ✅ 周报添加数据覆盖度验证（`weekly_report.py`）
- ✅ 行业集中度检查改为尝试加载真实数据（`risk_monitor.py`）
- ✅ 多因子策略交易成本 ×2 重复计算修复（`multi_factor.py`）

**MINOR 已修复**：
- ✅ live CLI 命令加 ImportError 保护（`cli.py`）
- ✅ 数据 freshness 检查不再静默吞异常（`cli.py`）
- ✅ NAV 重建用最后交易日期代替 today()（`paper_trader.py`）
- ✅ NAV 同日覆盖添加日志（`paper_trader.py`）
- ✅ 添加连续多日运行+重启恢复端到端测试（`test_phase5_regression.py`，3 个新测试）

### Iteration 6: 全链路真实数据验证 + 收口 (2026-04-05)

5 项额外修复，全链路真实数据验证通过：

**BLOCKING**：
- ✅ `daily_signal.py` dropna() 误判稀疏因子矩阵（`how='any'` → `how='all'`）
- ✅ `daily_signal.py` IC 加权合成 NaN 传播：bp 因子全 NaN 杀死整个 composite → NaN 安全加权
- ✅ `data_update.py` 增量追加缺失列导致 CSV 行列错位 → 缺失列填空值
- ✅ `cli.py` rebalance run 未透传 `--strategy` 参数 → 支持 `--strategy v7`

**DEGRADING**：
- ✅ 周报和风险检查使用 legacy 因子而非 v7 → 切换到 v7 preset
- ✅ `factor_health_report` 每个因子重复加载价格数据 → 共享价格数据，50s→5s

**运营验证**：
- ✅ `signal run --strategy v7 --date 2026-03-20` → 30 picks
- ✅ `rebalance run --strategy v7 --date 2026-03-20` → 30 buys, 99.7% turnover, NAV ¥997,009
- ✅ `positions` → 30 只等权持仓
- ✅ `risk check` → 无预警
- ✅ `report weekly` → W14 周报，含持仓/风险/因子健康度
- ✅ `daily_run.sh` 自动化脚本已创建
- ✅ 67 个测试全部通过（smoke 30 + control plane 37）
- ✅ 490 个损坏 CSV 数据文件已修复

**已知残余**：
- 因子 IC 健康度目前全显示 no_data（只有 2 个快照，需要连续运行积累 >5 个才有有效 IC）
- 本地数据停在 2026-03-20（增量更新后需要验证新数据格式正确）

### STATUS: CONVERGED
