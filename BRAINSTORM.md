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
