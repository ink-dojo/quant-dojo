# live/ — 模拟盘系统

> Phase 5 模块，用于在真实市场环境中验证 Phase 4 策略的实际表现。

---

## 模块说明

| 文件/目录 | 说明 |
|-----------|------|
| `paper_trader.py` | `PaperTrader` — 虚拟持仓管理，追踪净值、收益和每日交易记录 |
| `risk_monitor.py` | 风险预警系统 — 回撤超限 / 集中度超标 / 因子 IC 衰减检测 |
| `portfolio/` | 持仓快照和交易流水（JSON/CSV，不入 git） |
| `signals/` | 每日选股信号输出（不入 git） |

---

## 快速开始（3步跑通模拟盘）

### 第1步：安装依赖

```bash
pip install -e .
python -c "from live.paper_trader import PaperTrader; print('✅ 模块加载成功')"
```

### 第2步：生成今日信号

```bash
# 通过 pipeline 脚本生成选股信号
python pipeline/run_pipeline.py --date today

# 信号文件输出到 live/signals/YYYY-MM-DD.json
```

### 第3步：查看持仓和绩效

```python
from live.paper_trader import PaperTrader

pt = PaperTrader()
pt.load_state()          # 加载历史持仓状态

# 查看当前持仓
print(pt.positions)

# 查看绩效汇总
perf = pt.get_performance()
print(perf)
```

---

## 目录结构

```
live/
├── README.md              # 本文档
├── paper_trader.py        # PaperTrader 主类
├── risk_monitor.py        # 风险监控系统
├── portfolio/             # 持仓记录（git 忽略）
│   ├── positions.json     # 当前持仓快照
│   └── trades.csv         # 历史交易流水
└── signals/               # 选股信号（git 忽略）
    └── YYYY-MM-DD.json    # 每日信号文件
```

---

## PaperTrader 主要接口

```python
from live.paper_trader import PaperTrader

# 初始化（默认初始资金 100万）
pt = PaperTrader(initial_capital=1_000_000)

# 执行一天的模拟交易
pt.execute_trades(signal_date='2025-01-02', signals=['600036', '000858', ...])

# 获取净值曲线
nav_series = pt.nav_history   # pd.Series，index 为日期

# 获取绩效报告
perf = pt.get_performance()
# 返回: {'annual_return': 0.18, 'sharpe': 1.2, 'max_drawdown': -0.15, ...}
```

---

## 风险监控

```python
from live.risk_monitor import check_risk_alerts

alerts = check_risk_alerts(pt)
for alert in alerts:
    print(f"[{alert['level']}] {alert['message']}")
```

### 监控维度

| 监控项 | 默认阈值 | 说明 |
|--------|----------|------|
| 最大回撤 | -20% | 超过触发平仓预警 |
| 单股集中度 | 15% | 单只股票持仓占比上限 |
| 行业集中度 | 40% | 单个行业持仓占比上限 |
| 因子 IC 衰减 | ICIR < 0.1 | 因子失效预警 |

---

## 与回测结果对标

模拟盘结束后，用 `research/notebooks/13_live_simulation.ipynb` 对比：
- 模拟盘净值 vs 回测净值
- 实际交易成本 vs 假设成本
- 信号延迟分析（T+0 生成 → T+1 执行）
