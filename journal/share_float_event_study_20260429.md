# 限售解禁 event study — Issue #58, A 路第 3 候选

_2026-04-29 — 结论: 信号方向跟假设反了 (实测 supply pressure 而非反弹), reverse 也不可执行 (借券难). 杀, 转调研突变._

---

## TL;DR

**实测结果跟假设方向相反**:
- 假设: 大解禁 → 短期负 abn (supply pressure) → T+5~T+15 反弹
- 实测: 大解禁 → T+5 net +0.02% (接近零, 没反弹), **T+10 net -9.15% (t -12.9), T+15 net -15.2% (t -16.7)**

→ 大解禁后 weeks 持续 supply pressure, 没反弹. 经典 lock-up expiration 效应
被实证, 但跟"冷静期反弹"假设相反.

**理论上 reverse direction (做空大解禁) 是真 alpha** (T+15 spread 反过来 +15% gross),
但 short 大股东解禁股票**借券极难** (融券标的池不太覆盖刚解禁的股票, 且大股东
减持期券商风控会特别紧). 实际不可执行.

→ Framework_pass = 0 (按 long Qn-spread 默认方向, 全 FAIL_NEG_SHARPE 不合 PASS).
→ **杀方向, 转 A 路第 4 候选 (机构调研频次突变)**.

---

## 数据

- `data/raw/tushare/share_float/{symbol}.parquet` × 3,633 per-stock 文件
- 字段: ts_code, ann_date, float_date, float_share, **float_ratio** (% 总股本), holder_name, share_type
- 同 (ann_date, ts_code) 多 holder 行: float_ratio **求和** = 单日总解禁压力
- aggregate 后: 18,006 events, 日期 2014~2026

float_ratio 分位 (% 总股本):
- P10 = 0.04%, P50 = 0.42%, P90 = 4.6%

## 方法

复用 `utils/event_alpha_pipeline.run_3variant_pipeline` (新抽 helper, 此为
第一次 fresh-use, 验证 API):

- `t1_limit_mask`: T+1 涨跌停 filter (主板 9.5%), 408 events (2.3%) 被过滤
  (远低 LHB 23.4%, 跟回购预案 2.4% 接近 — 解禁公告不强烈触发涨跌停)
- `compute_event_abn_returns`: T-5 ~ T+30 vectorized
- `quintile_spread`: Qn-Q1 默认方向, **n_legs=2 long-short cost 1.0%**
- 3 variants A_all / B_no_limit / C_extreme_no_limit
- `framework_strict_decision`: 只对 B/C tradeable

加 **T+15** horizon (除 T+1/+5/+10) 看是否有冷静期反弹.

---

## 结果

### 全样本 spread (CONSERVATIVE, Qn-Q1, cost 1%)

| Horizon | gross | net | t | n_events |
|---|---|---|---|---|
| T+1 | +0.26% | -0.74% | +2.00 | 13,598 |
| T+5 | +1.02% | +0.02% | +2.82 | 14,579 |
| **T+10** | **-8.15%** | **-9.15%** | **-12.93** | 15,648 |
| **T+15** | **-14.22%** | **-15.22%** | **-16.66** | 15,659 |

**T+10 / T+15 negative spread t-stat 极强** (绝对值 13-17), 这是非常 strong 的
反向 signal. Q5 (大解禁) 的累计 abn return 在 2 周内比 Q1 (小解禁) 多跌 9-15
个百分点.

### Framework decision

- OOS PASS: 0 (loose 也 0)
- Framework PASS: 0
- 所有 cells (Qn-Q1 方向) net 负, 全 FAIL_NEG_SHARPE

### 反转方向 (Q1-Qn, 做空大解禁) 假设性数字

如果 reverse direction (做空 Q5 大解禁 + 做多 Q1 小解禁), 全样本 gross:
- T+10: +8.15% gross / +7.15% net (cost 1%)
- T+15: +14.22% gross / +13.22% net

t-stat 反转后 +12.93 / +16.66 (符号反转), 极显著.

**但执行不可行**:
1. 借券池: 中证金融融券标的不覆盖刚解禁的小盘股, 且大解禁后 1-2 周券商风控
   会特别紧 (担心大股东配合机构联手出货)
2. T+0 解禁日股票通常进入"被减持观察名单", broker borrow 拒绝率高
3. 即使能借, 借券利率会因供给紧张飙升 (典型 8% 年化 → 解禁期可能 15-20%)

按 framework Live-Tier 1 standard ("可交易" 标准, 不算理论 alpha): 不可入.

---

## 不浪费的 sunk cost

- `utils/event_alpha_pipeline.run_3variant_pipeline` 第一次 fresh-use ✅,
  验证 API 在不同 candidate (无 subgroup, 单 'all') 跑通
- share_float per-stock 加载 pattern (`load_share_float_events`) 可后续 reuse
- 反向 supply pressure 效应实证存在, **可作为别处 strategy 的 universe filter**
  (例如: 执行其他多头 alpha 时排除最近 30 天有大解禁公告的股票)

---

## 红线检查

- ✅ no lookahead: ann_date 公告日, CONSERVATIVE skip overnight
- ✅ 涨跌停 filter (主板 9.5%, 解禁公告涨跌停率仅 2.3%)
- ✅ 不调任何参数凑显著 (反向方向数字也只是 magnitude 报告, 没改默认 Qn-Q1)
- ✅ 不假装 reverse direction 可执行 (借券难是诚实障碍)
- ✅ framework 严格判定按 default direction, 杀

---

## 决策

**杀限售解禁方向 (long-short 不可执行).**

A 路 status:
- ✗ LHB 龙虎榜 (Issue #56)
- ✗ 回购预案 (Issue #57)
- ✗ 限售解禁 (Issue #58, 本)
- 下一个: **机构调研频次突变** (data/raw/tushare/stk_surv 之类)

如果第 4 候选也死 → A 路 4/4 全死 → 该认真看 honest 是不是 cross-sectional
event-driven 这条路在当前 A 股市场普遍被磨掉了, 转其他 paradigm (如 C 路
质量改进 + D 路 paper-trade infra 跑现有 roe_stability).

---

## 数据/代码出处

- 脚本: `research/event_alpha/share_float_event_study.py`
- Pipeline: `utils.event_alpha_pipeline.run_3variant_pipeline` (新)
- 工具: `utils.event_study.*` 全套
- 结果: `research/event_alpha/share_float_event_study_results.json` (.gitignored)

— 记录: jialong
