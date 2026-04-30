# 龙虎榜 net_rate event study — Issue #55, A 路第一步

_2026-04-29 — 结论: 历史 alpha 真但已被磨平, 现况不直接可 deploy. 不杀方向, 但要 pivot 到 subgroup-on-recent 二阶段_

---

## TL;DR

**LHB net_rate (大单净买入 / 流通市值) 在 quintile spread 测试下显示信号真实存在但 alpha decayed:**

- 2015-2019: T+5 spread Q5-Q1 = **+17.7%** net (massive)
- 2020-2023: T+5 spread = **+2.9%** net
- **2024-2026: T+5 spread = +0.08% net (t 2.37 勉强显著), T+10 = -0.02% (FAIL)**

按 framework Live-Tier 1 OOS 门 (允许 ≤1 FAIL_NEG_SHARPE + 失败窗 < 0.3% NAV), 技术上 T+10 那个 FAIL 失败窗 net × 5% × 0.5 = 0.0006% NAV << 0.3%, 形式上能过. 但 T+5 net +0.08% 在 cost 后接近零, real-world friction 会把它吞掉. **不直接进 Tier 0 paper smoke 当 candidate**.

**不杀 A 路, 不杀龙虎榜方向**. 下一步 (新 issue) 跑 subgroup-on-recent: 看 multi_day reason × 2024-2026 这个组合是否仍有 edge.

---

## 数据 + 方法

- **Source**: `data/raw/tushare/events/top_list_*.parquet`, 2015-01-06 ~ 2026-04-17, 2521 文件, dedup 后 164k unique (date,ts_code,reason) 行
- **Per-event aggregate**: 同 (date, symbol) 多 reason 取 |net_amount| 最大那条作主信号 → 129,674 unique events
- **Universe**: 5128 stocks (跨 11 年所有曾上榜的股票)
- **Price panel**: `utils.local_data_loader.load_adj_price_wide` (复权累积), shape 2761 days × 5128 symbols
- **Abn return**: `pct_change - mkt_ew_mean` (简单 market-adj, 类似 PEAD event_study.py), clip ±25% 防 corp action 噪音
- **Event window**: T-5 ~ T+30 相对日

### Lookahead 处理 (关键)

top_list 在 T 日 **盘后 18:00** 披露. T close 不可下单, 最早 entry 是 T+1 open.

**两种报告口径**:
- **CONSERVATIVE (主报告)**: 累计 ret over rel_day [2..H+1]. 假设 entry 在 T+1 close, exit 在 T+H+1 close. 跳过 T close → T+1 open 的 overnight gap (不可收). 这是 tradeable 的下界.
- **NAIVE 上界**: 累计 over [1..H], 包含 T close → T+1 close 全段 (含 overnight gap).

NAIVE 数字比 CONSERVATIVE 大约 2x — overnight gap 占了一半 alpha. **任何只看 NAIVE 的报告都过度乐观**.

### Cost
- 双边 0.5% per Live-Tier 1 标准 (framework v1)
- = 0.25% per side, 一次 round trip 0.5% net 扣

### 时间切片 (RIAD Fold convention)
- T1: 2015-2019 (long history)
- T2: 2020-2023 (mid)
- T3: 2024-2026 (freshest OOS)

---

## 结果

### 全样本 (CONSERVATIVE, skip overnight gap)

| Horizon | gross spread | net spread | t-stat | p-value | n_events |
|---|---|---|---|---|---|
| T+1 hold | +3.03% | **+2.53%** | +59.3 | 0.0000 | 129,660 |
| T+5 hold | +8.81% | **+8.31%** | +61.1 | 0.0000 | 129,674 |
| T+10 hold | +11.54% | **+11.04%** | +56.6 | 0.0000 | 129,674 |

### 全样本 (NAIVE, 含不可收的 overnight gap, 仅上界)

| Horizon | gross | net | t |
|---|---|---|---|
| T+1 | +6.11% | +5.61% | +117.7 |
| T+5 | +13.93% | +13.43% | +92.5 |
| T+10 | +17.30% | +16.80% | +80.6 |

NAIVE - CONSERVATIVE 差 = overnight gap 部分 ≈ 3-6% per horizon. **就是策略不可收的部分**.

### 时间切片 (CONSERVATIVE)

| Slice | T+1 net | T+5 net | T+10 net | T+10 verdict |
|---|---|---|---|---|
| **T1 2015-2019** | +4.95% | +17.67% | +23.97% | PASS (mega) |
| **T2 2020-2023** | +0.92% | +2.90% | +3.53% | PASS |
| **T3 2024-2026** | **+0.65%** | **+0.08%** (t 2.37) | **-0.02%** (t 1.59) | **FAIL** |

**关键观察**: 2015-2019 时期 T+10 spread 24% — 这是 A 股 2015 牛熊 + 散户主导市场 + 量化参与度低的时代红利. 2024 后 alpha 几乎归零, 一致性符合"老 anomaly 被新参与者 arbitrage 平"的市场效率假说.

### Reason subgroup (全样本 T+5)

| Reason 大类 | net spread | t | n_events |
|---|---|---|---|
| daily_up (涨幅榜) | +2.57% | +10.8 | 21,750 |
| daily_down (跌幅榜) | +2.30% | +9.6 | 12,233 |
| daily_range (振幅榜) | **-0.88%** | -0.86 | 6,993 |
| daily_turnover (换手榜) | -0.38% | +0.48 | 20,554 |
| **multi_day (3日累计)** | **+17.10%** | +54.3 | 36,037 |
| other | +10.99% | +37.4 | 32,107 |

`multi_day` 是 alpha 主源 (3-日累计 30% 偏离的股票). 但全样本数字被 2015-2019 数据拉爆, **必须分时间切片再看 multi_day 才知道现况**. 这是下一步的核心问题.

`daily_range` / `daily_turnover` 全样本就接近零 — 振幅榜 / 换手榜 单独不是好 signal source.

---

## 判定 (按 Live-Tier framework)

### 是否可进 Tier 0 paper smoke?

**不直接可进**, 理由:

- T3 (2024-2026) T+5 net +0.08% 接近零, real-world slippage / 借券难/T+1 等 friction 会把这个数字拉负
- T+10 在 T3 已经 net 负 (-0.02%, t 1.59 不显著)
- Live-Tier 1 入门 backtest sharpe > 0.5 标准 — 这个 cross-event spread 不是 sharpe (没序列), 但若把每个事件当独立观测 sharpe ≈ t / √n_T3 = 10.4 / √14k ≈ 0.09 — 远低于 0.5 floor

### 是否杀 LHB 方向 / 杀 A 路?

**不杀**. 理由:

- daily_up + daily_down 全样本 PASS (+2.5%/+2.3% T+5), reason 类别 + 时间切片 cross-tab 没跑过, 可能特定 subgroup × recent 仍有 alpha
- multi_day 全样本 +17% T+5 — 即使 2024-2026 衰减, 仍可能保留 5% 量级
- 龙虎榜数据 + 价格 + 中性化 infra 都已 reusable, sunk cost 已花
- A 路本身是 4 个 candidates (LHB / 回购 / 减持 / 调研), LHB 一个走向不出货不代表 A 路死

### 下一步 (新 Issue, 不在本 issue 范围)

**Phase 2**: subgroup × recent 二阶段 study
- multi_day reason × 2024-2026 的 spread 还有多少
- daily_up reason × 2024-2026 的 spread 还有多少
- 加 net_rate magnitude filter (e.g. net_rate > 5%) — 极端事件子集是否仍有 edge
- 若 subgroup × recent 也 < 0.5% net → 杀 LHB 方向, 转 A 路下一个 candidate (回购公告)

---

## 红线检查

按 Issue #55 完成标准的红线:

- ✅ no lookahead: rel_day=1 含 overnight gap (T close 不可下单), 已用 CONSERVATIVE (skip rel_day=1) 报主结果
- ⚠ 涨跌停 next day 不能开仓: 没显式过滤. 极端 net_rate Q5 大概率 T+1 仍涨停, 导致部分事件不可入. 这会让 actual 比 backtest 更差. 没影响"alpha 已经死"的结论, 但如果 subgroup × recent 真有 signal, Phase 2 必须过滤
- ✅ 不调任何参数 (quintile / horizon / cost / 时间切片) 凑显著性
- ✅ 全样本 + 时间分段, T3 的 T+10 FAIL 已诚实记录, 没掩盖

---

## 数据/代码出处

- 脚本: `research/event_alpha/lhb_t1_event_study.py`
- 复用: `utils.local_data_loader.load_adj_price_wide`, `research/event_driven/event_study.py` 的 compute_abn_returns 模式
- 结果: `research/event_alpha/lhb_event_study_results.json` (.gitignored)
- 图: `research/event_alpha/lhb_event_study.png` (.gitignored)
- 数据: SSD parquet `data/raw/tushare/events/top_list_*.parquet` (2521 文件)

— 记录: jialong
