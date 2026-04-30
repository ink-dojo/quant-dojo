# 回购预案 event study — Issue #57, A 路第 2 候选

_2026-04-29 — 结论: 全样本全 variant 全 slice 几乎全 FAIL. 杀回购方向, 转减持冷静期._

---

## TL;DR

**回购预案 (proc='预案') 上榜后 cost 后 alpha 全样本就负, T3 OOS 唯一接近 PASS
的 cell 也被 T1/T2 拖累 0.78% NAV/yr drag, 远超 framework 0.3% 阈. 直接杀.**

| 全样本 net (cost 1%, conservative) | 数 |
|---|---|
| T+1 | **-0.99%** (gross +0.01%, t 0.16) |
| T+5 | **-0.37%** (gross +0.63%, t 3.67) |
| T+10 | **-0.20%** (gross +0.80%, t 3.52) |

**全样本 gross < 1% (cost), 即基础信号在 cost 1% 假设下 net 必负.** Top 10% 极端
回购规模子集**反而更差** (T1 net -1.08%, T3 net -1.34% T+5), 说明大型回购公告
的 alpha 偏负 — 可能是 "大公司用回购掩盖业绩压力" 信号.

---

## 数据

- `data/raw/tushare/repurchase.parquet`: 95k 公告 2015-2026, proc 6 类
  - 预案 26.5k / 股东大会通过 12k / 实施 32k / 完成 24k / 停止 0.09k / 未通过 0.03k
- 本 study 只用 **proc='预案'** (announcement = alpha 第一次入价时点)
- 同 (ann_date, ts_code) 多条 (重复披露 / 多次预案) 取 amount 最大
- 去除 amount NaN / 0 → 15,538 events
- 加载 daily_basic.circ_mv 算 signal `amount_to_mv = amount / circ_mv`, 命中
  14,661/15,538 (94%)
- compute_event_abn_returns 后 unique events: **11,527**

## 方法

复用 `utils.event_study` 全套:
- `t1_limit_mask` 排 T+1 涨跌停 (回购预案 T+1 涨跌停率 2.4%, 远低于 LHB 23.4% —
  回购信号没那么 momentum-trigger)
- `compute_event_abn_returns` (vectorized, T-5 ~ T+30)
- `quintile_spread` (n_legs=2, cost 1%, skip overnight gap)
- `framework_strict_decision` 自动判 T3 PASS + IS slice budget < 0.3% NAV/yr

3 个 variant:
- A_all: 全部预案事件 (含涨跌停, 上界)
- B_no_limit: 排 T+1 涨跌停 (tradeable)
- C_extreme_no_limit: 排涨跌停 + |amount_to_mv| top 10% (extreme tradeable)

Time slices: T1 2015-19 / T2 2020-23 / T3 2024-26

---

## 结果

### 全样本 (CONSERVATIVE, cost 1%)
| Horizon | gross | **net** | t | n_events |
|---|---|---|---|---|
| T+1 | +0.01% | **-0.99%** | +0.16 | 11,527 |
| T+5 | +0.63% | **-0.37%** | +3.67 | 11,527 |
| T+10 | +0.80% | **-0.20%** | +3.52 | 11,527 |

**Cost 1% 把 gross 全部吃掉**. Q5-Q1 gross spread 在 T+5 / T+10 是统计显著正
(t 3.5+), 但 economically 不够覆盖 long-short 双腿 round-trip cost. 这条信号
**学术意义存在, 商业不可执行**.

### Cross-tab (T+5 net, cost 1%)

**Variant A (上界)**:
| Slice | T+5 net | t | verdict |
|---|---|---|---|
| T1 2015-19 | -1.03% | -0.1 | FAIL |
| T2 2020-23 | -0.91% | +0.3 | FAIL |
| T3 2024-26 | +0.41% | +4.5 | MARGINAL |

**Variant B (排涨跌停, tradeable)**:
| Slice | T+5 net | t | verdict |
|---|---|---|---|
| T1 2015-19 | -0.98% | +0.1 | FAIL |
| T2 2020-23 | -0.73% | +1.0 | FAIL |
| T3 2024-26 | +0.23% | +3.9 | MARGINAL |

**Variant C (排涨跌停 + |amount| top 10%)**: **全 FAIL, 顶部规模反而更差**
| Slice | T+5 net | t | verdict |
|---|---|---|---|
| T1 2015-19 | -1.08% | -0.1 | FAIL |
| T2 2020-23 | -2.17% | -1.4 | FAIL |
| T3 2024-26 | **-1.34%** | -0.4 | FAIL |

Variant C 是关键发现: 大额回购公告 (top 10% amount_to_mv) 全切片 net 负. 跟 LHB
"top extreme 救活 multi_day" 反而相反 — 大公司大型回购**没有跟风资金涌入,
反而**长期跑输大盘. 可能"大型回购 = 信号疲软的市值管理工具"假说成立.

### Framework 严格判定

framework_strict_decision (只看 tradeable B/C):
- **OOS (T3) PASS cells: 1** (loose: B_no_limit T+10 +0.57% t=4.01 n=3,557)
- **Framework PASS: 0**
- 唯一 OOS PASS 的 cell 被 T1/T2 拖累:
  T1 T+10 -10.75% annualized, T2 T+10 -15.65% annualized
  worst slice drag = 0.78% NAV/yr (5% Tier 1 仓位)
  **远超 0.3% 阈** → reject

---

## 判定: 杀回购方向

按 framework Live-Tier 1 严格门: **0 个 framework_pass cells**. 即使脚本宽
松判定也只 1 个 OOS loose PASS, 仍被 IS slice 拖累.

**杀回购预案方向. 转 A 路第 3 候选: 大股东减持冷静期反弹.**

不浪费的 sunk cost:
- 数据加载 + circ_mv 配对模式 → 减持/调研都能直接复用
- utils/event_study 全套继续 work
- 3-variant cross-tab + framework decision 一致, 后续直接 import 跑

---

## 红线检查

- ✅ no lookahead: 用 ann_date (公告日), 不用 end_date (回购截止日, 这个是未来信息)
- ✅ skip overnight gap (CONSERVATIVE)
- ✅ 涨跌停 filter (主板 9.5%, 回购预案率仅 2.4%)
- ✅ 不调任何参数 (cost / quintile / horizon / amount top% 都没改)
- ✅ 决策按 framework 严格门, 不按 loose 判定

---

## 数据/代码出处

- 脚本: `research/event_alpha/repurchase_event_study.py`
- 复用: `utils/event_study.py` (全套), `utils.local_data_loader.load_adj_price_wide`
- 结果: `research/event_alpha/repurchase_event_study_results.json` (.gitignored)

— 记录: jialong
