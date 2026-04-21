# Paper-Trade Spec v2 — DSR #30 主板 rescaled (单策略)
_2026-04-21 修订, supersedes `paper_trade_spec_20260420.md` (v1, 作废)_

## 修订理由 (vs v1)

v1 方案 paper-trade big_ens (#30 + #33 50/50). 2026-04-21 decay check (见
`journal/dsr30_decay_check_20260421.md`) 确认 **#33 最近 24 月 SR -1.86, 主动亏钱**,
ensemble 同期 SR -0.45. #33 是 crowded alpha (信息优势已被量化私募吃掉), 不能带进实盘.

同一分析确认 **#30 单独 2024-2025 SR 1.34, 是历史最强两年** — 无衰减. 本 v2 只 paper-trade #30.

---

## 1. 策略定义

**DSR #30 = BB-only + PV-only 50/50 (主板 rescaled)**

零 DoF 等权组合, 合并前每策略 gross-cap 1.0, 合并后再 cap 到 1.0.

| 成分 | 事件源 | 窗口 | UNIT | 方向 | 过滤 |
|---|---|---|---|---|---|
| BB | `_all_buyback.parquet` | T+1 ~ T+20 | 1/15 × 1.985 | LONG | board == 主板 |
| PV | `_all_earnings_preview.parquet` | T+1 ~ T+20 | 1/? × 2.286 | LONG | board == 主板 |

相关性与单腿 Sharpe:
- BB 单独 8-yr SR 0.95, ann 16.0%
- PV 单独 8-yr SR 0.48, ann 6.6%
- BB+PV ensemble 8-yr SR 0.83, ann 11.6%
- corr(BB, PV) 未测 (待 WF 补)

**注**: 因 BB 单腿 Sharpe > ensemble, 下个 sprint 考虑 only-BB 版本. 本 v2 先用 ensemble (BB+PV) 保持原 pre-reg 的零 DoF 承诺, BB 单腿需独立 pre-reg.

---

## 2. 信号生成节奏

**每交易日 EOD (15:00 收盘后) 跑一次 pipeline**:

1. 新建 `scripts/paper_trade_daily.py` 或在 `pipeline_daemon.py` 注入
2. 拉当日 buyback / earnings_preview 事件 (tushare 增量)
3. 应用 #30 的 main-board filter + UNIT rescale → 信号列表 `(symbol, weight_bb, weight_pv)`
4. 合成 weight = 0.5 × w_bb + 0.5 × w_pv, gross cap 1.0
5. 与昨日持仓 diff → **T+1 open** 买单 + 到期卖单
6. 写入 `paper_trade/orders_YYYYMMDD.csv` (date, symbol, action, weight_target, reason)

**不允许**: 手动覆盖、intraday 触发、参数调节. 信号发出即终态.

---

## 3. 资金规模与头寸

- **初始规模**: 总权益的 **5%** (Phase 1, first 3 mo) — 相比 v1 的 10% 减半, 因为:
  - DSR #30 8-yr ann 11.6% 不过 15% admission gate (单 SR 0.83 过)
  - 去掉 #33 后失去 ensemble 历史 SR 2.65 的虚胖信度
  - 需要 live 印证 2024-2025 的 SR 1.34 是结构性持续还是 regime 友好
- **升规条件** (T+3mo): 若 3 mo 实盘 SR ≥ 1.0 且 DD < 10% → 升到 **10%**
- **二次升规** (T+6mo): 若 6 mo 实盘 SR ≥ 1.0 且 DD < 15% → 升到 **15%**
- **单股上限**: 任意时刻持仓权重 ≤ 策略账户的 10%
- **策略 gross cap**: 1.0 (纯多头)

---

## 4. 执行纪律 (与 v1 一致)

| 项 | 规则 |
|---|---|
| 下单时机 | 每日 09:25 集合竞价挂 T+1 open 限价单 (限价 = 昨日收盘 × 1.005) |
| 滑点预算 | 单边 15 bps |
| 手续费 | 单边 10 bps 佣金 + 1 bps 印花 (卖方) |
| 未成交 | open 未成交则当日作废 |
| 持仓到期 | hold_days=20 (BB/PV 一致), 到期日 09:30 market 卖出 |
| 涨跌停 | 一字涨停 → 跳过建仓; 一字跌停 → 跳过减仓 |
| 停牌 | 保留仓位, 复牌首日按原到期日计算 |

---

## 5. 风控 / Kill Switch (vs v1 收紧)

| 触发 | 动作 |
|---|---|
| 30日滚动 SR < 0.5 | 仓位减半 |
| 30日滚动 SR < 0 持续 10 日 | 全减, 下线 |
| 累计 DD > **20%** (v1 是 25%) | 全减, 下线 |
| 单月 MDD > 12% (v1 是 15%) | 暂停新仓 7 日 |
| 回测 vs 实盘 10 日 rolling 差 > 50 bps/日 | flag 异常 |

**Fast-validation 新增**:
- T+3mo 时若 live SR < 0.5 → 不升规, 进入观察
- T+6mo 时若 live SR < 0.5 → 下线, 重回研究 (不再 wait T+9mo)

---

## 6. 监控 SLAs (与 v1 一致)

Daily EOD 输出 `paper_trade/daily_report_YYYYMMDD.md`; 每月首个交易日
`paper_trade/monthly_review_YYYYMM.md`. 字段定义同 v1 §6.

---

## 7. Review / Upgrade / Downgrade

| 时点 | 行动 |
|---|---|
| T | Phase 1 start, **5%** 规模 |
| T + 3 mo | 升到 10% 若 SR ≥ 1.0 且 DD < 10%; 否则维持或降 |
| T + 6 mo | 升到 15% 若 SR ≥ 1.0 且 DD < 15%; SR < 0.5 下线 |
| T + 9 mo | 若仍活 → 考虑加 2nd 条独立 pre-reg alpha |

**3 mo fast-check**: 相比 v1 的 6 mo 硬最小 forward 期缩短 — 因为单策略没有 ensemble
diversification 兜底, 需要更快判定信号是否还活着.

---

## 8. Alpha Decay 应对

DSR #30 最近 24 月 SR 1.34 无衰减信号, 但:
- BB/PV 是公司行为事件驱动, 理论上不像 LHB 那样易被 crowding 吃掉
- 仍需警惕: 回购窗口期套利 (已有 ETF 工具) 可能未来侵蚀
- 若 forward 3-6 月 SR 掉到 0.5 以下, 按 §5 处理; 不试图"修正"参数

**预期 live 区间**: ann **8-15%**, SR **0.6-1.2** (保留 margin, 不按 2024-2025 牛区外推).

---

## 9. 基础设施 TODO (实盘启动前, 与 v1 一致)

- [ ] 新建 `paper_trade/` 目录 (日报、月报、orders、fills、NAV)
- [ ] 新建 `scripts/paper_trade_daily.py` (EOD pipeline)
- [ ] 新建 `scripts/paper_trade_monthly_review.py`
- [ ] `pipeline_daemon.py` 注入 paper-trade daily 任务
- [ ] `portfolio/` 加 "/paper-trade" 页面
- [ ] 告警: daily report WARN/KILL → 推送

**启动前额外需要**:
- [ ] DSR #30 单独重跑完整 5-gate + WF (确认去掉 #33 后真实 gate pass 数)
- [ ] DSR #30 regime split (牛/熊/震荡) 独立确认
- [ ] 评估是否 BB 单腿优于 BB+PV ensemble (若是, 独立 pre-reg BB-only)

---

## 10. 预注册承诺 (与 v1 一致)

本文件定义的参数、阈值、规则不得在 paper-trade 期间修改. 如需调整:
1. 必须在 `journal/paper_trade_change_YYYYMMDD.md` 记录
2. 新 spec 从下一笔新仓起生效 (不追溯)
3. review 统计区分 spec-v2 和 spec-v3 期

触发超 2 次 → 承认 paper-trade 失败, 策略下线.

— 预注册日期: **2026-04-21**
— supersedes: `paper_trade_spec_20260420.md` (v1)
— 策略 owner: jialong
— 实盘启动目标日: 待启动前 TODO 完工
