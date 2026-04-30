# 机构调研 event study — Issue #59, A 路第 4 候选 (last)

_2026-04-29 — 结论: 调研频次没 alpha. A 路 4/4 全死._

## TL;DR

**机构调研频次 (rolling 30d sum) 作 quintile signal, 全样本 gross spread 接近零, cost 后明显负**:
- T+1 net -0.83% (gross 0.17%, t 3.54)
- T+5 net -0.97% (gross 0.04%, t 0.33)
- T+10 net -1.11% (gross -0.11%, t -0.79)
- T+20 net **-1.46%** (gross -0.46%, t -2.35)

时间切片:
- T1 2015-19: N/A (stk_surv 数据 2018 后才丰富)
- T2 2020-23: 全 FAIL, 高调研 → T+20 跑输 -2.4%
- T3 2024-26: 全 FAIL, 高调研 → T+20 跑输 -0.9%

Variant C (排涨跌停 + 极端 top 10% 调研频次) T3 仍全 FAIL.

**Framework_pass = 0. 杀机构调研方向. A 路 4/4 全死.**

## 数据

- `data/raw/tushare/stk_surv/stk_surv_{symbol}.parquet` × 2810 per-stock
- aggregate (surv_date, symbol) → n_today (= 当日调研次数)
- per-symbol rolling 30d sum → surv_30d (signal)
- 28k unique (date, symbol) events with prices

surv_30d 分位:
- P10 = 1, P50 = 5, P90 = **47** (高调研热度的股票一个月内被调研 47+ 次)

## 经济解释

为什么高调研频次 → 跑输? 假设性 (没数据验证):
- 集中调研常发生在**业绩公告季 + 业绩预期不及时** → 卖方/买方机构紧急复盘
- 公告"机构密集调研"被市场解读 = "情况复杂, 需要专门调研" 而非 "热点"
- 调研记录是过去时, 信息已被消化

或者就是 cross-sectional 上市公司 cycle: 大公司被调研多 (头部股), 中小公司被调研少. 大公司 vs 小公司在 2020-26 是后者跑赢 (低 vol / size factor 反向). 调研频次只是 size 代理.

要确认这个假说需要做 size-neutral 调研频次 — 但 framework 红线 "不调参数凑显著", 不再 sweep.

## A 路 final 状态

A 路 4 候选全部跑完, 全部杀:

| Issue | 候选 | 数据 | n_events | 决策 |
|---|---|---|---|---|
| #56 | 龙虎榜 | top_list 2015-26 | 130k | ❌ T2 FAIL drag 6.6% NAV/yr |
| #57 | 回购预案 | repurchase 2015-26 | 11.5k | ❌ 全 cell FAIL, top extreme 反而恶化 |
| #58 | 限售解禁 | share_float 2014-26 | 16k | ❌ 信号方向反 (supply pressure 真实但 reverse 不可执行 借券难) |
| #59 | 机构调研 | stk_surv 2018-26 | 28k | ❌ 全样本 gross 接近零 cost 后负 |

**A 路终结. 4/4 全死.**

诚实读: A 股事件驱动 cross-sectional alpha 在 2024-26 普遍被磨掉了, 不是
4 个候选我选错了. LHB 是历史最 famous 的事件 alpha (2015-19 T+5 spread 17%),
现况 net 负. 回购/解禁/调研三个都没 effective 信号.

可能的解释 (没验证):
1. 量化参与度上升 → 公开事件被秒级 arb
2. cost (双边 1%) 是 long-short 真实门, 单事件 alpha 必须 >1% gross 才 net 正
3. T3 2024-26 是 A 股结构性年 (国九条 / 化债 / 高低切换), 任何 size/style cluster 都被打碎

## 不浪费的 sunk cost

- `utils/event_study.py`: load + abn return + quintile + limit + cell + framework decision
- `utils/event_alpha_pipeline.py`: 3-variant orchestrator
- 4 个 study script: 后续如果有新事件数据 (例如 dragon_tigers 第二维度 / margin / ETF flow),
  直接 import + 改 load_xx_events + signal_col 一行 = 1 个新 study
- 凡是新 alpha source 都进同一 framework 严格门, 不在 backtest 数字上自欺

## 下一步: 转方向

按原始 A → B → C → D 计划, A 已死. 选 C 或 D:

**C (质量改进现有 cross-sectional 因子)**:
- 已有 roe_stability 单腿 5/7 切片 PASS (Issue #44/47), 加 regime overlay /
  quality overlay / 改 horizon 看是否能过 framework
- 优点: 候选已存在, 改动小
- 风险: 也可能跟 A 路一样 alpha 已 decay

**D (paper-trade infra 真用法)**:
- Issue #51 (Tier 0 startup: roe_stability + v16 双 ledger) 已 ready,
  没启动 (等 framework v1 ratify 完成)
- framework 已 ratify, 现在可以启动 30 天 paper smoke
- 优点: 现有 candidate (roe_stability) 立刻可跑, 收 friction data 比 backtest 信息量大
- 缺点: 需要每天检查, 30 天才有结论

**我的建议**: 同步做 D + C (并行不冲突):
- D: 立刻启动 Issue #51 paper smoke (nightly ledger update, 30 天)
- C: 同期跑 regime overlay 改进 roe_stability — 如果效果显著, paper smoke
  跑完后正好可以升级到改进版

— 记录: jialong
