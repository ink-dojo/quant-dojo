# 免费数据接入方案 — 像 TradingView 一样

> 2026-03-25

## 当前状态

| 数据 | 来源 | 状态 |
|------|------|------|
| 日线 OHLCV | BaoStock / AkShare | ✅ 已接入 |
| PE/PB/PS/PCF | 本地 CSV | ✅ 已有 |
| 行业分类 | BaoStock | ✅ 已接入 |
| 换手率 | 本地 CSV | ✅ 已有 |
| 实时行情 | - | ❌ 未接入 |
| 分钟线 | - | ❌ 未接入 |
| 北向资金 | - | ❌ 未接入 |
| 龙虎榜 | - | ❌ 未接入 |
| 基金持仓 | - | ❌ 未接入 |
| 财务报表 | - | ❌ 未接入 |

## 免费数据源全景

### Tier 1：无需注册、无限制

| 来源 | 数据类型 | 接口 | 限制 |
|------|---------|------|------|
| **BaoStock** | 日线/分钟线/财务/行业/成分股 | TCP Socket | 无限制，但串行慢 |
| **Sina Finance** | 实时行情（OHLCV + 买卖盘） | HTTP GET | 无 key，极快 |
| **Tencent Finance** | 实时行情 + 分钟线 | HTTP GET | 无 key |

### Tier 2：免费但偶有限流

| 来源 | 数据类型 | 限制 |
|------|---------|------|
| **AkShare** | 几乎所有（东方财富后端） | 偶尔连接拒绝 |
| **Ashare** | 日线/分钟线（Sina+Tencent） | 单文件，无限流 |

### Tier 3：免费注册、有配额

| 来源 | 数据类型 | 免费额度 |
|------|---------|---------|
| **Tushare** | 全量数据 | 200次/分钟（积分制） |

## 缺失数据的免费获取方案

### 1. 分钟线数据（解锁：CPV、聪明钱、APM 完整版、日内动量）

**方案 A：BaoStock 分钟线**
```python
import baostock as bs
bs.login()
rs = bs.query_history_k_data_plus("sh.600000",
    "date,time,open,high,low,close,volume",
    start_date="2026-03-20", end_date="2026-03-20",
    frequency="30")  # 支持 5/15/30/60 分钟
```
- 免费，无限制
- 历史数据从 2006 年开始
- 缺点：串行慢，需要逐只拉取

**方案 B：Tencent 分钟线**
```python
# 获取最近 N 天的 1 分钟线
url = f"https://web.ifzq.gtimg.cn/appstock/app/minute/query?_var=min_data_{code}&code={code}"
# 获取 5 分钟 K 线
url = f"https://web.ifzq.gtimg.cn/appstock/app/kline/kline?param={code},5,,,320,qfq"
```
- 无 key，速度快
- 只有最近一段时间的数据

**建议**：BaoStock 用于历史分钟线回填，Tencent 用于每日增量更新。

### 2. 北向资金（解锁：北向资金择时、聪明钱 2.0）

**方案：AkShare**
```python
import akshare as ak
# 北向资金每日净流入
df = ak.stock_hsgt_north_net_flow_in_em()
# 个股北向持仓
df = ak.stock_hsgt_hold_stock_em(market="沪股通")
```
- 完全免费
- 但依赖东方财富接口（我们当前连不上）
- **备选**：通过 Sina 爬虫获取 `https://vip.stock.finance.sina.com.cn/q/go.php/vComSKHold/kind/hgt/`

### 3. 龙虎榜（解锁：机构席位、游资行为、特征分布择时）

**方案：AkShare**
```python
df = ak.stock_lhb_detail_em(start_date="20260320", end_date="20260324")
```
- 东方财富免费接口
- 包含：日期、股票、营业部、买入/卖出金额

### 4. 基金持仓（解锁：基金重仓超配因子、来自优秀基金经理的超额）

**方案：AkShare**
```python
# 公募基金持仓
df = ak.fund_portfolio_hold_em(symbol="000001", date="2025")
```
- 季报频率（每季度更新）
- 免费

### 5. 财务报表（解锁：企业生命周期、ROE、营收增速）

**方案 A：BaoStock 财务数据**
```python
bs.query_profit_data(code="sh.600000", year=2025, quarter=3)  # 盈利能力
bs.query_growth_data(code="sh.600000", year=2025, quarter=3)  # 成长能力
bs.query_balance_data(code="sh.600000", year=2025, quarter=3) # 偿债能力
```
- 完全免费
- 覆盖所有 A 股
- 字段：ROE、净利润增长、营收增长、资产负债率等

**方案 B：AkShare**
```python
df = ak.stock_financial_analysis_indicator(symbol="600000")
```

### 6. 分析师一致预期（解锁：金股增强、预期修正因子）

**方案：AkShare**
```python
df = ak.stock_profit_forecast_em(symbol="600000")  # 盈利预测
df = ak.stock_analyst_rank_em()  # 分析师排名
```
- 来自东方财富
- 免费但依赖网络

### 7. 实时行情（解锁：盘中监控、日内策略）

**方案：Sina Finance API（已验证可用）**
```python
# 批量获取：每次最多 800 只
url = "https://hq.sinajs.cn/list=sh600000,sz000001,..."
# 返回：名称、开盘、昨收、现价、最高、最低、买一到买五、卖一到卖五、成交量、成交额、时间
```
- 完全免费，无 key
- 可轮询（每 3 秒一次不会被封）
- 适合做盘中信号监控

## 整合方案：构建"免费 TradingView"

### 架构

```text
providers/
  base.py              -- 已有
  akshare_provider.py  -- 已有（日线主力，偶尔不可用）
  baostock_provider.py -- 已有（日线备选 + 分钟线 + 财务）
  sina_provider.py     -- 新建（实时行情 + 北向资金爬虫）
  tencent_provider.py  -- 新建（分钟线增量）

pipeline/
  data_update.py       -- 已有（日线更新）
  minute_update.py     -- 新建（分钟线更新）
  realtime_quote.py    -- 新建（实时行情轮询）
  fund_data.py         -- 新建（基金持仓/北向/龙虎榜）
```

### 实施优先级

| 阶段 | 数据 | 解锁的因子/策略 | 难度 |
|------|------|----------------|------|
| 1 | BaoStock 财务数据 | ROE/营收增速/企业生命周期 | 低 |
| 2 | BaoStock 分钟线 | CPV/聪明钱/APM完整版 | 中 |
| 3 | Sina 实时行情 | 盘中监控/日内信号 | 低 |
| 4 | AkShare 北向/龙虎榜 | 北向资金因子/机构行为 | 中（需网络通） |
| 5 | AkShare 基金持仓 | 基金超配因子 | 中（需网络通） |
| 6 | Tencent 分钟线增量 | 日内动量策略 | 中 |

### 关键原则

1. **永远不付费** — 所有数据都有免费来源
2. **多源冗余** — 每种数据至少 2 个来源，主备切换
3. **本地缓存优先** — 拉一次存 parquet，不重复拉
4. **provider 抽象** — 上层代码不直接碰任何数据源 API

## 与 TradingView 的差异

| TradingView | quant-dojo |
|-------------|-----------|
| 实时图表 | CLI + Dashboard（够用） |
| 全球市场 | 只做 A 股（专注） |
| 1 分钟线 | BaoStock/Tencent（免费） |
| 基本面数据 | BaoStock 财务 + CSV PE/PB |
| 技术指标 | 自建因子库（更专业） |
| 回测引擎 | 自建（更灵活） |
| 付费 Pro 版 | 完全免费 |

**结论：完全可以做到 TradingView 免费版的 80% 数据覆盖，且回测能力远超 TradingView。**
