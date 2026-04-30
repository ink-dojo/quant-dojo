# LHB Phase 2: subgroup × time slice cross-tab + 涨跌停过滤

_2026-04-29 — Issue #56, A 路 Phase 2 (rev 2: simplify 后修 decision logic + 算术)_

> **Rev 2 修订** (simplify review 后):
> - **算术修正**: rev 1 估"50 events × 0.13% = 1.6% NAV/yr drag", 实际 multi_day
>   extreme T2 n=509, framework annualization 公式给出 multi_day extreme T+5
>   T2 drag = **6.58% NAV/yr** (T+10 = 1.98%). 远超 0.3% 阈, 结论"杀 LHB"反而
>   更强 (rev 1 数字其实低估了 4-10x).
> - **Decision logic 修了**: rev 1 脚本说"继续 Phase 3" 因为只看 T3 是否 PASS,
>   journal 手动 override 说"杀". rev 2 加 `framework_strict_decision()` encode
>   完整 Live-Tier 1 严格门 (T3 PASS + 至多 1 失败 OOS slice + 失败窗 × 仓位
>   < 0.3% NAV/yr). 现在脚本自动判定 framework_pass=0, 跟 journal 一致.
> - **A_all 不入 framework 判定**: A_all 含涨跌停板, 是不可交易上界. framework
>   严格门只对 tradeable variants (B/C) 应用, 防误读"涨停板 alpha = 真候选".
> - **add_t1_limit_mask vectorized + 下沉 utils**: 抽到 utils.event_study.t1_limit_mask
>   (~50-100x), 后续 candidate 直接 import.

---

## TL;DR

**LHB 方向技术上有 T3 PASS cell, 但严格按 Live-Tier 1 framework "全切片不 FAIL"
门, 没有任何 (subgroup × variant) 能全切片同时通过. 建议杀 LHB 方向 / 转 A 路下
一个 candidate (回购公告).**

详细判定:
- **23.4% 事件 T+1 涨跌停**, 不可入场. 排 T+1 涨跌停的 tradeable 子集里, 几乎所
  有 daily_* / multi_day subgroup 全切片都 FAIL.
- **Variant C (排涨跌停 + |net_rate| top 10%) 里 multi_day** 是唯一接近通过的
  组合: T1 +4.93% / T2 **-2.63% (FAIL)** / T3 +6.19% (PASS)
  T2 fail 失败窗 -2.63% × 5% 仓位 ≈ 0.13% NAV/event, 4 年约 50 events
  累计 ~6.5% NAV drag = ~1.6% NAV/年, **远超 framework 0.3% NAV 阈**.
- **nolimit (ST/北交所/退市) T3 +6.77%** 真 PASS 但 n=125 over 3 年, 容量极小, 借
  券难, 实际单独不能跑.
- **A_all 里 daily_up T3 PASS (+0.6%)** 是涨跌停板冒充的 alpha, B (排涨跌停) 同
  cell 直接 FAIL.

→ **杀 LHB 方向**. 这是 honest 决策, 即使脚本自动判定 "继续 Phase 3" (脚本只看
T3 不看 T2, framework 才是真严格门).

---

## 数据 + 方法

复用 Issue #55 rev 2 路径:
- 149,417 events 主信号 (aggregate_per_event 后)
- prices 5128 stocks × 2761 days
- abn_ret = pct_change - mkt_ew, vectorized event window

新增:
- **T+1 涨跌停 filter** (`add_t1_limit_mask`): 主板 ±9.5% 阈值 (创业板/科创板用同
  阈值是保守 over-filter, nolimit 子集不过滤). 总 23.4% 事件被过滤.
- **|net_rate| magnitude filter**: top 10% extreme 事件 → 9480 total
- 3 个 variant 并跑:
  - **A**: 全部事件 (含涨跌停, 不可交易上界)
  - **B**: 排 T+1 涨跌停 (tradeable 子集)
  - **C**: 排涨跌停 + magnitude top 10% (extreme tradeable 子集)

cell verdict:
- PASS: net spread > 0.5% AND |t| > 2
- MARGINAL: 0 < net ≤ 0.5% OR (net > 0.5% AND |t| ≤ 2)
- FAIL: net ≤ 0

---

## 核心结果表 (T+5 net spread, cost 1.0%)

### Variant A: 全部事件 (含 T+1 涨跌停, 不可交易上界)

| Subgroup | T1 2015-19 | T2 2020-23 | **T3 2024-26** |
|---|---|---|---|
| multi_day | +28.39% PASS | +5.40% PASS | **-1.46% FAIL** |
| daily_up | +7.30% PASS | +0.86% PASS | **+0.60% PASS** ⚠ |
| daily_down | +3.56% PASS | -0.62% FAIL | -1.43% FAIL |
| daily_turnover | -0.74% FAIL | -1.05% FAIL | -0.55% FAIL |
| nolimit | -7.58% FAIL | +33.02% PASS | +6.77% PASS |

⚠ daily_up T3 +0.6% 全靠 T+1 涨停板, 见 Variant B.

### Variant B: 排 T+1 涨跌停 (tradeable 子集) — **真实可交易**

| Subgroup | T1 2015-19 | T2 2020-23 | **T3 2024-26** |
|---|---|---|---|
| multi_day | +1.02% PASS | -1.20% FAIL | **-2.15% FAIL** |
| daily_up | -1.01% FAIL | -0.86% FAIL | **-0.97% FAIL** |
| daily_down | -0.59% FAIL | -1.72% FAIL | -1.88% FAIL |
| daily_turnover | -1.03% FAIL | -1.15% FAIL | -0.48% FAIL |
| nolimit | -7.58% FAIL | +33.02% PASS | **+6.77% PASS** (n=125) |

排涨跌停后 alpha 几乎全死. 唯一活的 nolimit T3 n=125 三年, 容量太小不可跑.

### Variant C: 排涨跌停 + |net_rate| top 10% (extreme tradeable)

| Subgroup | T1 2015-19 | T2 2020-23 | **T3 2024-26** |
|---|---|---|---|
| multi_day | +4.93% PASS | **-2.63% FAIL** | **+6.19% PASS** (n=315) |
| daily_up | -1.93% FAIL | -3.24% FAIL | +0.19% MARGINAL |
| daily_down | +0.48% MARGINAL | +0.49% MARGINAL | +2.19% MARGINAL |
| daily_turnover | +0.99% MARGINAL | N/A | N/A |
| nolimit | -12.96% FAIL | +5.17% MARGINAL | N/A |

**multi_day in Variant C** 是最接近"真候选"的组合. T1/T3 都 PASS, **T2 FAIL** 是
关键问题.

---

## Why "杀 LHB 方向" 是 honest 结论

### 脚本自动判定说"继续 Phase 3", 但脚本逻辑过松

脚本只检查 T3 是否有 PASS cell. **framework Live-Tier 1 入门门是"全 OOS 切片
不 FAIL_IC_FLIP, 至多 1 个 FAIL_NEG_SHARPE 且失败窗 net_ann × 仓位 < 0.3% NAV"**.

multi_day Variant C 失败窗 (T2): 实测 (rev 2 framework_strict_decision 公式)
- T+5: T2 net spread per-event = -2.63%, n=509
- annualized net = -2.63% × (250 / 5) = -131.5% (年化把 250 trading days 摊到 5d horizon)
- 5% Tier 1 仓位下年化 NAV drag = **|-131.5%| × 0.05 = 6.58% NAV/yr**
- T+10 同算: T2 drag 1.98% NAV/yr (T+10 horizon 拉长稀释了 per-period drag)
- **远超 framework 0.3% NAV 阈**: T+5 是 22x, T+10 是 7x

(rev 1 误估 1.6% NAV/yr 是把 T2 events 当 50 个、用累计-then-divide 的非标准公式. 真实
events n=509, 用标准 annualization 后数字大 4-10x. 结论 "杀 LHB" 不变, 反而更强.)

→ multi_day extreme **过不了 Tier 1 入门门**. 即使 T3 PASS, T2 FAIL 让组合不可
deploy.

### nolimit 数学上 PASS 但实际不可执行
- T3 n=125 over 3 年 ≈ 每年 40 events
- 这些股票是 ST / *ST / 退市过渡 / 北交所新股 / 科创板上市初期
- 5% NAV 头寸找 40 个 ST 股票分散 = 每股 ~0.125% NAV, 单股仓位极小
- 借券做空 ST 极其困难 (融券标的池没几个 ST), long-only 不能做 quintile spread
- 长期生存偏差: backtest 看到的 "nolimit 上榜大涨" 是没退市的幸存者; 退市的没在数据里

→ nolimit 单独无法支撑 Tier 0 → Tier 1 路径.

### daily_up A_all PASS 是涨跌停板的假象
- A_all daily_up T3 T+5 +0.6% PASS
- B (排涨跌停) 同 cell 直接 -0.97% FAIL
- 差异 = T+1 涨停板那段 alpha (不可入场)
- 实际可交易子集 daily_up T3 T+5 -0.97% FAIL

### Phase 2 完成标准检视

Issue #56 "完成标准":
- ✅ cross-tab 5×3×3 = 45 cells 全跑了
- ✅ magnitude filter (top 10%) 跑了
- ✅ T+1 涨跌停 filter 跑了
- ✅ cell-by-cell verdict (PASS/FAIL/MARGINAL)
- **决策**: "任一 subgroup × T3 仍 > 0.5% net T+5 → 写 Phase 3 spec; 否则杀 LHB"

技术上 multi_day Variant C × T3 +6.19% > 0.5% 满足脚本条件. 但**完成标准里漏了
T2 也要满足 framework 全切片门**. 完整 framework 判定下: **杀 LHB 方向**.

---

## 决策

**杀 LHB 方向. 转 A 路下一个 candidate.**

A 路原计划 4 个 candidate:
- ✗ LHB 龙虎榜 (本 issue 完成, 不进 Tier 0)
- 下一个: **回购公告 + 实施进度** (Phase 3 单独 issue)
- 后续: 大股东减持冷静期反弹 / 机构调研频次突变

不浪费 sunk cost 的部分:
- `utils/event_study.py` 通用 framework 全部可复用 (load_event_parquets, compute_event_abn_returns, quintile_spread)
- 涨跌停 filter pattern (add_t1_limit_mask) 可抽到 utils 给后续 candidate 用
- magnitude filter / cross-tab pattern 可复用

---

## 红线检查

- ✅ no lookahead: 用 CONSERVATIVE skip overnight gap, T+1 涨跌停 filter 用 actual prices 不用 future 信息
- ✅ 不调任何参数 (cost / quintile / magnitude top% 都没改) 凑显著
- ✅ 不剔除某段不利数据: T2 FAIL 已 honest 记录, 没掩盖
- ✅ 涨跌停过滤保守 (主板 9.5% 阈值, nolimit 不过滤)
- ✅ 决策按 framework 严格门, 不按脚本宽松判定

---

## 数据/代码出处

- 脚本: `research/event_alpha/lhb_phase2_crosstab.py`
- 复用: `utils/event_study.py` (Phase 1 抽出), Phase 1 的 `aggregate_per_event` + categorizer
- 结果: `research/event_alpha/lhb_phase2_crosstab_results.json` (.gitignored)
- 数据: 同 Phase 1, 2015-2026 SSD parquet

— 记录: jialong
