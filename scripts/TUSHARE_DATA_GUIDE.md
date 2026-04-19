# Tushare 数据下载指南

## 快速开始

```bash
# 1. 配置 token（只需做一次）
echo "TUSHARE_TOKEN=<你的token>" > .env

# 2. 安装依赖
pip install tushare==1.4.21 pandas pyarrow

# 3. 全量下载（约 1.6 GB，3线程约 1.5 小时）
python scripts/bulk_download_tushare.py

# 4. 只下载部分模块（例如只要财务数据和每日指标）
python scripts/bulk_download_tushare.py --modules financial daily_basic
```

---

## 数据模块说明

### 📊 `financial` — 财务四张表（最重要）

**包含什么**
| 表 | 关键字段 | 用途 |
|----|---------|------|
| 现金流量表 | `n_cashflow_act`（经营现金流）, `f_ann_date`（实际公告日） | 盈利质量因子：CFO/NI |
| 利润表 | `n_income_attr_p`（归母净利润）, `revenue`（营收） | 盈利因子、盈利增速 |
| 资产负债表 | `total_assets`（总资产）, `total_liab`（负债）, `accounts_receiv`（应收） | 应计项目、杠杆因子 |
| 财务指标 | `roe`, `roa`, `grossprofit_margin`, `debt_to_assets`, `fcff` | 质量因子，直接可用 |

**为什么重要**：含 `f_ann_date`（实际公告日），可以精确处理前视偏差，比 shift(1) 准确 1~3 个月。

**单股大小**：约 70 KB（四张表合计）  
**全量大小**：约 370 MB  
**下载时间**：约 27 分钟（3线程）

---

### 📈 `daily_basic` — 每日行情指标

**包含什么**
| 字段 | 说明 |
|------|------|
| `pe_ttm` | 滚动市盈率（TTM） |
| `pb` | 市净率 |
| `ps_ttm` | 市销率 |
| `total_mv` | 总市值（万元） |
| `circ_mv` | 流通市值（万元） |
| `turnover_rate` | 换手率（%） |
| `dv_ratio` | 股息率（%） |

**为什么重要**：做价值因子（EP/BP）和市值中性化的必备数据，现在项目里缺这块。

**单股大小**：约 41 KB（10年日频）  
**全量大小**：约 220 MB  
**下载时间**：约 27 分钟（3线程）

---

### 💰 `moneyflow` — 个股资金流向

**包含什么**
| 字段 | 说明 |
|------|------|
| `buy_lg_amount` | 大单买入额（万元，>50万） |
| `sell_lg_amount` | 大单卖出额 |
| `buy_md_amount` | 中单买入额（10~50万） |
| `net_mf_amount` | 净流入总额 |

**为什么重要**：可以构造「机构资金净流入/流通市值」因子，作为北向资金历史数据的替代。大单净流入与机构行为高度相关。

**单股大小**：约 38 KB（5年日频）  
**全量大小**：约 200 MB  
**下载时间**：约 27 分钟（3线程）

---

### 🏦 `margin` — 融资融券

**包含什么**
| 字段 | 说明 |
|------|------|
| `rzye` | 融资余额（元） |
| `rqye` | 融券余额（元） |
| `rzmre` | 融资买入额 |
| `rqmcl` | 融券卖出量 |

**用途**：「融资余额/流通市值」反映散户杠杆程度（高 = 过热），可做反向因子。

**全量大小**：约 100 MB

---

### 🌏 `northbound` — 北向持股个股

**包含什么**：每日外资在每只股票的持股数量、持股占A股比例

**用途**：构造 `Δholding_ratio/N` 北向增减持因子，有完整历史，无需每日积累。

**注意**：只有约 1500 只纳入陆股通的股票有数据，其余返回空（正常）。

**全量大小**：约 10 MB

---

### 📋 `top_list` — 龙虎榜

**包含什么**
- `top_list_YYYYMMDD.parquet`：龙虎榜个股明细（涨跌幅、净买入额）
- `top_inst_YYYYMMDD.parquet`：机构席位明细（机构买卖金额）

**用途**：event_driven 策略，机构席位净买入为正向信号。

**全量大小**：约 30 MB（2015-2025）

---

### 📊 `index_data` — 指数行情

下载的指数：
| 代码 | 名称 |
|------|------|
| 000300.SH | 沪深300 |
| 000905.SH | 中证500 |
| 000852.SH | 中证1000 |
| 000016.SH | 上证50 |
| 399006.SZ | 创业板指 |
| 000688.SH | 科创50 |

**用途**：regime 判断（HS300 < MA120）、基准收益、beta 计算。

---

### 其他模块

| 模块 | 用途 | 大小 |
|------|------|------|
| `adj_factor` | 复权因子，价格还原 | 70 MB |
| `dividend` | 股息率因子 | 10 MB |
| `share_float` | 解禁压力因子 | 10 MB |
| `holder_num` | 股东人数/筹码集中度 | < 5 MB |
| `block_trade` | 大宗折价因子 | 30 MB |
| `repurchase` | 回购事件驱动 | 5 MB |
| `index_weight` | 指数成分权重历史 | 5 MB |
| `northbound_agg` | 北向每日汇总（大盘择时） | < 1 MB |

---

## 数据存储结构

```
data/raw/tushare/
├── financial/
│   ├── cashflow_000001.parquet      ← 每只股票一个文件
│   ├── income_000001.parquet
│   ├── balancesheet_000001.parquet
│   └── fina_indicator_000001.parquet
├── daily_basic/
│   └── 000001.parquet
├── moneyflow/
│   └── 000001.parquet
├── margin/
│   └── 000001.parquet
├── northbound/
│   └── 000001.parquet               ← 无数据的股票不会有文件
├── dividend/
│   └── 000001.parquet
├── share_float/
│   └── 000001.parquet
├── holder_num/
│   └── 000001.parquet
├── adj_factor/
│   └── 000001.parquet
├── events/
│   ├── top_list_20241231.parquet    ← 按日期
│   ├── top_inst_20241231.parquet
│   └── block_trade_202412.parquet  ← 按月
├── repurchase.parquet               ← 全市场合并
├── northbound_agg.parquet
├── index_daily_000300.parquet       ← 按指数代码
└── index_weight_399300.parquet
```

---

## 读取数据示例

```python
import pandas as pd
from pathlib import Path

DATA = Path("data/raw/tushare")

# 读某只股票的每日PE/PB/市值
df = pd.read_parquet(DATA / "daily_basic/000001.parquet")
print(df[["trade_date", "pe_ttm", "pb", "circ_mv"]].tail())

# 读现金流量表（含实际公告日）
cf = pd.read_parquet(DATA / "financial/cashflow_000001.parquet")
print(cf[["end_date", "f_ann_date", "n_cashflow_act"]].tail())

# 批量读取所有股票的财务指标，拼成宽表
import glob
all_fi = pd.concat(
    [pd.read_parquet(f) for f in glob.glob(str(DATA / "financial/fina_indicator_*.parquet"))],
    ignore_index=True
)
roe_wide = all_fi.pivot(index="end_date", columns="ts_code", values="roe")

# 读北向资金汇总（大盘择时）
nb = pd.read_parquet(DATA / "northbound_agg.parquet")
print(nb.tail())

# 读龙虎榜（某天）
tl = pd.read_parquet(DATA / "events/top_list_20241231.parquet")
```

---

## 注意事项

1. **断点续传**：脚本会跳过已存在且非空的文件，中断后重跑不会重复下载
2. **限速**：每次 API 调用间隔 0.25 秒，不要将 `--workers` 设超过 5
3. **北向数据**：只有纳入陆股通的约 1500 只股票有数据，其他返回空属正常
4. **财务数据时间**：部分早期上市公司的财务数据可能从 2005 年甚至更早开始
5. **Token 有效期**：下载完后数据在本地，token 过期不影响已下载数据的使用
