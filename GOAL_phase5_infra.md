# GOAL — quant-dojo Phase 5 量化工程基础设施

> 给 /autoloop 的目标文件。当前日期：2026-03-22

---

## 背景

Phase 3/4 完成了因子研究和策略代码。现在需要把研究成果转化为可以持续运行的工程系统。

**已有：**
- 因子库（动量/价值/质量/低波动）
- 多因子策略 `strategies/multi_factor.py`
- 本地数据加载器 `utils/local_data_loader.py`（5477只股票，桌面CSV）
- 止损/仓位管理工具
- Telegram 通知（`~/.claude/hooks/notify-telegram.sh` 已配置）

**本次目标：** 搭建量化工程基础设施，让系统能自动运行、自动记录、自动预警。

---

## 理想终态

### 1. 每日信号生成管道 `pipeline/daily_signal.py`

```
数据目录：/Users/karan/Desktop/20260320/
```

实现 `run_daily_pipeline(date: str = None) -> dict`：

```
流程：
  1. 加载所有股票最新数据（用 local_data_loader）
  2. 计算各因子截面值（动量/EP/低波动/换手率）
  3. 合成综合评分（等权）
  4. 过滤：排除ST、上市不足60日、价格<2元的股票
  5. 输出当日选股名单（前30只）
  6. 保存结果到 live/signals/{date}.json
  7. 保存因子值快照到 live/factor_snapshot/{date}.parquet

输出 dict：
  {
    "date": "2026-03-20",
    "picks": ["600000", "000001", ...],  # 30只
    "scores": {"600000": 0.85, ...},
    "factor_values": {
      "momentum_20": {"600000": 0.12, ...},
      "ep": {"600000": 0.08, ...},
      ...
    },
    "excluded": {"st": 120, "new_listing": 45, "low_price": 23},
  }
```

在 `pipeline/__init__.py` 暴露 `run_daily_pipeline`。

文件末尾 `if __name__ == "__main__":` 跑一次最新日期的信号生成并打印结果。

---

### 2. 模拟持仓追踪器 `live/paper_trader.py`

实现 `PaperTrader` 类，追踪虚拟持仓和收益：

```python
class PaperTrader:
    """
    模拟盘持仓管理

    不接券商API，纯本地记录。
    持仓文件：live/portfolio/positions.json
    交易记录：live/portfolio/trades.json
    净值曲线：live/portfolio/nav.csv
    """

    def __init__(self, initial_capital: float = 1_000_000):
        """初始资金默认100万元"""

    def rebalance(self, new_picks: list, prices: dict, date: str):
        """
        调仓
        参数：
            new_picks: 新的选股名单
            prices:    {symbol: 当日收盘价}
            date:      调仓日期

        逻辑：
            1. 计算需要买入/卖出的股票
            2. 按等权分配资金
            3. 扣除双边 0.3% 交易成本
            4. 更新 positions.json 和 trades.json
            5. 记录当日 NAV 到 nav.csv
        """

    def get_performance(self) -> dict:
        """
        返回当前模拟盘绩效
        {
          "total_return": 0.123,
          "annualized_return": 0.18,
          "sharpe": 1.2,
          "max_drawdown": -0.08,
          "n_trades": 45,
          "running_days": 90,
        }
        """

    def get_current_positions(self) -> pd.DataFrame:
        """返回当前持仓明细 DataFrame"""
```

---

### 3. 风险监控模块 `live/risk_monitor.py`

```python
def check_risk_alerts(portfolio: PaperTrader, price_data: dict) -> list:
    """
    检查风险预警，返回预警信息列表

    检查项：
    1. 组合回撤预警：当日回撤超过 -5% → 警告；超过 -10% → 红色警报
    2. 单票仓位预警：任一持仓占比超过 15% → 警告
    3. 行业集中度：同一行业超过 40% → 警告
    4. 因子 IC 衰减检测：最近 20 日 IC 均值 < 0（因子失效）→ 警告
    5. 涨跌停持仓：有持仓股涨停（无法卖出）或跌停（无法买入）→ 提示

    返回：
        [{"level": "warning"|"critical", "msg": "...", "symbol": "..."}]
    """

def format_risk_report(alerts: list) -> str:
    """格式化为 Markdown 风险报告"""
```

---

### 4. 每周自动周报 `pipeline/weekly_report.py`

实现 `generate_weekly_report(week: str = None) -> str`：

```
每周五自动生成，格式对应 journal/weekly/YYYY-Www.md

内容：
  1. 本周持仓变化（买入/卖出了哪些股票）
  2. 本周净值表现 vs 沪深300
  3. 各因子本周 IC（信号是否有效）
  4. 风险预警摘要
  5. 下周调仓计划（下周一的选股名单预测）

自动写入 journal/weekly/{YYYY-Www}.md
```

---

### 5. 因子健康度监控 `pipeline/factor_monitor.py`

持续追踪因子有效性，防止因子失效：

```python
def compute_rolling_ic(
    factor_name: str,
    lookback_days: int = 60,
) -> pd.Series:
    """
    计算最近 lookback_days 天的滚动 IC
    用于判断因子是否仍然有效
    """

def factor_health_report() -> dict:
    """
    返回各因子当前健康状态
    {
      "momentum_20": {"rolling_ic": -0.02, "status": "degraded"},
      "ep":          {"rolling_ic": 0.04,  "status": "healthy"},
      ...
    }
    status: "healthy"（|IC|>0.02）/ "degraded"（|IC|<0.02）/ "dead"（IC≈0且t<1）
    """
```

---

### 6. 命令行入口 `pipeline/cli.py`

用 argparse 实现以下命令：

```bash
# 生成今日信号
python -m pipeline.cli signal

# 生成指定日期信号
python -m pipeline.cli signal --date 2026-03-20

# 查看当前持仓
python -m pipeline.cli positions

# 执行调仓（基于最新信号）
python -m pipeline.cli rebalance --date 2026-03-20

# 查看绩效
python -m pipeline.cli performance

# 因子健康度报告
python -m pipeline.cli factor-health

# 生成本周周报
python -m pipeline.cli weekly-report

# 风险检查
python -m pipeline.cli risk-check
```

---

### 7. 数据新鲜度检查 `pipeline/data_checker.py`

```python
def check_data_freshness(data_dir: str = "/Users/karan/Desktop/20260320/") -> dict:
    """
    检查本地数据是否是最新的

    返回：
    {
      "latest_date": "2026-03-20",
      "days_stale": 2,         # 距今几个交易日
      "missing_symbols": [],   # 有哪些股票数据缺失
      "status": "ok"|"stale"|"missing"
    }
    """
```

若数据超过 3 个交易日未更新，在 CLI 运行时自动打印警告。

---

### 8. Notebook `13_live_simulation.ipynb`

展示整个模拟盘系统的使用方式：

```
Section 1: 初始化 PaperTrader（初始资金100万）
Section 2: 批量回放 2025 全年（模拟每月调仓）
  - 用 run_daily_pipeline 生成每月第一天的信号
  - 用 PaperTrader.rebalance 执行调仓
  - 记录每次调仓后的 NAV
Section 3: 绩效评估
  - NAV 曲线 vs 沪深300
  - 分月度收益表
  - 最大回撤区间
Section 4: 风险监控回溯
  - 2025 年内触发过哪些风险预警？
  - 止损机制在哪几个月救了回撤？
```

---

### 9. 更新 `live/README.md`

把原来的占位内容替换成实际使用文档：
- 各模块说明
- 快速开始（3步跑通模拟盘）
- 目录结构

---

### 10. 更新 ROADMAP.md 和 journal

- Phase 5 已完成的条目标 [x]
- `journal/weekly/2026-W13.md` 追加本次工作记录

---

## 目录结构（完成后）

```
quant-dojo/
├── pipeline/
│   ├── __init__.py
│   ├── cli.py              # 命令行入口
│   ├── daily_signal.py     # 每日信号生成
│   ├── weekly_report.py    # 每周自动周报
│   ├── factor_monitor.py   # 因子健康度监控
│   └── data_checker.py     # 数据新鲜度检查
├── live/
│   ├── paper_trader.py     # 模拟持仓追踪
│   ├── risk_monitor.py     # 风险监控
│   ├── portfolio/          # 持仓/交易记录（不入git）
│   └── signals/            # 每日信号（不入git）
└── research/notebooks/
    └── 13_live_simulation.ipynb
```

---

## 硬性约束

1. **数据路径固定：** `/Users/karan/Desktop/20260320/`
2. **live/portfolio/ 和 live/signals/ 加入 .gitignore**（不上传持仓数据）
3. **禁止动的文件：** `backtest/engine.py` 签名、`polar_pv_factor/` 目录
4. **回测红线：** 信号 `.shift(1)`，排ST，双边0.3%成本
5. **代码规范：** 注释中文，变量名英文，每个函数有 docstring
6. **禁止** commit message 里加任何 AI 署名

---

## 完成验证标准

```bash
# 1. 信号生成管道
python -m pipeline.cli signal --date 2026-03-20
# 应输出：选股名单30只，保存到 live/signals/2026-03-20.json

# 2. 持仓查询
python -m pipeline.cli positions
# 应输出：当前持仓 DataFrame

# 3. 因子健康度
python -m pipeline.cli factor-health
# 应输出：各因子 IC 状态

# 4. 风险检查
python -m pipeline.cli risk-check
# 应输出：无预警或具体预警信息

# 5. 模块可导入
python -c "from pipeline.daily_signal import run_daily_pipeline; print('✅')"
python -c "from live.paper_trader import PaperTrader; print('✅')"
python -c "from live.risk_monitor import check_risk_alerts; print('✅')"
python -c "from pipeline.factor_monitor import factor_health_report; print('✅')"

# 6. notebook 存在
ls research/notebooks/13_live_simulation.ipynb
```
