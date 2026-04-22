# GOAL — quant-dojo Phase 5 Infrastructure Execution Plan

> 给 `/autoloop` 的可执行工作计划。当前日期：2026-03-22
>
> 当前 active subgoal：
> [`GOAL_phase5_free_data_ingestion.md`](/Users/karan/Documents/GitHub/quant-dojo/GOAL_phase5_free_data_ingestion.md)
> 说明：免费最新数据接入与 freshness 契约收口，是当前 Phase 5 的优先切入点。

---

## 1. Mission

把 `quant-dojo` 从“研究与回测仓库”推进到“可连续运行的模拟盘基础设施”。

本阶段不是做更多因子研究，也不是做正式实盘系统。
本阶段的唯一目标是建立一条可信的闭环：

```text
本地数据 → 每日信号 → 调仓执行 → 持仓/NAV记录 → 风险检查 → 周报复盘
```

完成后，单人操作者应能在本机稳定运行该流程，并对结果具备基本信任。

---

## 2. Current Reality

### 已有能力
- 因子研究与策略框架已存在：`research/`、`strategies/`、`backtest/`
- 多因子策略已实现：`strategies/multi_factor.py`
- 本地 CSV 数据加载已存在：`utils/local_data_loader.py`
- 模拟盘、风险监控、信号管道、CLI、Dashboard 已有初版
- 本轮 review 已修复的关键问题：
  - `BacktestEngine` 与 `MultiFactorStrategy` 返回列不兼容
  - `PaperTrader.rebalance()` 未真正再平衡保留仓位
  - `risk_monitor` 未正确消费因子健康度状态
  - `factor_monitor` 依赖不存在的 `next_return`
  - `pipeline.cli rebalance` 未加载真实收盘价

### 仍然存在的核心短板
- 数据路径仍然硬编码到个人机器
- 免费最新数据更新路径缺失，freshness 只能报警，不能闭环修复
- 模拟盘状态恢复与 restart 安全性不足
- 自动化验证过弱，缺少回归测试
- 周报、数据新鲜度、风控阈值与执行路径还没有形成严格契约
- 当前系统可以“运行”，但还不足以称为“可信”

### Immediate Priority Inside Phase 5

在继续平均推进 WS1-WS6 之前，先收口一个执行型阻塞问题：

- 免费数据接入与 freshness 契约

执行文件：
- [GOAL_phase5_free_data_ingestion.md](/Users/karan/Documents/GitHub/quant-dojo/GOAL_phase5_free_data_ingestion.md)

原因：

- 当前 CLI 已报告本地数据停在旧交易日
- 没有正式更新入口，`signal -> risk -> weekly report` 只能依赖旧数据
- 这个问题会同时阻塞 WS2、WS4、WS5 和 WS6 的真实验收

---

## 3. Phase 5 Definition Of Done

Phase 5 基础设施完成的标准不是“文件都存在”，而是满足以下 6 条：

1. 能为任意交易日生成一份可复现的信号文件和因子快照。
2. 能基于该信号文件与当日价格，执行一次可追溯的模拟调仓。
3. 重启后可以恢复持仓、现金、交易记录与 NAV，不出现状态漂移。
4. 风险检查对真实运行状态有意义，不是空壳告警。
5. CLI 可以完成日常操作，不依赖手动改代码。
6. 有最小自动化验证，能防止 Phase 5 主路径再次被改坏。

---

## 4. Non-Goals

以下内容明确不属于本次目标：

- 不接真实券商 API
- 不做自动定时任务调度系统
- 不做云部署、多用户、权限、数据库
- 不重新设计因子研究框架
- 不做复杂前端重构
- 不追求“策略一定赚钱”，本阶段只追求工程闭环可信

---

## 5. Execution Principles

### 原则 1：配置优先于硬编码
- 不允许把核心运行依赖永久绑定到 `/Users/karan/Desktop/20260320`
- 必须提供默认值，但路径、阈值、股票数、调仓频率都应能配置

### 原则 2：文件产物必须可审计
- 每次生成信号、调仓、周报，都必须产出可回看文件
- 所有关键输出必须带日期

### 原则 3：失败必须显式
- 数据过旧、价格缺失、无可交易股票、因子无数据，这些都必须清楚报错或告警
- 禁止“悄悄返回空结果然后继续当成功”

### 原则 4：研究口径与模拟口径一致
- 模拟盘使用的选股、价格、交易成本、过滤规则，必须与研究/回测口径尽量一致
- 若有偏差，必须在文档里明确写出

### 原则 5：先可信，再自动化
- 先让手动命令链条稳定
- 再考虑 cron、自动触发、外部通知等增强项

---

## 6. Workstreams

本阶段拆成 6 个工作流，必须按顺序推进。

### WS1. Runtime Configuration

**目标：** 去掉个人机器路径耦合，让 Phase 5 可在任何本机环境复现。

**交付物：**
- `config/config.example.yaml` 补充 Phase 5 所需字段
- 新增统一配置读取模块，例如 `config/runtime.py` 或 `utils/runtime_config.py`
- 支持以下配置项：
  - `local_data_dir`
  - `signal_n_stocks`
  - `min_listing_days`
  - `min_price`
  - `transaction_cost_rate`
  - `drawdown_warning`
  - `drawdown_critical`
  - `concentration_limit`

**完成标准：**
- `utils/local_data_loader.py` 不再只依赖硬编码路径
- `pipeline/daily_signal.py`、`pipeline/data_checker.py`、`pipeline/cli.py` 可以从统一配置读取路径
- 默认配置仍能兼容当前本机环境

**禁止偷懒：**
- 不要在多个模块里各写一份默认路径
- 不要只加环境变量说明而不真正接线

---

### WS2. Daily Signal Pipeline Hardening

**目标：** 把 `pipeline/daily_signal.py` 变成“可重跑、可检查、可解释”的正式入口。

**当前基线：**
- 已能生成 `live/signals/{date}.json`
- 已能保存 `live/factor_snapshot/{date}.parquet`

**必须补齐：**
- 明确输入日期规则：
  - 若 `date is None`，取数据中最新交易日
  - 若指定日期不存在，返回明确错误，不默默降级
- 输出结构固定化：
  - `date`
  - `picks`
  - `scores`
  - `factor_values`
  - `excluded`
  - `metadata`
- `metadata` 至少包含：
  - `n_input_symbols`
  - `n_after_filters`
  - `config_snapshot`
  - `generated_at`

**文件要求：**
- `pipeline/__init__.py` 暴露 `run_daily_pipeline`
- 结果文件格式写入 `live/README.md`

**完成标准：**
- 同一个日期、同一份输入数据、同一配置，多次运行结果一致
- `python -m pipeline.cli signal --date YYYY-MM-DD` 成功时一定生成产物
- 失败时不写半成品文件

---

### WS3. Paper Trading State Integrity

**目标：** 让 `PaperTrader` 成为可信状态机，而不是“凑合记账器”。

**当前基线：**
- 已有 `positions.json` / `trades.json` / `nav.csv`
- 本轮已修复“未真正再平衡”的错误

**必须补齐：**
- 启动恢复逻辑：
  - 校验 `positions.json` 与 `nav.csv` 是否自洽
  - 明确现金恢复规则
  - 缺失文件时采用可预测初始化
- 交易记录标准化：
  - 每笔交易记录要有 `date / symbol / action / shares / price / cost`
- NAV 记录防重：
  - 同一日期重复调仓时，不能无限追加重复 NAV
  - 明确策略：覆盖当日 NAV 或拒绝重复执行
- 调仓结果摘要：
  - 返回一个结构化结果，例如：
    - `n_buys`
    - `n_sells`
    - `turnover`
    - `cash_after`
    - `nav_after`

**完成标准：**
- 同一天重复运行时行为明确、可预期
- 重启进程后再查询持仓和绩效，不应出现明显状态跳变
- `get_performance()` 指标字段与 CLI 展示字段完全一致

---

### WS4. Risk And Health Monitoring

**目标：** 让风险告警有真实信息价值。

**当前基线：**
- 回撤、集中度、因子健康度检查已存在
- 本轮已修复因子状态读取与 next-return 计算问题

**必须补齐：**
- 行业集中度检查：
  - 若无行业映射数据，返回 `skipped` 原因，而不是只写内部日志
- 风险结果标准化：
  - 每条告警统一字段：`level`, `code`, `msg`, `symbol`, `as_of_date`
- 价格异常检查：
  - 缺价格、零价格、明显无效价格需要单独提示
- 可选检查项与已跳过检查项分开输出

**因子健康度要求：**
- 监控因子名必须与 `daily_signal.py` 输出一致
- 如果本地价格不足以支持 lookback，状态应为 `no_data`，不是误判 `dead`

**完成标准：**
- `python -m pipeline.cli factor-health`
- `python -m pipeline.cli risk-check`
  这两个命令的输出字段和状态值稳定一致

---

### WS5. Weekly Review Artifact

**目标：** 让模拟盘形成“运行 -> 复盘 -> 修正”的最小闭环。

**交付物：**
- `pipeline/weekly_report.py`
- `journal/weekly/` 目录结构

**周报必须包含：**
1. 本周调仓记录
2. 周末持仓概览
3. 本周 NAV 表现
4. 本周风险预警摘要
5. 因子健康度摘要
6. 下周待确认事项

**注意：**
- 不要求自动预测“下周一定买什么”
- 不要伪造未来信息
- 周报本质是运营/复盘文档，不是研究报告

**完成标准：**
- `python -m pipeline.cli weekly-report --week YYYY-Www`
  成功生成 `journal/weekly/YYYY-Www.md`
- 无持仓、无信号、无风险时仍能生成“空但可读”的周报

---

### WS6. Verification And Operator UX

**目标：** 给操作者一个可靠的最小命令界面，并补上防回归验证。

**必须补齐：**
- `pipeline/cli.py` 的各命令帮助文本与实际行为对齐
- 关键模块增加最小 smoke tests
- 至少补 3 组自动化验证：
  - 数据加载/信号输出结构
  - `PaperTrader` 调仓与状态持久化
  - 风险/因子健康度接口返回结构

**测试优先级：**
- 先纯 Python 单元测试
- notebook 不作为主验证手段

**完成标准：**
- 存在可重复执行的测试入口
- 至少一个测试覆盖“生成信号 -> 调仓 -> 风险检查”主链路

---

## 7. Ordered Milestones

### Milestone A: 可配置运行底座
- [ ] 完成 WS1
- [ ] 调整 `live/README.md` 快速开始

**出口标准：**
- 新机器只需改配置，不需要改源码路径

### Milestone B: 可重复信号与调仓
- [ ] 完成 WS2
- [ ] 完成 WS3

**出口标准：**
- 能稳定完成一次 `signal -> rebalance -> positions -> performance`

### Milestone C: 有意义的风险与复盘
- [ ] 完成 WS4
- [ ] 完成 WS5

**出口标准：**
- 能产出本周风险状态和周报文档

### Milestone D: 可维护
- [ ] 完成 WS6

**出口标准：**
- 主链路有最小自动化验证，后续修改不容易再次破坏

---

## 8. File-Level Task List

### `utils/local_data_loader.py`
- [ ] 改为从统一配置读取 `local_data_dir`
- [ ] 保留默认值，但允许覆盖
- [ ] 补充对目录不存在的明确错误信息

### `pipeline/daily_signal.py`
- [ ] 固定输出结构
- [ ] 增加 metadata
- [ ] 明确错误处理与半成品文件保护

### `pipeline/__init__.py`
- [ ] 暴露 `run_daily_pipeline`

### `live/paper_trader.py`
- [ ] 完成 restart 安全恢复
- [ ] 完善 NAV 防重规则
- [ ] `rebalance()` 返回结构化摘要

### `live/risk_monitor.py`
- [ ] 输出结构统一化
- [ ] 对 skipped checks 提供显式说明
- [ ] 接入行业集中度的可选实现或标准化 skip

### `pipeline/factor_monitor.py`
- [ ] 保持与信号快照字段严格对齐
- [ ] 文档化 `healthy / degraded / dead / no_data`

### `pipeline/data_checker.py`
- [ ] 从统一配置读取数据目录
- [ ] 输出 `latest_date / days_stale / missing_symbols / status`

### `pipeline/weekly_report.py`
- [ ] 实现周报生成
- [ ] 周报模板固定

### `pipeline/cli.py`
- [ ] 帮助文本、命令输出、字段名与实际实现一致
- [ ] 命令失败时提供人能理解的提示

### `live/README.md`
- [ ] 更新为真实使用文档
- [ ] 增加“首次跑通”和“常见失败原因”

### `research/notebooks/13_live_simulation.ipynb`
- [ ] 只保留演示和回放用途
- [ ] 不作为唯一验证入口

---

## 9. Acceptance Commands

以下命令必须全部通过，才算本阶段完成：

```bash
# 1. 生成指定日期信号
python -m pipeline.cli signal --date 2026-03-20

# 2. 查看最新持仓
python -m pipeline.cli positions

# 3. 执行一次调仓
python -m pipeline.cli rebalance --date 2026-03-20

# 4. 查看绩效
python -m pipeline.cli performance

# 5. 因子健康度
python -m pipeline.cli factor-health

# 6. 风险检查
python -m pipeline.cli risk-check

# 7. 生成周报
python -m pipeline.cli weekly-report --week 2026-W12
```

并满足以下产物检查：

```bash
test -f live/signals/2026-03-20.json
test -f live/factor_snapshot/2026-03-20.parquet
test -f live/portfolio/positions.json
test -f live/portfolio/trades.json
test -f live/portfolio/nav.csv
test -f journal/weekly/2026-W12.md
```

---

## 10. Verification Strategy

### 必须有的验证
- 语法检查
- CLI smoke test
- 至少 3 个自动化测试

### 推荐测试场景
- 空持仓初始化
- 正常调仓
- 同日重复调仓
- 数据目录不存在
- 因子快照存在但价格不足
- 全部股票被过滤

---

## 11. Out-Of-Scope Follow-Ups

以下内容属于 Phase 5 之后：
- 定时调度
- Telegram/通知自动发送
- Dashboard 自动刷新与更完整交互
- 模拟券商接口
- 实盘下单

---

## 12. Hard Constraints

1. `live/portfolio/`、`live/signals/`、`live/factor_snapshot/` 数据产物不入 git
2. 不修改 `backtest/engine.py` 与研究框架的公共接口，除非为兼容性修复且有验证
3. 所有新函数都要有中文 docstring
4. commit message 不带任何 AI 署名
5. 不得引入需要额外长期运维的服务

---

## 13. Final Deliverable

最终交付不是一个文件集合，而是一套可执行说明：

1. 改好配置
2. 生成信号
3. 执行调仓
4. 查看持仓与绩效
5. 查看风险
6. 生成周报

如果一个新操作者在本机不能按这 6 步跑通，就说明本 Phase 5 infra 仍未完成。
