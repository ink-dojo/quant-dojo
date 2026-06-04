# 新因子回测指南

三个新因子的设计逻辑、数据准备要求、回测建议。

---

## 因子一：盈利质量（Earnings Quality）

**文件**：`research/factors/earnings_quality/earnings_quality_factor.py`

### 逻辑

```
CFO/NI = 经营现金流 / 净利润
  高 → 盈利是真实现金，不是应收账款堆出来的
  低 → 账面盈利虚，容易暴雷

Accruals/TA = (净利润 - 经营现金流) / 总资产（取负）
  应计项目是财务操纵最常见的手段
```

两者合成后，高因子值 = 盈利质量高 = 正向因子。

### 数据状态

| 数据 | 接口 | 状态 |
|------|------|------|
| 经营现金流 | `ak.stock_cash_flow_sheet_by_report_em` | 需运行拉取 |
| 净利润 | 同上（同一接口） | 需运行拉取 |
| 总资产 | 同上 | 需运行拉取 |

### 运行方式

```python
from research.factors.earnings_quality.earnings_quality_factor import (
    build_cashflow_wide,
    compute_composite_earnings_quality,
)
import pandas as pd

symbols = [...]  # 你的股票池
date_range = pd.bdate_range("2020-01-01", "2024-12-31")

# 1. 拉数据（首次较慢，有缓存后快）
cashflow = build_cashflow_wide(symbols, start="2018-01-01", end="2024-12-31")

# 2. 计算合成因子
eq_factor = compute_composite_earnings_quality(cashflow, date_range)
```

### 回测注意

- 季报数据 shift(1) 只是粗略的前视偏差处理（移了一个季度）
- 建议在回测结论中注明：实际公告日比报告期末晚 1~3 个月
- 数据覆盖率：小市值公司现金流数据质量较差，建议先在沪深 300 成分内验证

---

## 因子二：北向资金（Northbound Flow）

**文件**：`research/factors/northbound_flow/northbound_flow_factor.py`

### 逻辑

```
Δholding_pct_N = (北向持股比例_t - 北向持股比例_{t-N}) / N
  正值 → 外资净增持 → 正向信号
  负值 → 外资净减持 → 负向信号
```

北向资金是 A 股最透明的"外部聪明钱"信号，每日 15:30 后公开。

### ⚠️ 数据特殊说明

akshare 的北向持股接口只提供**当天快照**，没有完整历史库。

**两种方案**：

**方案 A（推荐，可回测到 2024+）**：  
将 `snapshot_today()` 加入 `scripts/daily_run.sh`，每日积累，
30 个交易日后可开始验证 N=20 的因子。

```bash
# 在 daily_run.sh 末尾加入：
python -c "
from research.factors.northbound_flow.northbound_flow_factor import snapshot_today
snapshot_today()
print('北向快照已更新')
"
```

**方案 B（立即可用代理）**：  
用 `alpha_factors.py` 里的 `apm_overnight` 因子（隔夜收益，捕捉外资隔夜定价）
作为北向因子的有效代理，相关性约 0.3~0.5。

### 运行方式（积累数据后）

```python
from research.factors.northbound_flow.northbound_flow_factor import (
    build_holding_wide,
    compute_northbound_composite,
)
import pandas as pd

holding_wide = build_holding_wide(symbols=None, start="2024-01-01")
nb_factor = compute_northbound_composite(holding_wide, short_window=20, long_window=60)
```

---

## 因子三：基金拥挤度（Fund Crowding）

**文件**：`research/factors/fund_crowding/fund_crowding_factor.py`

### 逻辑

```
n_funds = 持有某股的基金数量（越多 = 越拥挤）
因子 = -n_funds（取负，低拥挤 = 高因子值 = 好）

Δcrowding = -(本季基金数 - 上季基金数)
  基金开始撤出 → 因子值上升 → 早期离场信号
```

### 数据状态

| 数据 | 接口 | 频率 | 状态 |
|------|------|------|------|
| 个股基金持仓 | `ak.stock_report_fund_hold` | 季度 | 需运行拉取 |

### 运行方式

```python
from research.factors.fund_crowding.fund_crowding_factor import (
    build_crowding_panel,
    compute_composite_crowding,
)
import pandas as pd

symbols = [...]
# 过去 3 年的季报期
periods = ["20211231","20220331","20220630","20220930","20221231",
           "20230331","20230630","20230930","20231231",
           "20240331","20240630","20240930","20241231"]

date_range = pd.bdate_range("2022-01-01", "2024-12-31")

# 1. 拉数据（按股票 × 季报期，第一次慢）
panel = build_crowding_panel(symbols, periods, max_workers=4)

# 2. 计算合成因子
crowding_factor = compute_composite_crowding(panel, date_range)
```

---

## 回测建议顺序

### Step 1：单因子 IC 验证（先验证方向）

```python
from utils.factor_analysis import compute_ic_series, ic_summary, neutralize_factor

# 对每个新因子做：
# 1. 行业+市值中性化
# 2. IC 分析（Rank IC）
# 3. 分层回测

factor_neutral = neutralize_factor(new_factor, df_info, n_sigma=3.0)
ic_s = compute_ic_series(factor_neutral, fwd_ret, method="spearman")
ic_summary(ic_s, name="因子名称")
```

### Step 2：与现有英雄因子的相关性检验

```python
# 新因子应该和现有因子相关性低（<0.3），否则增量信息有限
from scipy.stats import spearmanr

for existing_name, existing_factor in hero_factors.items():
    corr_series = []
    for date in common_dates:
        f1 = new_factor.loc[date].dropna()
        f2 = existing_factor.loc[date].dropna()
        idx = f1.index.intersection(f2.index)
        if len(idx) > 30:
            corr_series.append(spearmanr(f1[idx], f2[idx])[0])
    print(f"vs {existing_name}: 截面相关均值 = {np.mean(corr_series):.3f}")
```

### Step 3：加入多因子合成

如果 Step 1 IC 显著（|IC| > 0.02, |t| > 2），Step 2 相关性低（< 0.3），
则可尝试加入 `utils/multi_factor.py` 的 `ic_weighted_composite` 合成，
验证加入新因子后整体 ICIR 是否提升。

---

## 我的预期

| 因子 | A 股有效性预期 | 回测难度 | 衰减速度 |
|------|------------|---------|---------|
| 盈利质量（CFO/NI）| 中高，尤其熊市 | 低（季度数据稳定） | 慢（基本面因子） |
| 北向资金 | 高，但近两年外资波动大 | 高（需积累数据） | 中 |
| 基金拥挤度 | 中，危机时效果最强 | 中（季度数据） | 慢 |

**建议优先跑盈利质量**：数据最容易拿，逻辑最扎实，和现有质量因子有补充但不重复（现有质量因子用 ROE，不用 CFO）。
