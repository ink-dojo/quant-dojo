# Goal: Phase 5 Free Data Ingestion And Freshness

> 执行型子目标。隶属于 `GOAL_phase5_infra.md`，不是新的主线。当前日期：2026-03-24

## Goal

把 `quant-dojo` 当前“依赖本地 CSV，但没有稳定免费更新路径”的状态，推进到“可用免费数据源做日线更新，并把 freshness 明确暴露给 CLI / Dashboard / control plane”。

这个 goal 的重点不是做完所有 Phase 5。
它只解决一个关键瓶颈：

```text
免费数据接入 → 本地落盘 → freshness 检查 → signal/risk/report 可依赖最新数据运行
```

## Why This Exists

当前仓库已经有：

- 本地数据加载能力
- `pipeline.data_checker.check_data_freshness()`
- CLI / Dashboard / control surface 对 freshness 的消费

但当前系统仍然缺一条可依赖的免费更新路径：

- 本地数据停在 `2026-03-20`
- CLI 已经能报警，但不能自己解释“怎么把数据补到今天”
- Phase 5 的 `signal -> rebalance -> risk -> weekly report` 可信度，依赖最新数据

如果继续在 `GOAL_phase5_infra.md` 里泛泛推进，很容易出现：

- freshness 一直是 warning，但没人真正接上数据源
- data checker 只是“看旧目录”而不是“管理一个更新契约”
- 后续周报/风险/信号链路看起来能跑，实际上只是跑旧数据

所以这个问题值得拆成一个独立执行 goal。

## Scope

### In Scope

- 选择一个不花钱、能在本机场景稳定使用的 A 股日线数据方案
- 设计统一数据 provider 契约，避免未来被单一免费源绑死
- 落地第一版免费 provider
- 把数据更新命令接进 CLI
- 让 `data_checker` / Dashboard / control surface 对“最新数据状态”输出一致
- 让 signal/risk 等主链路能依赖这套本地更新后的数据目录

### Out Of Scope

- 分钟级数据
- L2 / 逐笔 / 高级行情
- 付费数据源采购
- 真正的生产级调度系统
- 云部署、多用户、数据库
- 一次性把所有历史研究数据全部重建

## Primary Decision

第一版默认方案：

- **Primary provider: `AkShare`**
- 目标数据：A 股日线 EOD
- 落盘格式：与仓库当前本地 CSV 加载路径兼容，优先少改上层逻辑

保留抽象层，允许后续加：

- `TushareProvider`
- `BaoStockProvider`

但本 goal 不要求在第一版同时实现多个 provider。

## Success Criteria

这个 goal 只有在以下条件同时成立时才算完成：

- 能通过一个明确命令更新本地 A 股日线数据
- 更新结果写入统一目录，不要求手工搬文件
- `check_data_freshness()` 能基于真实更新结果输出稳定字段
- CLI、Dashboard、control surface 看到的是同一份 freshness 结果
- 指定日期信号生成可以依赖更新后的数据运行
- 数据缺失、更新失败、源端异常时，会显式失败，而不是静默成功

## Design Constraints

### 1. Free First, But Not Source-Locked

免费源可以不完美，但代码结构不能写成“AkShare 到处直连”。

至少需要一个薄抽象，例如：

- `providers/base.py`
- `providers/akshare_provider.py`
- `pipeline/data_update.py`

### 2. Freshness Is A Contract, Not A Side Effect

必须统一输出以下字段：

- `latest_date`
- `days_stale`
- `missing_symbols`
- `status`

禁止不同入口各算各的。

### 3. Updater Must Be Explicit

必须有一个正式入口，例如：

- `python -m pipeline.cli data update`

而不是靠 notebook 或一次性脚本。

### 4. Existing Local Data Must Not Be Needlessly Broken

如果仓库当前大量逻辑依赖本地 CSV 结构，第一版应优先兼容现有格式。

目标是：

- 先把更新链路接上
- 再考虑后续是否迁移目录布局或缓存格式

## Deliverables

### D1. Provider Contract

新增统一数据 provider 接口，至少支持：

- 获取股票列表
- 获取单只股票日线历史
- 增量更新指定股票到某个截止日

建议返回统一字段：

- `symbol`
- `date`
- `open`
- `high`
- `low`
- `close`
- `volume`
- `amount`（若源端可得）

### D2. AkShare Provider

第一版实现 `AkShareProvider`：

- 支持拉取 A 股股票列表
- 支持按股票抓取日线
- 支持全量初始化或增量更新
- 对源端失败有明确异常信息

### D3. Local Storage Update Path

新增正式更新入口，例如：

- `pipeline/data_update.py`

要求：

- 支持更新全部或部分 symbol
- 支持指定 `--end-date`
- 支持 dry-run 或至少清晰日志
- 不在失败时写半成品或损坏旧文件

### D4. CLI Integration

`pipeline.cli` 新增数据命令组，至少包含：

- `data status`
- `data update`

如果已有 `doctor` / `risk-check` / `signal` 使用 freshness warning，需要继续复用同一实现。

### D5. Freshness / Missingness Hardening

`pipeline.data_checker` 需要从“扫描旧目录”升级到“消费更新契约后的目录”。

必须明确：

- 什么叫 `ok`
- 什么叫 `stale`
- 什么叫 `missing`
- `missing_symbols` 的口径是什么

### D6. Minimal Verification

至少补 3 组自动化验证：

- provider 返回字段与本地落盘格式
- 更新后 freshness 状态变化
- CLI `data status` / `data update` 的最小 smoke test

## Ordered Work Plan

### WS1. Confirm Storage Contract

先确认当前仓库本地 CSV 实际依赖的目录结构与字段口径。

出口标准：

- 写清楚当前 loader 期待的格式
- 明确第一版 updater 是“兼容旧格式”还是“迁移到新格式并顺手兼容”

### WS2. Add Provider Abstraction

新增 provider 层，不直接把 AkShare 调用散落到 CLI / checker / signal 里。

出口标准：

- provider contract 存在
- `AkShareProvider` 可单独测试

### WS3. Implement Update Path

实现本地数据更新主路径。

出口标准：

- 可以跑一次更新命令
- 文件写入成功
- 失败时不污染已有数据

### WS4. Integrate Freshness Consumers

把更新结果接回：

- `pipeline.data_checker`
- `pipeline.cli`
- `pipeline.control_surface`
- dashboard data status

出口标准：

- 所有入口返回同一 freshness 结果

### WS5. Verification

跑 smoke tests，并验证 signal 至少能在更新后的某个交易日执行。

出口标准：

- CLI 验证通过
- 自动化测试通过

## Definition Of Done

Do not close this goal unless all are true:

- [x] 本地存在一个正式的免费数据更新入口
- [x] 第一版免费 provider 已接入且可运行
- [x] freshness 字段口径被统一
- [x] CLI / Dashboard / control surface 看到同一 freshness 结果
- [x] 至少一个交易日的 signal 能基于更新后的数据成功运行
- [x] 自动化测试覆盖 provider / freshness / CLI smoke
- [x] 文档写清楚如何首次初始化和日常更新

## Acceptance Commands

以下命令必须全部通过，才算本 goal 完成：

```bash
python -m pipeline.cli data status
python -m pipeline.cli data update --help
python -m pipeline.cli data update --end-date 2026-03-24
python -m pipeline.cli data status
python -m pipeline.cli signal --date 2026-03-24
python -m pytest -q tests/test_data_update.py
python -m pytest -q tests/test_data_checker.py
```

如果 `2026-03-24` 不是交易日，则替换为更新后目录中的最新交易日。

## Risks To Watch

- 免费源字段口径和现有 CSV 口径不一致
- 免费源限流或偶发失败，导致 updater 不稳定
- 现有 loader 依赖隐含字段，更新后才暴露问题
- 只更新了 freshness，却没真正打通 signal 主链路

## Relationship To Phase 5

这个 goal 完成后，`GOAL_phase5_infra.md` 会直接受益于：

- WS1 Runtime Configuration
- WS2 Daily Signal Pipeline Hardening
- WS4 Risk And Health Monitoring
- WS6 Verification And Operator UX

所以它是 **Phase 5 的子目标**，不是新的独立方向。

## Status

- `ACTIVE`: 正在执行
- `BLOCKED`: 被具体数据源限制、字段兼容问题、或本地目录契约冲突阻塞
- `CONVERGED`: 免费数据更新路径、freshness 契约、signal 链路和测试全部验证完成

**当前状态：`ACTIVE`**
