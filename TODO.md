# TODO — quant-dojo 当前任务

> 给 Claude 的执行清单。按顺序来，每完成一项把 `[ ]` 改成 `[x]`。
> 项目规范见 WORKFLOW.md，研究背景见 BRAINSTORM.md，路线图见 ROADMAP.md。

---

## 🔴 优先级 1 — 财务数据管道

### 1.1 新建 `utils/fundamental_loader.py`
- [x] 实现 `get_pe_pb(symbol: str, start: str, end: str) -> pd.DataFrame`
      — 用 `ak.stock_zh_valuation_baidu` 获取 PE_TTM/PB/PS（stock_a_indicator_lg 已下线）
      — 列名标准化：date, pe_ttm, pb, ps_ttm
      — 带 parquet 缓存，缓存路径 `data/raw/fundamentals/{symbol}_pe_pb.parquet`
- [x] 实现 `get_financials(symbol: str, periods: int = 8) -> pd.DataFrame`
      — 用 `ak.stock_financial_analysis_indicator` 获取财务指标（新浪财经）
      — 提取：ROE、毛利率、资产负债率、净利润增速、营收增速等
      — 列名全部改为英文 snake_case
- [x] 实现 `get_industry_classification(symbols: list) -> pd.DataFrame`
      — 用 `ak.stock_individual_info_em` 逐只获取行业分类（带重试+增量缓存）
      — 返回 DataFrame: symbol, industry_name
- [x] 在模块末尾加 `if __name__ == "__main__":` 快速验证（用 000001 平安银行测试）
- [x] 确认 `from utils.fundamental_loader import get_pe_pb` 可以正常 import

### 1.2 更新 `utils/__init__.py`
- [x] 把 `fundamental_loader` 的主要函数暴露出来（和现有 data_loader 一致）

---

## 🟡 优先级 2 — agents/ 模块骨架

### 2.1 新建 `agents/base.py`
- [x] 定义 `LLMClient` 类：
      — 优先用 `claude -p`（subprocess 调用）
      — 如果 claude 不在 PATH，fallback 到 Ollama（`http://localhost:11434`）
      — `complete(prompt: str) -> str` 方法
      — `complete_json(prompt: str) -> dict` 方法（自动解析 JSON，失败时返回 `{"error": ...}`）
- [x] 定义 `BaseAgent` 抽象类：
      — `__init__(self, llm: LLMClient)`
      — `analyze(self, **kwargs) -> dict` 抽象方法
      — `format_report(self, result: dict) -> str` 默认实现（Markdown 格式）

### 2.2 新建 `agents/debate.py`
- [x] 实现 `BullBearDebate` 类：
      ```
      输入：topic（因子名/股票代码），context（IC结果/价格数据摘要）
      流程：
        1. Bull analyst prompt → 列出3个做多理由
        2. Bear analyst prompt → 反驳 + 列出3个做空理由
        3. Moderator prompt → 综合结论 + 置信度（0-1）
      输出：dict {bull_args, bear_args, conclusion, confidence}
      ```
- [x] 实现 `debate_factor(factor_name: str, ic_summary: dict) -> dict`
      — 把 `utils/factor_analysis.ic_summary()` 的输出喂给辩论
      — 返回结构化报告

### 2.3 新建 `agents/__init__.py`
- [x] 暴露 `LLMClient`, `BullBearDebate`

### 2.4 快速测试
- [x] 在 `agents/` 目录下写 `test_debate.py`：
      用极坐标价量因子（IC均值 -0.031，ICIR -0.28）作为 context 跑一次辩论
      打印输出，确认能正常运行（不要求 LLM 结果完美，能跑通就行）

---

## 🟢 优先级 3 — 动量因子研究

### 3.1 新建 `research/factors/momentum/`
- [x] 新建 `momentum_factor.py`：
      — `compute_momentum(price_wide: pd.DataFrame, lookback: int, skip: int = 1) -> pd.DataFrame`
        lookback 窗口收益率，skip=1 跳过最近1天（避免反转噪音）
      — 支持多周期：`[5, 10, 20, 60, 120]` 日
- [x] 新建 `05_momentum_factor.ipynb`（放在 `research/notebooks/`）：
      结构：
        1. 计算多周期动量因子
        2. IC/ICIR 分析（复用 `utils/factor_analysis.compute_ic_series`）
        3. 分层回测（十分位）
        4. 与极坐标因子相关性（两者是否正交？）
        5. 结论：A 股动量 vs 反转，哪个更显著？
- [x] 在 `research/factors/momentum/README.md` 写研究结论（仿照 polar_pv_factor/README.md 的格式）

---

## ✅ 完成标准

每个优先级完成后更新 ROADMAP.md 对应条目的进度。
全部完成后在本文件末尾写一行：`> 完成时间：YYYY-MM-DD`

---

## 禁止事项（不要动）

- `data/` 目录下的数据文件
- `backtest/engine.py` 的对外接口（`BacktestEngine` 类的 `__init__` 和 `run` 签名）
- `research/factors/polar_pv_factor/` 下的任何文件
- `pyproject.toml` 的包结构

---

> 完成时间：2026-03-21

---

## Tech Debt

- [x] 🟡 `ic_weighted_composite` 在 `utils/factor_analysis.py:297` 和 `utils/multi_factor.py:112` 有两个不同签名的实现，接口命名易混淆
- [x] 🟡 `test_notebook_compat` 测试因缺少 `pyarrow` 失败 — 需要将 pyarrow 加入项目依赖或 CI 环境
- [x] 🟡 `agents/base.py` 的 Ollama URL 和超时值硬编码为默认参数，应改为环境变量
- [x] 🔵 `live/paper_trader.py:218` `rebalance()` 208 行，可拆分卖出/买入子阶段
- [x] 🔵 `pipeline/run_store.py:16-47` 架构注释块应合并到模块 docstring

