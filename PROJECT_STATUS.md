# quant-dojo Project Status

_Last updated: 2026-04-29_

## Pending Decisions (awaiting jialong review)

- **评估范式 v1 framework** — `journal/eval_framework_v1_proposal_20260429.md`
  Proposal: 把当前一道单门拆成 Tier 0/1/2/3 分级实盘门, 每级由 risk capacity →
  max DD → sharpe 反推, 升级必须 live 证据. **不直接改 CLAUDE.md / ROADMAP.md**,
  等 jialong 阅 proposal §"5 个开放问题" 后批准再 ratify. Issue #50.
  - Tushare 因子轮: 候选库本轮归零 (Issue #44/46/47), 不影响 framework 走流程.


## Current Position

quant-dojo is not in go-live mode.

The project is currently a systematic research and execution platform with:

- a working A-share data/research/backtest stack
- a paper-trade and ledger infrastructure
- Phase 8 Tier 1 risk modules implemented and tested
- no approved real-money candidate

The active local strategy state is currently `v16`, but `v16` is deprecated as a
strategy candidate. It failed admission historically and must not be described
as a baseline, go-live candidate, or paper-trade candidate.

Any use of `v16` from this point is allowed only as an **ops smoke runner**:
temporary infrastructure exercise for CLI/data/signal/rebalance plumbing. It
does not create strategy evidence.

## Recent Decision

`spec v4` is abandoned.

RIAD + DSR #30 BB-only 50/50 produced attractive combined metrics, but it relied
on a one-off DSR exception (`0.920 < 0.95`) and did not receive approval before
the decision window expired. It will not be implemented as `pipeline/riad_signal.py`
and will not enter live 5%.

Record: `journal/paper_trade_spec_v4_riad_dsr30_combo_20260422.md`

## Phase 8 Status

Tier 1 risk infrastructure is implemented and covered by tests:

- `pipeline/vol_targeting.py`
- `pipeline/capacity_monitor.py`
- `scripts/stress_test.py`
- `pipeline/live_vs_backtest.py`
- `live/event_kill_switch.py` external trigger support

This does not approve any strategy. Each future candidate must rerun:

- admission gate
- capacity check
- stress test
- live-vs-backtest tracking plan
- paper-trade observation

## Operating Principle

Do not optimize toward having a strategy.

Optimize toward a repeatable process that can reject weak strategies quickly and
preserve clean evidence for the rare candidate that survives.

## Next Four-Week Plan

### Week 1 — Control and Ops Smoke

- Do not use rejected strategies as baselines.
- Use `v16` only as a deprecated ops smoke runner until a neutral smoke path or
  non-rejected operational baseline is chosen.
- Run `make health` before material changes.
- Keep README / TODO / roadmap aligned with actual project state.
- Do not open a new alpha branch this week unless the ops pipeline is stable.

Exit criteria:

- health check passes
- no active go-live candidate is implied in docs
- strategy status is understandable from `quant_dojo status` without implying
  approval

### Week 2 — Operational Smoke

- Run and inspect the daily pipeline as an operational smoke test only.
- Track signal date, position count, NAV, risk alerts, and live-vs-backtest status.
- Update the weekly journal with operational facts, not strategy claims.

Exit criteria:

- at least one clean ops smoke run is recorded
- any data freshness or tracking-divergence issue is classified
- a non-rejected operational baseline or synthetic smoke path is selected before
  continuing repeated paper-trade runs

Status:

- 2026-04-25: one-time ops smoke using deprecated `v16` runner recorded in
  `journal/ops_smoke_v16_deprecated_runner_20260425.md`.
- 2026-04-25: short-window v16 backtest `v16_20260425_e14020e0` created only
  as a temporary tracking anchor for that smoke run.

### Week 3 — One Candidate Funnel

Pick exactly one candidate path:

- BGFD / LULR as a filter
- THCC reverse
- FMD data repair
- another pre-registered idea from `journal/ideas.md`

Do not run parallel speculative branches unless one is explicitly killed.

Exit criteria:

- candidate has a written hypothesis
- neutralized IC and cost-aware result are recorded
- kill / continue decision is documented

### Week 4 — Review

Answer three questions:

- Did the operational pipeline behave as expected?
- Did the candidate survive the funnel?
- Is there any reason to promote something to paper-trade observation?

If the answer is no, keep the system running and choose the next candidate.

## Health Check

Use:

```bash
make health
```

`python -m quant_dojo run --dry-run --strategy v16` is only an orchestration
smoke test using a deprecated runner. By design, dry-run skips real signal
generation and returns `n_picks=0`, so it must not be used to judge strategy
quality, alpha, or valid daily picks.

For full regression:

```bash
pytest -q
```

Last full regression observed locally: `677 passed`.

Known local warning:

- `requests` reports an urllib3/charset dependency mismatch in this environment.
  It does not currently fail tests or `quant_dojo doctor`, but should be cleaned
  up when the Python environment is next refreshed.
