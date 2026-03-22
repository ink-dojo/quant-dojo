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

## Phase 5：模拟实盘（第25-36周） 🔄 进行中（~10%）

```
Phase 5  模拟实盘  █░░░░░░░░░  10%  🔄
```

### 基础设施（已完成）
- [x] `pipeline/` 目录：每日信号生成脚本、因子监控、数据检查、CLI 入口
- [x] `live/paper_trader.py`：PaperTrader — 虚拟持仓管理、净值追踪、绩效报告
- [x] `live/risk_monitor.py`：风险预警系统 — 回撤/集中度/因子衰减检测
- [x] `research/notebooks/13_live_simulation.ipynb`：模拟盘演示 & 2025 全年回放

### 信号与执行（待完成）
- [ ] 接入实时数据（akshare 日线 + 实时行情）
- [ ] 运行 `pipeline/daily_signal.py` 生成第一批真实信号
- [ ] 用 `13_live_simulation.ipynb` 回放 2025 全年，验证系统可用性
- [ ] 模拟盘执行（聚宽 / 掘金模拟）

### 验证与记录（待完成）
- [ ] 每周复盘记录（`journal/`）
- [ ] 实盘 vs 回测差异分析（滑点、延迟）
- [ ] 检查因子在 2025 年的 IC 是否仍然显著

**交付物：** 连续3个月模拟盘，月度绩效报告

---

## Phase 6：实盘（时机成熟后）

- [ ] 资金管理规则确定
- [ ] 接入真实券商 API
- [ ] 严格的风控规则（最大单日亏损、最大回撤熔断）
- [ ] 定期策略审查机制

**交付物：** 实盘运行，季度复盘

---

## 里程碑时间线

```
2026 Q1  →  Phase 0-1：环境 + 基础
2026 Q2  →  Phase 2-3：回测体系 + 因子研究
2026 Q3  →  Phase 4：策略打磨
2026 Q4  →  Phase 5：模拟实盘
2027 Q1  →  Phase 6：实盘启动（如条件成熟）
```
