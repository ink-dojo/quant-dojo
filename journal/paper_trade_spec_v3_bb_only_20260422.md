# Paper-Trade Spec v3 — DSR #30 BB-only 主板 rescaled
_2026-04-22 修订, supersedes `paper_trade_spec_v2_20260421.md` (v2, 作废)_

## 修订理由 (vs v2)

v2 spec `§9` item 3 自己留的出口: **"评估是否 BB 单腿优于 BB+PV ensemble (若是, 独立 pre-reg BB-only)"**.
2026-04-21 `research/event_driven/dsr30_standalone_wf.py` 完成该评估, 结论三条:

1. **BB-only 主板 rescaled**: single-sample **4/5** (唯一 fail = CI_low 0.20), WF median SR > 0.5 ✅,
   regime 2/3 ✅, trade-level win-rate > 45% + top5 < 20% ✅ → **生产级 3/4 过**.
2. **PV-only 主板 rescaled**: single-sample **1/5** (ann 2.1%, SR 0.16). PV 腿已死, 不是分散器,
   是稀释剂. 把 BB 4/5 拖到 ensemble 2/5.
3. **BB+PV 50/50 ensemble**: single-sample **2/5** (ann 11.5%, SR 0.72). 严格劣于 BB-only.

additional 2026-04-22 ran `dsr31_three_way_ensemble.py` (ggcg akshare 数据 on hand, 8842 增持事件):
Insider-only **0/5** (ann 5.83%, SR 0.30, MDD -46%, 2018 年 ann -45.8% 爆仓). 3-way ensemble
**2/5** (ann 9.82%, SR 0.59), 严格劣于 BB-only. DSR #31 alpha 被证伪, 不进组合.

**结论**: paper-trade live 用 BB-only 而非 ensemble. 本 v3 锁定 BB-only pre-reg. 未来若发现新 orthogonal
alpha (非 PV, 非 insider), 须独立 DSR 条目 + 独立 pre-reg + 5-gate 过 4/5, 再考虑 2-腿 ensemble.

---

## 1. 策略定义

**DSR #30 = BB-only 主板 rescaled (单腿 LONG-only)**

零 DoF, 单腿 gross-cap 0.8 (rescale 后), 不再有 ensemble mix.

| 成分 | 事件源 | 窗口 | UNIT | 方向 | 过滤 |
|---|---|---|---|---|---|
| BB | `_all_buyback.parquet` | T+1 ~ T+20 | 1/15 × (0.8/0.403) ≈ 0.1323 | LONG | board == 主板 |

**单样本 8-yr (2018-01-01 ~ 2025-12-31) 实测** (from `dsr30_standalone_wf.json`):
- ann **+15.99%**, Sharpe **0.84**, MDD **-29.68%**, PSR **0.996**, CI = [0.20, 1.50]
- WF (2yr × 6mo step, n=12): Sharpe median **+0.73**, Q25 **+0.39** (median ≥ 0.5 ✅, Q25 > 0 ✅)
- Regime: bull SR +1.37 ✅ / bear SR +0.01 ❌ / sideways SR +0.77 ✅ (**2/3 PASS**, ≥2 满足)
- Trade-level (n=684): win-rate **69.7%**, top-5 集中度 **9.4%** (win>45% ✅, top5<20% ✅)
- 2024 ann +41%, SR 1.27; 2025 ann +28%, SR 1.62 — 最近两年是历史最强 → 无衰减

**唯一未过**: CI_low 0.20 < 0.5 (variance 较高, 8-yr 样本还不够 tight). 因:
- 产品级 **3/4 PASS** (WF ✅ / regime 2/3 ✅ / trade-level ✅; single-sample 5-gate 4/5 因 CI_low)
- 或 paper-trade 6mo fast-validation 若 SR ≥ 0.8 → 自动满足 CI_low (bootstrap CI 会收窄)
- 单样本 5/5 硬门槛保留 "升 phase2 需 live SR ≥ 1.0" 的统计显著性 — 见 §7

---

## 2. 信号生成节奏

**每交易日 EOD (15:00 收盘后) 跑一次 pipeline**:

1. `scripts/paper_trade_daily.py` 运行 `pipeline.event_signal.generate_daily_signal(...)`
2. 拉当日 buyback 事件 (pv 腿已下, 不再消费)
3. 应用 BB 主板 filter + BB UNIT rescale → 候选 `(symbol, leg='bb', unit_weight=0.1323)`
4. 候选通过 causal 60d trailing 70th-percentile admission → 入 new_entries
5. `EventPaperTrader.process_day(...)` 重算 target-weight (**单腿 portfolio = 1.0 × bb_leg_weight, gross cap 1.0**)
6. 与昨日持仓 diff → 买单 (新入) + 卖单 (到期)
7. 写 `paper_trade/orders_YYYYMMDD.csv` + `paper_trade/daily_report_YYYYMMDD.md`

**不允许**: 手动覆盖、intraday 触发、参数调节. 信号发出即终态.

**Config-driven**: `paper_trade/config.json` 的 `legs_enabled = {bb: true, pv: false}` +
`ensemble_mix = {bb: 1.0, pv: 0.0}` 是 pre-reg 锁定参数, 改值必须开 v4 spec.

---

## 3. 资金规模与头寸

**不变 (vs v2)**. BB-only 比 ensemble Sharpe 更高, 但单腿没有分散, 仍保持 conservative 起步:

- **初始规模**: 总权益的 **5%** (Phase 1, first 3 mo)
- **升规条件** (T+3mo): live SR ≥ 1.0 且 DD < 10% → 升到 **15%** (phase 2)
- **二次升规** (T+6mo): live SR ≥ 1.0 且 DD < 15% → 升到 **50%** (phase 3, final sizing)
- **单股上限**: 任意时刻持仓权重 ≤ 策略账户的 15% (BB-only 单腿每个 position 已经 13.2%, 设 15% cap)
- **策略 gross cap**: 1.0 (纯多头), BB 腿 rescale 后平均 gross ≈ 0.8

---

## 4. 执行纪律

与 v2 一致.

| 项 | 规则 |
|---|---|
| 下单时机 | 每日 09:25 集合竞价挂 T+1 open 限价单 (限价 = 昨日收盘 × 1.005) |
| 滑点预算 | 单边 15 bps |
| 手续费 | 单边 10 bps 佣金 + 1 bps 印花 (卖方) |
| 未成交 | open 未成交则当日作废 |
| 持仓到期 | hold_days=20, 到期日 09:30 market 卖出 |
| 涨跌停 | 一字涨停 → 跳过建仓; 一字跌停 → 跳过减仓 |
| 停牌 | 保留仓位, 复牌首日按原到期日计算 |

---

## 5. 风控 / Kill Switch

与 v2 一致 (硬编码在 `live/event_kill_switch.py`).

| 触发 | 动作 |
|---|---|
| 30日滚动 SR < 0.5 | 仓位减半 (HALVE) |
| 30日滚动 SR < 0 持续 10 日 | HALT |
| 累计 DD > 20% | HALT |
| 单月 MDD > 12% | COOL_OFF 7 日 |
| 6-mo fast-check SR < 0.5 | HALT (不再 wait T+9mo) |
| 3-mo fast-check SR < 0.5 | DO_NOT_UPGRADE |
| 单日持仓 < 3 或 turnover > 0.5 | WARN |
| 回测 vs 实盘 10 日 rolling 差 > 50 bps/日 | WARN (flag 异常) |

---

## 6. 监控 SLAs

与 v2 一致. Daily EOD 输出 `paper_trade/daily_report_YYYYMMDD.md`; 每月首个交易日
`paper_trade/monthly_review_YYYYMM.md`.

---

## 7. Review / Upgrade / Downgrade

与 v2 相同时点, 规模阶梯 **5% → 15% → 50%** (replace v2 的 5/10/15).

| 时点 | 行动 |
|---|---|
| T | Phase 1 start, **5%** 规模 |
| T + 3 mo | 升到 15% 若 SR ≥ 1.0 且 DD < 10%; 否则维持或降 |
| T + 6 mo | 升到 50% 若 SR ≥ 1.0 且 DD < 15%; SR < 0.5 下线 |
| T + 9 mo | 若仍活 → 考虑加 2nd 条独立 pre-reg alpha (非 PV / insider) |

---

## 8. Alpha Decay 应对

BB 主板 rescaled 最近两年 (2024 SR 1.27, 2025 SR 1.62) 是历史最强, 无衰减信号.

可能的未来 decay 源:
- 回购窗口期套利 (已有 ETF 工具) 可能未来侵蚀 alpha
- 监管修改回购规则 (e.g. 限制大比例回购)
- 指数成分股调整改变主板 universe

**若 forward 3-6 月 SR 掉到 0.5 以下, 按 §5 处理; 不试图"修正"参数** (TOP_PCT, UNIT, hold_days 都已 pre-reg 锁定).

**预期 live 区间**: ann **12-20%**, SR **0.8-1.4** (不按 2024-2025 牛区外推).

---

## 9. 基础设施

已就绪 (2026-04-21):
- [x] `paper_trade/` 目录 + config.json
- [x] `scripts/paper_trade_daily.py` (EOD pipeline)
- [x] `scripts/paper_trade_monthly_review.py`
- [x] `live/event_paper_trader.py` (SQLite WAL ACID, 幂等 cron retry)
- [x] `live/event_kill_switch.py` (v3 §5 规则硬编码)
- [x] `pipeline/event_signal.py` (causal 60d trailing percentile)
- [x] `tests/test_event_*.py` + `scripts/paper_trade_smoke_test.py` (8-yr strict match vs backtest)
- [x] `research/event_driven/dsr30_standalone_wf.py` (4/5 + trade-level 验证)

v3 切换 checklist:
- [ ] `paper_trade/config.json`: `legs_enabled.pv = false`, `ensemble_mix = {bb:1.0, pv:0.0}`
- [ ] `pipeline/event_signal.py` + `live/event_paper_trader.py`: 读 config 的 mix + legs
- [ ] `paper_trade/README.md` 反映 BB-only
- [ ] smoke test 在 BB-only 模式重跑, 期望 vs `dsr30_mainboard_bb_oos.parquet` corr > 0.99
- [ ] Go-live 前: jialong 确认 phase="live_phase1", 填 started_at

---

## 10. 预注册承诺

本文件定义的参数、阈值、规则不得在 paper-trade 期间修改. 如需调整:
1. 必须在 `journal/paper_trade_change_YYYYMMDD.md` 记录
2. 新 spec 从下一笔新仓起生效 (不追溯)
3. review 统计区分 spec-v3 和后续 spec-vX 期

**触发超 2 次 → 承认 paper-trade 失败, 策略下线** (与 v2 保持).

**关键不变量 (v3 锁定, 不允许 A/B test)**:
- BB_UNIT_WEIGHT = 1/15 × (0.8/0.403) ≈ 0.13234077750206782
- TOP_PCT = 0.30 (monthly or 60d trailing)
- HOLD_DAYS = 20, POST_OFFSET = 1
- COST_RATE = 0.0015 单边
- Universe = listing_metadata["board"] == "主板"
- Direction = LONG-only

— 预注册日期: **2026-04-22**
— supersedes: `paper_trade_spec_v2_20260421.md` (v2)
— 策略 owner: jialong
— 实盘启动目标日: 待 §9 checklist 完工 + jialong 明示 go-live
