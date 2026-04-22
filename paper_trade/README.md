# Paper-Trade — DSR #30 主板 rescaled BB+PV ensemble

> Spec v2 — 2026-04-21 起基础设施就绪，等待 go-live。

## 这是什么

DSR #30 (BB 主板 rescaled × 0.5 + PV 主板 rescaled × 0.5) 的纸面交易流水。
2018-2025 回测：ann 18.1%, Sharpe 1.50, MDD -21.6%, corr(bt, live) 0.9993 (smoke test, 1.91 bps / day drift)。

交易逻辑 = 事件驱动。每日 EOD 跑一次：
1. 拉 BB/PV 当日事件 → `generate_daily_signal`
2. `EventPaperTrader.process_day` 下单（target-weight rebalance, 不 equal-weight）
3. `event_kill_switch.evaluate` 风控判定
4. 写 `orders_YYYYMMDD.csv` / `daily_report_YYYYMMDD.md`；非 OK 写 `alerts.log`

每月首个交易日跑一次 monthly review (`paper_trade_monthly_review.py`) —
产出 live vs backtest 对比 / 集中度 / 月末 kill switch 快照。

## 目录结构

```
paper_trade/
  config.json                   # 运行配置 (见下)
  portfolio/                    # trader 持久化 (SQLite + JSON)
    ledger.sqlite               # trades / NAV 账本 (ACID)
    open_entries.json           # 未到期 entries (fail-safe recovery)
  orders_YYYYMMDD.csv           # 每日成交
  daily_report_YYYYMMDD.md      # 每日报告
  monthly_review_YYYY-MM.md     # 月度 review
  alerts.log                    # kill switch 告警历史 (仅 non-OK)
```

## 日常用法

```bash
# EOD daily (手动或 cron，15:30 之后)
python scripts/paper_trade_daily.py                    # 用今天 (Asia/Shanghai)
python scripts/paper_trade_daily.py --date 2026-04-21
python scripts/paper_trade_daily.py --dry-run          # 不落盘

# 每月首交易日
python scripts/paper_trade_monthly_review.py           # 自动上月
python scripts/paper_trade_monthly_review.py --month 2026-04
```

退出码：`kill_action in {halt, cool_off}` → exit 1，cron 可据此告警。

## config.json 字段

| 字段 | 含义 |
|------|------|
| `spec_version` | 绑定的规格版本 (当前 v2) |
| `enabled` | 是否已上线 (pre_live 阶段 = false) |
| `phase` | `pre_live` → `live_phase1` → `live_phase2` → `live_phase3` |
| `started_at` | go-live 日期 (`YYYY-MM-DD`)，由 kill switch fast-validation 计时 |
| `initial_capital_cny` | trader 内部绝对本金 (NAV 相对此归一化) |
| `initial_capital_pct_of_total` | 占总资金比例，phase1=5% / phase2=15% / phase3=50% |
| `legs_enabled.bb`, `legs_enabled.pv` | 分腿开关，单腿失效时可独立关闭 |
| `unit_weights.bb/pv` | 单事件目标权重 (BB≈0.1323, PV≈0.0305) — rescale 自回测 gross ratio |
| `ensemble_mix` | 两腿合并系数，默认 0.5/0.5 |
| `hold_days`, `post_offset`, `cost_rate` | 交易机械参数 |

## Kill switch (spec v2 §5)

硬编码在 `live/event_kill_switch.py`：

- **HALT** (全部暂停): 累计 DD > 20% / 30 日 rolling SR < 0 连续 ≥ 10 天 / 6-mo fast-check SR < 0.5
- **HALVE** (仓位减半): 30 日 rolling SR < 0.5
- **COOL_OFF** (7 天冷却): 单月 MDD > 12%
- **DO_NOT_UPGRADE**: 3-mo fast-check SR < 0.5 (不升阶段但继续跑)
- **WARN**: 单日持仓 < 3 / turnover > 0.5

非 OK 会写 `alerts.log` 并向 stderr 打 `[ALERT]` 行，daemon 据此推消息。
`paper_trade_daily.py` 退出码 0 仅在 `action == OK` 时返回；任何其他 action
(WARN / HALVE / COOL_OFF / DO_NOT_UPGRADE / HALT) 都返回 1，供 cron 告警。

**并发约束**: `paper_trade_daily.py` 和 `paper_trade_monthly_review.py` 均打开
SQLite ledger (WAL 模式), 同时跑不会崩但 review 可能读到 daily 事务中间的视图。
实操上 daily 调度在 15:30, monthly review 在每月首交易日 17:00, 不会重叠。

## Go-live checklist

- [ ] jialong 确认 Phase 5 所选升级路径 (A/B/C, 见 `journal/phase5_regime_robust_plan_20260420.md`)
- [ ] 改 `config.json`: `enabled=true`, `phase="live_phase1"`, 填 `started_at`
- [ ] 配置 cron: `30 15 * * 1-5 cd /path && python scripts/paper_trade_daily.py >> paper_trade/cron.log 2>&1`
- [ ] 配置 monthly cron (首交易日 17:00)
- [ ] 绑定 alerts.log 到 Slack/邮件推送 (目前仅写文件 + stderr)

## 测试

```bash
pytest tests/test_event_signal.py \
       tests/test_event_paper_trader.py \
       tests/test_event_kill_switch.py \
       tests/test_paper_trade_daily.py -v

# 8 年 strict-match smoke test (实盘语义 vs 回测 parquet)
python scripts/paper_trade_smoke_test.py --mode strict
# 期望: mean abs daily delta < 10 bps, corr > 0.99
```
