# 龙虎榜 net_rate event study — Issue #55, A 路第一步

_2026-04-29 — rev 2 (simplify review 后修 3 个 correctness bug + 抽 utils)_

> **Rev 2 关键变化** (vs rev 1):
> - **Cost 公式修了 2x under-count**. rev 1 `2 * cost_per_side = 0.5%` 只算 1 腿
>   round trip; long-short 是 2 腿 → 4 * cost_per_side = **1.0%**. 数字大幅变差.
> - **Categorize_reason 修复 ~30% 事件漏分类**. 新 wording variant `有价格涨跌幅
>   限制的...` / `非ST、*ST...` / `当日收盘价涨幅...` 现在能正确归类. other 从
>   32k → 0.5k. 新增 `nolimit` 类 (无涨跌停板, 即 ST / 北交所 / 退市过渡 / 上市初期).
> - **抽 utils/event_study.py** (`compute_event_abn_returns` 向量化 + `quintile_spread`
>   通用), A 路下 3 个 candidate (回购/减持/调研) 直接 import.
> - **向量化提速 ~30x**. iterrows + iloc → numpy fancy index, 1.5 min → 40 秒.

---

## TL;DR (rev 2)

**LHB net_rate signal 真实存在, 但 cost 修正后 + 时间切片显示 2024-2026 alpha 已转负, 主力 alpha 集中在 2015-2019 与 multi_day / nolimit 子集:**

- 全样本 T+5 net: **+7.81%** (cost 1%, conservative no-gap)
- 时间衰减: **T1 2015-19 +17.2%** → T2 2020-23 +2.4% → **T3 2024-26 -0.43% (FAIL)**
- 子集差异极大: **nolimit +36.7%** (n=2k, 容量小) > multi_day +16.5% > daily_up +3.5% > daily_down +1.3% > daily_turnover -0.78%

**不直接进 Tier 0 paper smoke** (T3 净负, real-money 必输). 不杀 LHB 方向.
**Phase 2 优先**: multi_day × 2024-2026 切片看看, nolimit 容量评估.

---

## 数据 + 方法

- Source: `data/raw/tushare/events/top_list_*.parquet`, 2015-01-06 ~ 2026-04-17, 2521 文件, dedup 后 164k unique 行
- Per-event aggregate: 同 (date, symbol) 多 reason 取 |net_amount| 最大那条 → 129,674 unique events
- Universe: 5128 stocks (跨 11 年所有曾上榜)
- Price panel: `utils.local_data_loader.load_adj_price_wide` (复权累积), shape 2761 × 5128
- Abn return: `pct_change - mkt_ew_mean`, clip ±25% 防 corp action
- Event window: T-5 ~ T+30
- Vectorized via `utils.event_study.compute_event_abn_returns` (numpy fancy index)

### Lookahead 处理 (rev 2 docstring 已对齐)

top_list **盘后 ~18:00** 披露. T close 不可下单, 最早 entry 是 T+1 close (本 study 用 close-to-close 近似).

**两种报告口径** (`utils.event_study.quintile_spread` 的 `skip_overnight_gap` 参数):
- **CONSERVATIVE** (主报告, `skip_overnight_gap=True`): 累计 over rel_day [2..H+1].
  Entry T+1 close, exit T+H+1 close. 跳过 T close → T+1 close 的 overnight gap (含披露后的 open gap, 不可收).
- **NAIVE** (上界, `skip_overnight_gap=False`): 累计 [1..H], 含 overnight gap.

NAIVE - CONSERVATIVE 差 ≈ 3-6% per horizon, **就是 overnight gap 部分, 不可收**.

### Cost (rev 2 修正)
- `cost_per_side = 0.0025` (单边)
- Long-short 2 腿, 各 1 round trip = 2×2×0.25% = **1.0% net 扣**
- rev 1 用了 `2 * cost_per_side = 0.5%` 是 under-count by 2x (只算了一腿). 新数字反映真 cost.

### Reason categorizer (rev 2 重写)

substring 匹配, 7 类:
- `multi_day`: "连续" / "累计" (跨 N 日累计 deviation)
- `nolimit`: "无价格涨跌幅限制" (ST / 北交所 / 退市过渡 / 上市初期, 无涨跌停板)
- `daily_turnover`: "换手率"
- `daily_range`: "振幅"
- `daily_up`: "涨幅" (剔除上面)
- `daily_down`: "跌幅" (剔除上面)
- `other`: 都不匹配

rev 1 用 prefix 匹配漏 30% 事件到 other. rev 2 substring + 涵盖涨跌停板 wording 变体. 新 reason_cat 分布:

| 类别 | n_events | 占比 |
|---|---|---|
| multi_day | 41,416 | 32% |
| daily_up | 35,555 | 27% |
| daily_turnover | 32,927 | 25% |
| daily_down | 21,327 | 16% |
| daily_range | 12,631 | 10% |
| nolimit | 2,065 | 2% |
| other | < 0.5k | < 0.4% |

### 时间切片 (RIAD Fold convention)
- T1: 2015-2019, T2: 2020-2023, T3: 2024-2026

---

## 结果

### 全样本 (CONSERVATIVE, cost 1.0%)

| Horizon | gross spread | net spread | t-stat | n_events |
|---|---|---|---|---|
| T+1 hold | +3.03% | **+2.03%** | +59.3 | 129,660 |
| T+5 hold | +8.81% | **+7.81%** | +61.1 | 129,674 |
| T+10 hold | +11.54% | **+10.54%** | +56.6 | 129,674 |

### 全样本 (NAIVE, 含不可收 overnight gap, 仅上界)

| Horizon | gross | net | t |
|---|---|---|---|
| T+1 | +6.11% | +5.11% | +117.7 |
| T+5 | +13.93% | +12.93% | +92.5 |
| T+10 | +17.30% | +16.30% | +80.6 |

NAIVE - CONSERVATIVE ≈ 3-6%, 这是 strategy 不可收的 overnight 部分.

### 时间切片 (CONSERVATIVE, cost 1.0%)

| Slice | T+1 net | T+5 net | T+10 net | T+10 verdict |
|---|---|---|---|---|
| **T1 2015-2019** | +4.45% | +17.17% | +23.47% | PASS (mega era) |
| **T2 2020-2023** | +0.42% | +2.40% | +3.03% | PASS |
| **T3 2024-2026** | **+0.15%** | **−0.43%** | **−0.52%** | **FAIL** |

**关键观察**: rev 1 误用 cost 0.5% 时 T3 T+5 还能勉强 PASS (+0.08%). rev 2 修对 cost 后, T3 T+5 / T+10 都 net 负. 时间衰减 + cost 双重打击, 最近 OOS 完全没 alpha.

### Reason subgroup (全样本 T+5, cost 1.0%)

| 类别 | net spread | t | n_events | 备注 |
|---|---|---|---|---|
| **nolimit** | **+36.74%** | +25.0 | 2,065 | ST/北交所/退市/上市初期, 无涨跌停板, 容量极小高风险 |
| **multi_day** | **+16.50%** | +54.2 | 36,373 | 3 日累计 deviation, 主力 alpha 来源 (但被 T1 数据拉抬) |
| daily_up | +3.49% | +17.2 | 31,293 | 单日涨幅榜, 中等 |
| daily_down | +1.27% | +9.9 | 18,884 | 单日跌幅榜, 弱 |
| daily_range | -1.45% | -1.28 | 11,117 | 振幅榜, 不显著 |
| daily_turnover | -0.78% | +1.04 | 29,514 | 换手榜, 接近零 |
| other | -5.76% | -3.58 | 468 | 杂项 |

`nolimit` 数字看上去爆炸 (+36.7% T+5), 但 n=2k 且**全是无涨跌停板的特殊股票** — ST / 退市 /
新股 / 北交所. 这些股票容量小, 流动性差, 借券很难, 不能作主力策略, 也容易被 backtest 高估 (停牌、退市样本生存偏差).

`multi_day` 数字 +16.5% 来自 36k 事件, 但 11 年合计. 必须分时间切片才知道现况.

---

## 判定 (按 Live-Tier framework)

### 是否可进 Tier 0 paper smoke?

**不直接可进**. Cost 修正后 T3 (2024-26) 在所有 horizon 都 net 负, real-money deploy 必输.

按 framework Live-Tier 1 入门门 (sharpe > 0.5 + 全 OOS 切片不 FAIL_NEG_SHARPE 至多 1 个):
- T3 T+5 + T+10 都 FAIL_NEG_SHARPE. 2 FAIL > 1, 直接卡门.

### 是否杀 LHB 方向?

**不杀**. 理由:
- 子集 `multi_day` 全样本 +16.5% 极强, 但需 T3 切片验证才知现况
- 子集 `nolimit` 数字夸张但容量太小, 单独不能跑, 但作为 universe filter (排除 nolimit) 可以试
- daily_up 子集 +3.5%, T3 切片若仍 > 0.5% 就值得做 Phase 2

### 下一步 (新 Issue, 不在本 issue 范围)

**Phase 2 (cross-tab subgroup × time slice)**:
- multi_day × 2015-19 / 2020-23 / 2024-26 — 看 multi_day 衰减幅度
- daily_up × 2024-26 — 看单日涨幅榜在最近是否仍有 edge
- 加 net_rate magnitude filter (e.g., net_rate > 5%) — 看极端事件子集
- 加涨跌停 next day 过滤 — Q5 net_rate 极大的股票大概率 T+1 仍涨停, 不可入场, 实际 net 比 backtest 更差

**杀的判定**: 若 Phase 2 subgroup × T3 都 < 0.5% net spread T+5 → 杀 LHB 方向, 转 A 路下一个 (回购公告 / 减持冷静期 / 调研突变).

---

## 红线检查

- ✅ no lookahead: rev 2 主报告 CONSERVATIVE 跳过 T close → T+1 open 的 overnight gap. NAIVE 上界也并列报告, 不当 tradeable
- ⚠ 涨跌停 next day 不能开仓: 没显式过滤. Q5 大 net_rate 股票 T+1 大概率仍涨停. 实测 vs backtest 还会更差. Phase 2 必修
- ✅ 不调任何参数 (quintile / horizon / cost / 时间切片) 凑显著性
- ✅ 全样本 + 时间分段, T3 T+5/T+10 都 FAIL 已诚实记录
- ✅ Cost 公式修了 (rev 1 错 2x 已纠正), 数字反映真 long-short cost

---

## 数据/代码出处

- 脚本: `research/event_alpha/lhb_t1_event_study.py` (rev 2)
- 通用 utils: `utils/event_study.py` (rev 2 新建, 抽自本 script + PEAD 共同模式)
  - `load_event_parquets(prefix, dir, start, end)` 通用 SSD parquet glob
  - `compute_event_abn_returns(events, prices, ...)` 向量化 fancy-index, ~30x
  - `quintile_spread(long_df, signal_col, ..., n_legs=2)` per-event quintile + cost-aware
- 价格: `utils.local_data_loader.load_adj_price_wide`
- 结果文件: `research/event_alpha/lhb_event_study_results.json` (.gitignored, rev 2)
- 图: `research/event_alpha/lhb_event_study.png` (.gitignored, rev 2 加 T+2 entry 标注)

— 记录: jialong
