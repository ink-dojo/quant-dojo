# quant-dojo Master Workplan

> 这是仓库的总工作计划入口。所有当前目标、后续目标和未来方向统一从这里进入。
> 详细设计和执行细节仍保留在各自的 `GOAL_*.md` 文件中，但本文件是**唯一总览**。
> 更新日期：2026-03-22
>
> 新建执行型 goal 时，统一从 [`GOAL_EXECUTION_TEMPLATE.md`](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_EXECUTION_TEMPLATE.md) 开始。

---

## 1. Mission

`quant-dojo` 的长期目标不是“做很多 notebook”，而是建立一套可持续迭代的 A 股量化研究与执行系统：

```text
研究假设 → 因子验证 → 策略构建 → 模拟盘运行 → 风险控制 → 复盘迭代 → 实盘准备
```

短期优先级必须服从这个主线。

---

## 2. Canonical Status

### 已完成
- Phase 0-3：环境、回测框架、因子研究主干
- Phase 4：多因子策略打磨与验证主框架
- Dashboard：本地单机工作台已有初版骨架
- Phase 5 infra：已有初版实现，且已完成一轮关键 correctness 修复

### 当前最重要的事实
- 系统已经不再是纯研究仓库
- 但它还没有达到“可信模拟盘基础设施”的标准
- 当前首要任务不是扩功能，而是把 Phase 5 基础设施做扎实

---

## 3. Single Priority Stack

所有工作按下面顺序排，不允许随意跳：

1. **P0: Phase 5 Infrastructure**
   目标：让 `signal -> rebalance -> positions -> performance -> risk -> weekly report` 成为可信闭环。
   详细计划见 [GOAL_phase5_infra.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md)

2. **P0.5: Control Plane First Implementation** ✅ 已完成
   目标：统一 CLI 命令树 + 策略注册表 + 运行记录 + Dashboard 集成 + AI-safe 控制面。
   详细计划见 [GOAL_control_plane.md](GOAL_control_plane.md)

3. **P0.75: Control Plane Convergence** 🔄 当前进行中
   目标：把已完成的 control plane 从“第一版可用”推进到“系统级收口”，重点是 artifact 语义、dashboard/CLI 一致性、approval gate、端到端回归和重复 review loop 验收。
   详细计划见 [GOAL_control_plane_convergence.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_control_plane_convergence.md)

4. **P1: Dashboard Integration**
   目标：把已稳定的数据与操作统一展示在本地工作台里，而不是继续手工翻文件和跑脚本。
   详细计划见 [GOAL_dashboard.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_dashboard.md)

5. **P2: Phase 5 Operational Maturity**
   目标：在基础设施稳定后，进入连续模拟运行、周报、风险回顾、数据 freshness 管控。
   这部分以 [GOAL_phase5_infra.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md) 后半段的验收和周报机制为基础，不单独拆新目标，直到 P0 真正完成。

6. **P3: Strategy Upgrades / New Research**
   目标：只有在模拟盘主链路可信后，才继续扩策略、增强因子和研究方法。
   历史背景与已完成内容见 [GOAL_phase4.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase4.md) 和 [GOAL.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL.md)

7. **P4: Control Plane** ✅ 第一版已完成
   目标：把分散脚本、回测、模拟盘、周报、风控整合成一个统一操作面。
   原则：CLI 负责执行，Dashboard 负责展示与批准，不反过来。
   详细计划见 [GOAL_control_plane.md](GOAL_control_plane.md)

8. **P5: Agentic Research And Execution**
   目标：让 AI 从“分析助手”升级为“有门禁的研究操作员”，能提议实验、批量跑回测、汇总比较结果，但不能绕过风控和人工批准。

9. **P6: Future Real-Money Readiness**
   目标：配置治理、执行纪律、连续模拟结果、资金管理、实盘前审查。
   当前只记录方向，不开做。

---

## 4. What To Work On Now

### Active Now: Phase 5 Infrastructure

当前唯一主任务：
- 统一运行配置，去掉硬编码路径
- 加固每日信号输出
- 完成 `PaperTrader` 状态完整性
- 让风险/因子健康度输出真正可信
- 生成周报产物
- 增加最小自动化验证

详细执行见：
- [GOAL_phase5_infra.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md)

### Done Recently
- 修复了回测引擎与多因子策略返回列不兼容问题
- 修复了 `PaperTrader.rebalance()` 不真正再平衡的问题
- 修复了 risk monitor 未正确读取因子健康状态的问题
- 修复了 `factor_monitor` 依赖不存在的 `next_return` 问题
- 修复了 CLI 调仓未加载真实价格的问题

这些修复说明：Phase 5 不是“补文档”，而是确实存在 correctness 风险，因此必须继续按 infra 路线推进。

---

## 5. What Comes Next

### Next After P0: Dashboard

Dashboard 的位置很明确：
- 它不是主系统
- 它是主系统稳定之后的操作台

因此 Dashboard 必须依赖已稳定的 `pipeline/`、`live/`、`agents/`，而不是自己重新实现业务逻辑。

执行时机：
- 只有当 Phase 5 infra 的 Milestone A/B 基本完成后，Dashboard 才进入主开发阶段

详细计划见：
- [GOAL_dashboard.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_dashboard.md)

### Next After Dashboard: Control Plane Convergence

控制面的第一版已经完成，下一阶段不是重做架构，而是把它收敛到账可信：

- 证明 CLI、run artifacts、dashboard 消费是同一条契约
- 收紧 artifact schema 和 provenance
- 验证 approval gate 和 legacy CLI compatibility
- 用至少两轮独立 review loop 作为收口门槛

- **Terminal / CLI 是主执行面**
  - 统一所有策略回测、信号生成、调仓、周报、风险检查入口
  - AI agent 将来优先调用 CLI，而不是直接 import 各种模块
- **Dashboard 是主观察面**
  - 展示策略列表、回测结果、运行历史、当前组合、风险状态、周报摘要
  - 提供手动触发按钮，但不复制底层业务逻辑
- **核心目标**
  - 一个终端完成所有策略回测和运行
  - 一个 dashboard 看清所有策略和运行状态

这一步是从“很多工具”升级到“量化操作系统”的关键。

详细执行计划见：
- [GOAL_control_plane_convergence.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_control_plane_convergence.md)

### Long-Term Direction: Agentic Portfolio Manager

长期目标不是做一个会说话的 dashboard，而是建立一套有门禁的 agentic workflow：

```text
AI 提议研究方向
→ 系统批量运行标准化回测
→ 自动汇总关键指标与差异
→ 风险门禁检查
→ 人工批准
→ 模拟盘执行
→ 周报与复盘
```

当前判断：

- 离“AI 全权自己交易”还远
- 离“AI 帮你跑研究、比较策略、给出执行建议”已经不远
- 因此近期应做的是 **AI 助手 + 人工批准**，不是 **AI 自主交易**

---

## 6. Future Work Buckets

### Bucket A: Simulated Trading Operations
- 连续月度模拟盘
- 周报沉淀
- 风险事件归档
- 回测 vs 模拟差异分析

### Bucket B: Data And Execution Reliability
- 更稳的配置管理
- 更明确的数据版本与数据 freshness
- restart-safe portfolio state
- 自动化 smoke tests / regression tests

### Bucket C: Strategy Expansion
- 更强的多因子组合方法
- 更严格的样本外测试
- 更细的风控与持仓约束
- 新研究主题，但必须服从 Phase 5 主线

### Bucket D: Operator Tools
- Dashboard 完整化
- AI stock analyst / bull-bear debate 的工作台整合
- 手动触发 pipeline 与流式进度
- Backtest run 历史、参数版本、结果对比
- 统一 CLI / dashboard 控制面

### Bucket E: Real Money Readiness
- 资金管理规则固化
- 模拟盘连续表现门槛
- 实盘前 checklist
- 券商 API 评估

### Bucket F: Agentic Ops
- Experiment planner：AI 生成待验证实验
- Batch runner：批量跑标准化 backtest
- Result judge：AI 总结优劣与失效原因
- Risk gate：不满足风险门槛时禁止进入模拟盘
- Approval workflow：保留人工最终批准

---

## 7. Phase Map

### Phase 0-3
定位：学习、回测、因子验证  
状态：基本完成  
详情：
- [GOAL.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL.md)
- [ROADMAP.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/ROADMAP.md)

### Phase 4
定位：策略打磨与真实数据验证  
状态：主要工作已完成，但仍可作为后续策略升级参考  
详情：
- [GOAL_phase4.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase4.md)

### Phase 5
定位：模拟盘基础设施与运行闭环  
状态：进行中，当前最高优先级  
详情：
- [GOAL_phase5_infra.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md)

### Dashboard Track
定位：本地单机工作台  
状态：次优先级，依赖 Phase 5 infra 稳定  
详情：
- [GOAL_dashboard.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_dashboard.md)

### Control Plane Track ✅ 第一版已完成
定位：统一 CLI 执行面 + Dashboard 观察面
状态：第一版已完成（2026-03-23），系统级收口仍在进行
交付物：
- `pipeline/strategy_registry.py` — 策略注册表
- `pipeline/run_store.py` — 运行记录存储
- `pipeline/control_surface.py` — AI-safe 控制面
- `pipeline/cli.py` — 层级 CLI 命令树
- Dashboard 回测端点 + 前端面板
- 27 个自动化测试
- 详细计划见 [GOAL_control_plane.md](GOAL_control_plane.md)

### Control Plane Convergence Track 🔄 当前进行中
定位：把 control plane 从“可用”推进到“收口”
状态：当前主线之一
重点：
- artifact schema 固化
- dashboard / CLI 一致性
- legacy CLI compatibility 回归保护
- approval gate 回归保护
- 至少两轮独立 review loop 无新增实质问题后才允许收敛
详情：
- [GOAL_control_plane_convergence.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_control_plane_convergence.md)

### Agentic Track
定位：AI 从研究助手升级到有门禁的研究操作员  
状态：中长期方向，必须建立在 Control Plane 之上  
说明：
- 先做 AI 提议与批量实验
- 后做风险门禁与批准流
- 最后才考虑更高自动化

---

## 8. Execution Rules

1. 当前只允许有一个主目标：Phase 5 infra。
2. 新想法先放 `journal/ideas.md` 或 `BRAINSTORM.md`，不要直接变成主任务。
3. 任何新 workplan 都必须回链到本文件，不能再散落成孤立入口。
4. 未来新增目标文件时，必须同时更新本文件的 Priority Stack 和 Phase Map。
5. 如果某项工作不能帮助“可信闭环”或“后续工作台整合”，优先级自动降低。

---

## 9. How To Use This File

### 如果你要开始做事
先看：
- [WORKPLAN.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/WORKPLAN.md)

再用模板起执行文件：
- [GOAL_EXECUTION_TEMPLATE.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_EXECUTION_TEMPLATE.md)

再进入当前主目标：
- [GOAL_phase5_infra.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase5_infra.md)

### 如果你要了解历史背景
看：
- [GOAL.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL.md)
- [GOAL_phase4.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_phase4.md)
- [ROADMAP.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/ROADMAP.md)

### 如果你要做界面层
看：
- [GOAL_dashboard.md](/Volumes/Crucial%20X10/Documents/GitHub/quant-dojo/GOAL_dashboard.md)

---

## 10. Definition Of “One Place”

从现在开始，“所有 workplan 在一个地方”指的是：

- **总入口**：`WORKPLAN.md`
- **当前执行主计划**：`GOAL_phase5_infra.md`
- **其他 GOAL 文件**：作为分计划存在，但不再承担总入口职责

如果后续需要，我还可以继续做两件事：
- 把 `README.md` 和 `ROADMAP.md` 也改成显式指向 `WORKPLAN.md`
- 给各个 `GOAL_*.md` 文件加上“父计划是 WORKPLAN.md”的头部说明
