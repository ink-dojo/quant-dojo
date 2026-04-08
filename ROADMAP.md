# 路线图 ROADMAP

> 更新日期：2026-03
> 原则：每个阶段要有**可交付物**，不是读完就算，是做完才算。

---

## Phase 0：环境搭建（第1周） ✅

- [x] Git 工作流熟悉（分支、PR、review）
- [x] Python 环境配置（venv + pip install -e .）
- [x] 数据源接入（akshare 免费接入，无需申请）
- [x] 跑通 `research/notebooks/01_getting_started.ipynb`

**交付物：** 本地环境可以拉数据、画图、跑简单计算

---

## Phase 1：基础建设（第2-4周） ✅

### 数学与统计
- [x] 收益率计算（简单收益率 vs 对数收益率）
- [x] 统计描述：均值、标准差、偏度、峰度
- [x] 相关性分析
- [x] 假设检验基础（t-test, p-value）

### 金融知识（jialong 主导）
- [x] A股市场机制（交易规则、涨跌停、T+1）
- [x] 常用数据：OHLCV、财务数据、行业分类
- [x] 基准指数理解（沪深300、中证500）

### 代码基础（xingyu 主导）
- [x] pandas 数据处理熟练
- [x] `utils/data_loader.py` 完善
- [x] `utils/metrics.py` 实现核心指标

**交付物：** 能用代码分析任意一只股票的历史数据

---

## Phase 2：回测体系（第5-8周） ✅

- [x] 理解回测框架原理（事件驱动 vs 向量化）
- [x] 搭建 `backtest/engine.py`
- [x] 实现第一个完整策略：双均线（MA Cross）
- [x] 绩效评估体系：夏普、最大回撤、胜率、盈亏比
- [x] 识别常见回测陷阱：未来函数、幸存者偏差、交易成本

**交付物：** `strategies/examples/dual_ma.py` 跑通，有完整绩效报告

---

## Phase 3：因子研究（第9-16周） ✅ 完成

### 经典因子
- [x] 动量因子（Momentum）— momentum_factor.py + notebook 已完成
- [x] 价值因子（PE, PB, PS）— value_factor.py + 06_value_factor.ipynb + README 已完成
- [x] 质量因子（ROE, 盈利稳定性）— quality_factor.py + 07_quality_factor.ipynb + README 已完成
- [x] 低波动因子（Beta, Volatility）— low_vol_factor.py + 08_low_vol_factor.ipynb + README 已完成

### 因子分析框架
- [x] IC/ICIR 分析（信息系数）— utils/factor_analysis.py 已完成
- [x] 分层回测（十分位组合）— utils/factor_analysis.py 已完成
- [x] 因子衰减分析 — factor_decay_analysis() 已实现
- [x] 多因子合成（等权 / 打分法 / 回归法）— ic_weighted_composite 已完成

**交付物：**
- `research/factors/` 下 4 个因子（动量/价值/质量/低波动）的完整分析框架
- `utils/factor_analysis.py` 包含衰减分析、中性化、批量分析工具
- `journal/phase3_summary.md` 阶段总结报告，含因子预期 IC、组合建议、Phase 4 路线图

---

## Phase 4：策略打磨（第17-24周） ✅ 完成

### 基础设施
- [x] 本地CSV数据加载器（utils/local_data_loader.py）—— 支持5477只股票批量并行加载
- [x] 多因子选股策略（strategies/multi_factor.py）—— ST过滤、交易成本、信号shift

### 因子验证与中性化
- [x] 因子验证 notebook（09_factor_validation.ipynb）—— IC/ICIR/衰减分析完整
- [x] 行业中性化验证 notebook（10_industry_neutral.ipynb）—— 去除板块轮动干扰

### 风险管理
- [x] 仓位管理（utils/position_sizing.py）—— Kelly公式 / 风险平价
- [x] 止损机制（utils/stop_loss.py）—— 绝对止损 / 相对止损 / 跌幅止损
- [x] Walk-forward验证（utils/walk_forward.py）—— 样本外性能评估

### 策略评审
- [x] 压力测试 notebook（11_stress_test.ipynb）—— 极端行情模拟（2015年股灾、2020年疫情等）
- [x] 完整策略报告 notebook（12_strategy_report.ipynb）—— 整合所有验证，最终评审

**交付物：** 完整通过验证的多因子策略框架，已验证夏普 > 1、年化收益 > 15%

---

## Phase 5：模拟实盘基础设施（第25-36周） ✅ 完成

```
Phase 5  模拟实盘基础设施  ██████████  100% ✅
```

### 基础设施（已完成）
- [x] `pipeline/` 目录：每日信号生成脚本、因子监控、数据检查、CLI 入口
- [x] `live/paper_trader.py`：PaperTrader — 虚拟持仓管理、净值追踪、绩效报告
- [x] `live/risk_monitor.py`：风险预警系统 — 回撤/集中度/因子衰减检测
- [x] `research/notebooks/13_live_simulation.ipynb`：模拟盘演示 & 2025 全年回放
- [x] `quant_dojo` 统一 CLI：16 个命令覆盖 init/run/backtest/generate/activate/status/diff 等
- [x] `pipeline/auto_gen_loader.py`：自动生成的策略可作为一等公民进入 daily pipeline

### 当前剩余重点
- [x] 连续运行每日 `signal -> rebalance -> risk -> weekly report`
      （2026-04-07 验证 10 天连续 run，见 `journal/phase5_continuous_run_20260407.md`）
- [x] 完成 restart-safe 组合状态恢复与一致性验证
      （`tests/test_phase5_regression.py::TestPaperTraderRestartSafe` 已覆盖；
       连续运行实测 NAV 与持仓零漂移）
- [x] 把自动化验证从 smoke 提升到回归级别
      （`test_phase5_regression.py` + `test_factor_monitor_health.py` 总 19+ 测试覆盖端到端 IO）
- [x] 证明系统可连续稳定跑完整周 / 整月模拟盘
      （10 个交易日干净 replay，每日 4/4 步成功，幂等重跑无副作用）
- [x] 提高风险输出与周报产物的审计价值
      （周报增加 git commit / 指纹 / 最大回撤 / 因子 t-stat；
       风险告警过滤 insufficient_data；见 `test_weekly_report_audit.py`）

### 验证与记录
- [x] 每周复盘记录（`journal/weekly/2026-W01..W15.md`）
- [x] 检查因子在 2025/2026 年的 IC 是否仍然显著
      （2026-04-07 审计，见 `journal/v7_factor_ic_audit_20260407.md`：
       v7 全部健康，t-stat 均 > 3.5；之前的 dead 告警是小样本误报，已修复）
- [x] 实盘 vs 回测差异分析（滑点、延迟）
      （`pipeline/live_vs_backtest.py` + `quant_dojo diff` CLI；
       2026-04-07 首次对照 8 天，见 `journal/live_vs_backtest_v7_20260407_analysis.md`，
       量化出 -2.05% 累计偏差，主因是 fresh-start 方法论差异 + 交易成本）

**交付物：** 可信的模拟盘基础设施，支持连续运行和审计

---

## Phase 6：Control Plane（CLI 统一执行 + Dashboard 统一展示）

### 目标

把 quant-dojo 从“很多模块和脚本”升级成“统一操作系统”。

原则：
- **CLI 是主执行面**
- **Dashboard 是主观察面**
- AI 后续优先调用 CLI，而不是直接拼模块

### CLI（必须补齐）
- [ ] 统一命令树：`backtest run / compare / signal / rebalance / report / doctor`
      （当前是扁平树；重构动作大，暂留）
- [x] 策略注册表：每个策略有标准名字、参数、输入契约
      （`pipeline/active_strategy.VALID_STRATEGIES` + `BacktestConfig`）
- [x] 标准化回测产物：指标、参数、日期区间、图表、日志
      （`live/runs/<run_id>.json` + `<run_id>_equity.csv`）
- [x] 运行历史索引：知道每次 backtest / pipeline run 发生了什么
      （`quant_dojo history` 覆盖 live/runs + logs/quant_dojo_run_*.json，
       支持 --type/--strategy/--status/--limit/--json 过滤）
- [x] 比较命令：多个策略/参数组合可直接横向比较
      （`quant_dojo compare`；支持 `--runs <id1> <id2>` 直接对比已有 run，不重跑）

### Dashboard（必须补齐）
- [x] 策略列表页：显示每个策略最近一次回测与核心指标
      （现有 streamlit app.py "回测" 页，展示 `pipeline/run_store` 下历史 run）
- [x] 回测结果页：收益、回撤、换手、因子暴露、参数版本
      （app.py "回测" 页已覆盖）
- [x] 组合页：当前模拟盘持仓、NAV、来源策略
      （app.py "总览" + "持仓分析" 已覆盖）
- [x] 风险页：预警、因子健康、数据 freshness、失败状态
      （app.py "因子健康" + "告警中心" 已覆盖）
- [x] 操作页：手动触发 signal / rebalance / weekly report
      （`dashboard/routers/trigger.py` + `POST /api/trigger/rebalance`、
       `POST /api/trigger/weekly-report`；signal.run 已由
       `/api/pipeline/run` 覆盖）

**交付物：**
- 一个终端做完所有策略回测与运行
- 一个 dashboard 看清所有策略和运行状态

---

## Phase 7：Agentic Research（AI 研究助理 → 有门禁的操作员）

### 目标

让 AI 从“解释结果”升级为“能提出实验、运行实验、总结结果”的研究助理。

### 第一阶段（现实可做）
- [ ] AI 根据周报 / 风险状态提出新的研究问题
- [ ] AI 批量运行标准化 backtest
- [ ] AI 比较不同策略 / 参数 / 区间的结果
- [ ] AI 输出实验总结和建议，但不直接执行交易

### 第二阶段（需要门禁）
- [ ] 风险门禁：不满足约束时禁止进入模拟盘
- [ ] 批准流：AI 提议后必须人工批准才能执行
- [ ] 运行日志：记录 AI 提议、参数、结论、最终动作

**交付物：** AI 成为量化研究操作员，而不是聊天玩具

---

## Phase 8：Agentic Execution / Real-Money Readiness（远期）

### 目标

讨论 AI 更深度接管之前，必须先解决真实资金约束。

- [ ] 模拟盘连续表现门槛
- [ ] 资金管理与风控规则固化
- [ ] 自动停机 / 熔断 / 风险升级机制
- [ ] 券商 API 与实盘执行审查
- [ ] AI 是否可拥有部分执行权的治理规则

**交付物：** 不是“AI 已经自动交易”，而是“系统已具备被审查和被约束的资格”

---

## 里程碑时间线

```
2026 Q1  →  Phase 0-1：环境 + 基础
2026 Q2  →  Phase 2-3：回测体系 + 因子研究
2026 Q3  →  Phase 4：策略打磨
2026 Q4  →  Phase 5：模拟实盘基础设施完成
2027 Q1  →  Phase 6：Control Plane（统一 CLI + Dashboard）
2027 Q2  →  Phase 7：Agentic Research
2027 H2  →  Phase 8：更深度自动化 / 实盘准备（条件成熟再开）
```
