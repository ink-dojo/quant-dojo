# BRAINSTORM — TradingAgents 整合研究

> 研究日期：2026-03
> 结论：三件事值得做，有优先级

---

## TradingAgents 是什么

**原版（35k+ stars，Apache-2.0）**
多智能体 LLM 框架，模拟真实交易公司结构：
```
4个分析师 Agent（基本面/技术面/情绪/新闻）
    → 牛熊研究员辩论
    → 交易员
    → 风控
    → 组合经理
```
用 LangGraph 编排，支持 OpenAI / Claude / Gemini / Ollama

**TradingAgents-CN（中文版，hsliuping）**
在原版基础上增加：
- A 股数据源（AkShare / Tushare / BaoStock）— 和 quant-dojo 依赖一致
- 中文 LLM 支持（DeepSeek / 通义千问）
- Vue3 Web UI + 报告导出
- ⚠️ 注意：Web UI 是商业授权，**核心 Agent 逻辑是 Apache-2.0 可用**

---

## 对 quant-dojo 最有价值的三件事

### 1. 财务数据管道（优先级 ★★★）

**现状**：`data_loader.py` 已有成熟的价格/量数据下载（akshare，带缓存）
**缺口**：因子研究 Phase 3 需要财务数据（PE、PB、ROE、营收增速等），当前没有

**要做的**：
- 新增 `utils/fundamental_loader.py`
- 参考 TradingAgents-CN 的 AkShare 接入方式
- 接口：`get_pe_pb(symbol, date)`, `get_financials(symbol, periods=8)`
- 输出 parquet 缓存，和现有 data/ 结构一致

### 2. 牛熊辩论机制（优先级 ★★）

**为什么有用**：
- 因子研究阶段容易产生选股偏见（只看好的信号）
- 让 AI 分别扮演多空双方，强迫考虑反面论据
- 对 jialong 的基本面分析特别有帮助

**要做的**：
- 新建 `agents/` 模块
- `agents/base.py` — Agent 基类（用 `claude -p` 或 Ollama，不硬编码 API key）
- `agents/debate.py` — `BullBearDebate` 类，输入：因子/股票，输出：多空论点 + 结论
- 先做最简版本，不用 LangGraph，直接两次 LLM 调用就够

### 3. 低成本 AI 基本面解读（优先级 ★）

**为什么有用**：
- jialong 做基本面分析，目前靠人工读研报
- 用 DeepSeek（或本地 Ollama）自动摘要财报/研报，给出要点
- 不是替代判断，是加速信息处理

**要做的**（后期）：
- `agents/fundamental_analyst.py`
- 输入：股票代码 + 日期，输出：基本面摘要 + 风险点

---

## 不要做的事

- **不要引入 LangGraph**：过重，我们不需要，两次 LLM 调用就够
- **不要接 Web UI**：TradingAgents-CN 的 Vue3 UI 是商业授权，且我们不需要
- **不要现在做实时数据**：Phase 5 才需要，先搞好离线研究
- **不要为了 AI 而 AI**：每个 Agent 必须有明确的研究价值，不是展示技术

---

## 和现有模块的关系

```
现有（已有，不动接口）          新增（本次目标）
─────────────────────          ──────────────────────────
utils/data_loader.py      →    utils/fundamental_loader.py
utils/factor_analysis.py  →    agents/debate.py (用 factor 结果做辩论)
strategies/base.py        →    agents/base.py (独立，不依赖 strategy)
backtest/engine.py        →    (不动)
```

---

## 参考仓库

- TradingAgents 原版: https://github.com/TauricResearch/TradingAgents
- TradingAgents-CN: https://github.com/hsliuping/TradingAgents-CN
- 重点看：`tradingagents/dataflows/` (数据接入) + `tradingagents/agents/analysts/` (Agent 结构)

---

# BRAINSTORM — quant-dojo 的终局形态

> 更新日期：2026-03-23
> 核心判断：未来目标不是“做很多 notebook”，而是“做一套 AI 可参与、但受风控和人工批准约束的量化操作系统”。

## 1. 最终想做成什么

长期愿景：

```text
AI 提议研究方向
→ 系统批量运行标准化回测
→ AI 汇总比较结果
→ 风险门禁检查
→ 人工批准
→ 模拟盘执行
→ 周报复盘
→ 实盘准备
```

这不是“聊天型 AI + 一堆脚本”，而是：

- 一个终端做完所有回测与日常操作
- 一个 dashboard 看清所有策略和运行状态
- 一个 AI 助手帮你持续提出实验、运行实验、解释结果

## 2. 什么不是正确方向

- 不是先把 dashboard 做成花哨网页，再反向塞业务逻辑
- 不是让 AI 直接 import 各模块、绕过统一入口
- 不是“AI 自己决定交易”，但没有风控、审批、审计
- 不是继续堆 notebook，让操作和结果散在文件夹里

## 3. 现实路线图

### 第一阶段：可信模拟盘基础设施

先把下面这条主链路做扎实：

```text
signal → rebalance → positions → performance → risk → weekly report
```

没有这一层，后面所有 AI 自动化都只是更高级的幻觉。

### 第二阶段：Control Plane

这是最近未来最重要的一步。

**CLI 是主执行面**
- 所有策略回测
- 参数搜索
- 信号生成
- 调仓执行
- 周报生成
- 风险检查

**Dashboard 是主观察面**
- 展示回测结果
- 展示策略比较
- 展示当前组合和风险状态
- 手动触发任务
- 呈现 AI 分析结果

一句话：

> 终端负责“做”，dashboard 负责“看”和“批”。

### 第三阶段：Agentic Research

AI 最先接管的应该是研究，不是执行。

可以让 AI 做：
- 提议新实验
- 批量跑标准化回测
- 汇总策略差异
- 解释风控和周报
- 生成下一轮研究建议

不应该让 AI 先做：
- 绕过门禁直接调仓
- 在没有约束的情况下自动选策略
- 在没有连续验证前直接走实盘

## 4. “像游戏一样，一个终端做所有策略回测”是否现实

非常现实，而且是对的方向。

理想形态应该像这样：

```bash
python -m pipeline.cli backtest run mean_reversion --start 2020-01-01 --end 2025-12-31
python -m pipeline.cli backtest compare momentum value quality
python -m pipeline.cli signal run --date 2026-03-23
python -m pipeline.cli rebalance run --date 2026-03-23
python -m pipeline.cli report weekly --week 2026-W13
python -m pipeline.cli doctor
```

这类终端系统的优点：
- 执行统一
- 适合 AI 调用
- 易于标准化和审计
- 比点网页更适合真实量化工作流

## 5. Dashboard 应该怎么定位

Dashboard 不是主引擎，而是 control tower。

它未来应该显示：
- 策略列表和最近一次 backtest
- 回测指标、回撤、换手、参数版本
- 当前模拟盘持仓、NAV、来源策略
- 数据 freshness
- 风险预警
- 周报摘要
- AI 研究建议
- 手动触发 pipeline / backtest / report

但它不应该：
- 重写底层策略逻辑
- 变成一个脱离 CLI 的第二套系统

## 6. 离“AI 全盘接管”还有多远

当前判断：

- 离“AI 全权自己交易”：还远
- 离“AI 帮你跑研究、比较策略、给出执行建议”：已经不远
- 离“一个终端做完所有策略回测和日常操作”：很近

所以最现实的中期目标是：

> **AI 研究助理 + 人工批准 + 统一控制面**

而不是：

> **AI 无门禁自主交易**
