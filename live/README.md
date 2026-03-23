# live/ — 模拟盘系统

> Phase 5 模块，提供命令行工具运行每日选股、调仓、风险监控和绩效分析。
> 支持两种使用方式：(1) CLI 命令行工具，(2) Python 代码直接调用 `PaperTrader` 类。

---

## 模块说明

| 文件/目录 | 说明 |
|-----------|------|
| `paper_trader.py` | `PaperTrader` 类 — 模拟盘持仓管理，追踪净值、成本、交易流水 |
| `risk_monitor.py` | 风险预警系统 — 检测回撤超限、集中度超标、因子失效 |
| `portfolio/` | 持仓和交易数据（JSON/CSV，不入 git） |
| `signals/` | 每日选股信号输出（JSON，不入 git） |

---

## 快速开始（6步）

### 1. 配置本地数据目录

```bash
cp config/config.example.yaml config/config.yaml
```

编辑 `config/config.yaml`，确保 `phase5.local_data_dir` 指向你的本地行情数据目录：

```yaml
phase5:
  local_data_dir: "/path/to/your/data"  # 改为你的本地数据路径
  signal_n_stocks: 30                   # 每次信号选股上限
  min_listing_days: 60                  # 最小上市天数
  min_price: 2.0                        # 最低股价（剔除仙股）
```

### 2. 安装依赖

```bash
pip install -e .
python -c "from live.paper_trader import PaperTrader; print('✅ 模块加载成功')"
```

### 3. 生成选股信号

```bash
python -m pipeline.cli signal --date 2026-03-20
```

输出示例：
```
==================================================
日期：2026-03-20
选股数量：25 只
==================================================

股票代码       综合评分
---
600036         0.7523
000858         0.6891
...

✅ 信号已保存到 live/signals/2026-03-20.json
```

### 4. 执行调仓

```bash
python -m pipeline.cli rebalance --date 2026-03-20
```

输出示例：
```
正在执行 2026-03-20 调仓...
✅ 调仓完成：25 只股票，日期 2026-03-20
```

### 5. 查看当前持仓

```bash
python -m pipeline.cli positions
```

输出示例：
```
==================================================
当前持仓
==================================================

股票代码       持仓数量      成本价     当前价
---
600036         100          15.25      15.50
000858         200          8.50       8.45
...
```

### 6. 查看模拟盘绩效

```bash
python -m pipeline.cli performance
```

输出示例：
```
==================================================
模拟盘绩效
==================================================

  总收益率        : +5.32%
  年化收益率      : +18.50%
  夏普比率        : 0.8542
  最大回撤        : -8.23%
  交易笔数        : 42
  运行天数        : 180
```

---

## CLI 命令完整列表（7 条）

### 1. `signal` — 生成每日选股信号

**功能**：基于因子评分生成选股标的，输出信号文件和摘要表格。

```bash
# 生成指定日期的信号（必须是数据中存在的交易日）
python -m pipeline.cli signal --date 2026-03-20

# 如果不指定日期，默认为今日
python -m pipeline.cli signal
```

**输出文件**：
- `live/signals/2026-03-20.json` — 选股标的和评分

**失败诊断**：
- "无法加载 2026-03-20 的行情数据" → 该日期在本地数据中不存在或缺失，改用其他日期
- "过滤统计" 中剔除了大量股票 → 检查 config.yaml 的过滤参数（min_listing_days、min_price 等）

---

### 2. `rebalance` — 执行调仓操作

**功能**：先生成信号，再根据当日价格调整持仓至目标权重。

```bash
# 执行调仓（必需 --date 参数）
python -m pipeline.cli rebalance --date 2026-03-20
```

**关键步骤**：
1. 调用 signal 生成目标选股标的
2. 从本地数据加载指定日期的收盘价
3. 调用 `PaperTrader.rebalance()` 执行买卖

**输出文件**：
- `live/portfolio/positions.json` — 调仓后的持仓快照
- `live/portfolio/trades.json` — 新增交易记录

**失败诊断**：
- "无法加载 {date} 的收盘价，调仓中止" → 本地数据中缺少该日期，改用其他日期
- 调仓完成但持仓未更新 → 检查 positions.json 和 trades.json 是否有写入权限

---

### 3. `positions` — 查看当前持仓

**功能**：打印当前的股票持仓和现金余额。

```bash
python -m pipeline.cli positions
```

**输出格式**：
```
股票代码       持仓数量      成本价     当前价
```

**返回数据来源**：从 `live/portfolio/positions.json` 读取

**失败诊断**：
- "当前无持仓（模拟盘尚未开始调仓）" → 正常，说明从未执行过 rebalance
- positions.json 文件损坏 → 删除并重新运行 rebalance

---

### 4. `performance` — 查看模拟盘绩效

**功能**：计算并显示净值、收益率、风险指标等。

```bash
python -m pipeline.cli performance
```

**输出指标**：
| 指标 | 说明 |
|------|------|
| 总收益率 | 从初始资金到现在的累计收益 |
| 年化收益率 | 按年化假设的收益率 |
| 夏普比率 | 风险调整后的收益（>0.8 为良好） |
| 最大回撤 | 历史最高点到低点的百分比跌幅 |
| 交易笔数 | 历史总交易次数 |
| 运行天数 | 从初始化到现在的交易日天数 |

**数据来源**：从 `live/portfolio/nav.csv` 和 positions.json 计算

---

### 5. `factor-health` — 因子健康度检查

**功能**：评估因子的实际有效性，报告 IC（Information Coefficient）衰减等问题。

```bash
python -m pipeline.cli factor-health
```

**输出格式**：
```
因子                 近期IC均值       状态
---
momentum_factor      0.0523           healthy
value_factor         0.0234           warning
```

**失败诊断**：
- "factor_snapshot 目录为空" → 需要先运行多次 signal 生成快照数据
- 所有因子都显示 "nan" → 因子计算模块中有错误，检查 pipeline/factor_monitor.py

---

### 6. `weekly-report` — 生成每周周报

**功能**：汇总周度持仓变化、收益、风险指标等。

```bash
# 生成指定周的报告（格式 YYYY-Www，如 2026-W12）
python -m pipeline.cli weekly-report --week 2026-W12

# 如果不指定，生成当前周的报告
python -m pipeline.cli weekly-report
```

**输出文件**：
- `journal/weekly/2026-W12.md` — Markdown 格式周报

**报告内容**：
- 周度交易概览
- 持仓变化统计
- 周度回报和夏普比率
- 风险预警摘要

---

### 7. `risk-check` — 运行风险预警检查

**功能**：监控当前持仓的风险指标，实时预警。

```bash
python -m pipeline.cli risk-check
```

**输出示例**：
```
==================================================
风险检查报告
==================================================

✅ 当前无风险预警
```

或：
```
🟡 [warning] 最大回撤已达 -8.2%，超过警线 -5.0%
🔴 [critical] 单只股票 600036 占比 16.5%，超过限额 15.0%
```

**监控维度**：
| 维度 | 默认阈值 | 说明 |
|------|----------|------|
| 最大回撤 | -5% (warning) / -10% (critical) | 净值从最高点回撤 |
| 单股集中度 | 15% | 单只股票占组合比例 |
| 行业集中度 | 30% | 单个行业占组合比例 |
| 因子 ICIR | 0.1 | 因子信噪比过低 |

---

## 预期输出目录结构

运行 CLI 命令后，会自动生成以下文件：

```
live/
├── README.md              # 本文档
├── paper_trader.py        # PaperTrader 类
├── risk_monitor.py        # 风险监控
├── portfolio/             # 模拟盘持仓和交易数据（不入 git）
│   ├── positions.json     # 当前持仓快照 {symbol: {shares, cost_price, current_price}}
│   ├── trades.json        # 历史交易流水 [{date, symbol, qty, price, side, ...}]
│   └── nav.csv            # 净值曲线 (date, nav)
└── signals/               # 每日选股信号（不入 git）
    ├── 2026-03-20.json    # {picks: [...], scores: {...}, excluded: {...}}
    ├── 2026-03-21.json
    └── ...

journal/weekly/           # 周报（不入 git）
├── 2026-W12.md
├── 2026-W13.md
└── ...
```

---

## 常见问题与排查

### 1. "本地数据目录未配置或不存在"

**症状**：
```
❌ 执行失败：无法读取本地数据目录
```

**原因**：
- `config/config.yaml` 中 `phase5.local_data_dir` 未设置或路径不存在

**修复步骤**：
```bash
# 确保 config.yaml 存在
cp config/config.example.yaml config/config.yaml

# 编辑配置，指向你的本地行情数据目录
nano config/config.yaml
# phase5:
#   local_data_dir: "/path/to/your/csv/data"

# 验证路径存在且包含 CSV 文件
ls -la /path/to/your/csv/data | head
```

---

### 2. "指定日期的数据不存在"

**症状**：
```
❌ 执行失败：无法加载 2026-03-20 的收盘价
```

**原因**：
- 指定的日期不在本地数据中（可能是周末或非交易日）
- 该日期的 CSV 数据文件缺失或损坏

**修复步骤**：
```bash
# 查看本地数据包含哪些日期
ls -la /path/to/your/csv/data | grep -E "\.csv$" | head -5

# 改用已有日期重试
python -m pipeline.cli signal --date 2026-03-19
```

---

### 3. "无法加载选中股票的价格数据"

**症状**：
```
❌ 执行失败：无价格数据用于调仓，中止
```

**原因**：
- signal 生成的标的中，某些股票在指定日期没有有效的收盘价
- 可能原因：停牌、退市、新股（未上市）

**修复步骤**：
```bash
# 检查数据完整性
python -m pipeline.data_checker

# 输出示例：
# ✅ 数据完整性检查
# 最新日期：2026-03-19
# 沪深300 覆盖率：98.2%
# ...

# 如果覆盖率过低，改用其他日期或检查数据源
```

---

### 4. "NAV 一致性警告"

**症状**：
```
[PaperTrader WARNING] 状态不一致：持仓推算 NAV=1,050,000.00，
csv 记录 NAV=1,000,000.00，偏差=5.00%（可能来自上次运行的过时数据）
```

**原因**：
- 首次运行模拟盘（正常）
- 上次调仓后，current_price 未及时更新
- 数据源价格变化导致的差异

**处理方式**：
- 若是首次运行，这是正常的初始化警告，可忽略
- 若偏差 > 5%，检查 positions.json 中的 current_price 是否陈旧
  ```bash
  # 手动更新当日收盘价
  python -m pipeline.cli positions  # 查看当前状态
  python -m pipeline.cli rebalance --date {today}  # 重新调仓会更新价格
  ```

---

### 5. "因子健康度检查返回空报告"

**症状**：
```
==================================================
因子健康度报告
==================================================

（无输出）
```

**原因**：
- `live/factor_snapshot/` 目录为空或不存在
- 需要多次运行 signal 才能积累因子计算结果

**修复步骤**：
```bash
# 运行多次 signal 以生成快照数据（至少 10+ 次）
for date in 2026-03-10 2026-03-11 2026-03-12 ... 2026-03-20; do
  python -m pipeline.cli signal --date $date
done

# 然后重新运行因子检查
python -m pipeline.cli factor-health
```

---

## Python API 直接调用（高级用法）

除了 CLI 命令，还可以在 Python 代码中直接使用 `PaperTrader` 类：

```python
from live.paper_trader import PaperTrader
from live.risk_monitor import check_risk_alerts

# 初始化交易器（默认 100 万初始资金）
trader = PaperTrader(initial_capital=1_000_000)

# 查看当前持仓
positions = trader.get_current_positions()
print(positions)
# 输出：{'600036': {'shares': 100, 'cost_price': 15.25, 'current_price': 15.50}, ...}

# 执行调仓
picks = ['600036', '000858', '000333']
prices = {'600036': 15.50, '000858': 8.45, '000333': 12.30}
trader.rebalance(picks, prices, '2026-03-20')

# 获取绩效报告
perf = trader.get_performance()
print(f"年化收益率: {perf['annualized_return']:.2%}")
print(f"最大回撤: {perf['max_drawdown']:.2%}")
print(f"夏普比率: {perf['sharpe']:.4f}")

# 运行风险检查
alerts = check_risk_alerts(trader)
for alert in alerts:
    print(f"[{alert['level']}] {alert['msg']}")
```

---

## 与回测结果对标

完成模拟盘运行后，用 `research/notebooks/13_live_simulation.ipynb` 对标：
- **模拟盘净值** vs **回测净值** — 验证是否一致
- **实际交易成本** vs **假设成本** — 评估滑点和手续费影响
- **选股覆盖率** — 检查信号标的是否稳定

---

## 数据刷新频率

| 文件 | 更新时机 | 说明 |
|------|----------|------|
| `positions.json` | 每次 rebalance 后 | 持仓快照 |
| `trades.json` | 每次调仓操作后 | 累积交易记录 |
| `nav.csv` | 每次 rebalance 或查看 performance 时 | 净值曲线 |
| `signals/{date}.json` | 每次运行 signal 后 | 当日选股结果 |

---

## 故障排除 Checklist

- [ ] `config/config.yaml` 已创建且 `local_data_dir` 指向有效路径
- [ ] `pip install -e .` 已成功运行
- [ ] 本地数据目录包含 CSV 格式行情数据（符合 `utils/local_data_loader.py` 的格式）
- [ ] CLI 命令中的日期是实际的交易日（周一～周五，非假期）
- [ ] `live/portfolio/` 和 `live/signals/` 目录有写入权限
- [ ] 最近一次 rebalance 成功完成（检查 positions.json 的修改时间）
