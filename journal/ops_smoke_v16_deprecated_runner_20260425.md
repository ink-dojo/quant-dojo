# Ops Smoke — deprecated v16 runner
_2026-04-25 run for trade date 2026-04-24_

## Purpose

This is an operational smoke check, not a strategy admission decision.

`v16` is a rejected/deprecated strategy candidate. It was used here only because
the current CLI has a ready runner for it, making it useful for one-time
infrastructure exercise:

```
data freshness -> signal -> paper rebalance -> risk check -> dashboard export -> status
```

This run does not rehabilitate `v16`, does not make it a baseline, and does not
create evidence toward go-live.

## Commands

```bash
make health
python -m quant_dojo run --strategy v16
python -m quant_dojo status
python -m quant_dojo diff
```

## Result

`make health` passed:

- imports ok
- 99 key tests passed
- `quant_dojo doctor` reported system ready

`python -m quant_dojo run --strategy v16` completed successfully as an ops smoke:

- trade date: `2026-04-24`
- elapsed: 88.6s
- data freshness: ok, latest data `2026-04-24`
- signal: ok, 30 picks
- rebalance: ok, bought 30 / sold 30
- risk: ok
- dashboard export: ok

Key artifacts:

- `live/signals/2026-04-24.json`
- `live/portfolio/positions.json`
- `live/portfolio/nav.csv`
- `logs/quant_dojo_run_2026-04-24.json`
- `live/dashboard/dashboard_data.json`

Top 5 signal names:

1. `300779`
2. `301275`
3. `688228`
4. `301008`
5. `002037`

Portfolio after rebalance:

- positions: 30
- cash: RMB 126.87
- NAV: RMB 994,218.03
- day count in current paper ledger: 6
- max drawdown shown by `quant_dojo status`: -0.60%

## Observations

The ops loop is operational: it generated a dated signal, updated paper
positions, wrote NAV, wrote a run log, and refreshed dashboard data.

`quant_dojo diff` was not initially usable because live NAV dates did
not overlap with the selected backtest equity series:

```
status: no_overlap
reason: live nav and backtest equity have no overlapping trade dates
live dates: 2026-03-20, 2026-04-07, 2026-04-09, 2026-04-10, 2026-04-13, 2026-04-24
```

Follow-up: generated a short-window v16 backtest only to create a matching
tracking anchor for this ops smoke:

```bash
python -m quant_dojo backtest --strategy v16 --start 2026-03-20 --end 2026-04-24 --n-stocks 30 --no-report
python -m quant_dojo diff v16_20260425_e14020e0 --trend
```

Backtest anchor:

- run id: `v16_20260425_e14020e0`
- window: `2026-03-20` to `2026-04-24`
- total return: -1.89%
- annualized return: -17.53%
- Sharpe: -1.01
- max drawdown: -3.84%
- benchmark total return: +2.94%
- excess return: -4.83%

Tracking diff over the 6 overlapping live NAV dates:

- live cumulative return: -0.60%
- backtest cumulative return: -1.36%
- cumulative gap: +0.76%
- mean daily gap: +0.1261%
- gap volatility: 1.3691%
- max daily gap: +1.90% on `2026-04-09`

Interpretation: the smoke run now has a working tracking anchor, but the sample
is too short and the live dates are sparse. This is an observability setup, not a
performance claim and not a reason to keep using `v16`.

Capacity quick check at current AUM (~RMB 994k) found no warn/blocked positions
among the 30 current holdings. One ADV input is missing:

- `688496.SH`: `data/raw/tushare/daily_basic/688496.parquet` not found

## Known Noise

The run emits repeated factor-monitor warnings because several v16 factors are
not present in older factor snapshots:

- `shadow_lower`
- `amihud_illiq`
- `price_vol_divergence`
- `high_52w_ratio`
- `turnover_acceleration`
- `momentum_6m_skip1m`
- `win_rate_60d`

This did not block signal generation, but it makes status/run output noisy and
should be cleaned up separately.

The local environment also emits pyarrow CPU feature warnings from sandboxed
`sysctlbyname` calls. These are environment noise and do not affect exit code.

## Next Actions

1. Decide whether missing daily_basic for `688496.SH` is a data gap or path
   normalization issue, then refresh or exclude from capacity checks.
2. Select a neutral synthetic smoke path or a non-rejected operational baseline
   before repeated paper-trade runs.
3. Reduce factor-monitor warning noise only if the chosen future smoke/baseline
   path still touches the same monitor code.
4. Do not continue collecting `v16` runs as if they were baseline evidence.
