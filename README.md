# quant-dojo

[![English](https://img.shields.io/badge/lang-English-2563EB?style=for-the-badge)](./README.md)
[![中文](https://img.shields.io/badge/lang-中文-DC2626?style=for-the-badge)](./README.zh-CN.md)

Systematic research and execution stack for the **A-share equity market**.
Built around a discipline of pre-registration, walk-forward validation, and
multi-layer risk control — every strategy must pass the same admission gate
before it can touch real capital.

> Project site: **https://quantdojo.vercel.app**
> License: CC BY-NC-SA 4.0

---

## What's inside

- **30+ factor research tracks** (price, fundamental, event-driven, LLM-native)
  with reproducible IC / ICIR / Fama-MacBeth analysis pipelines
- **Two strategy families**: cross-sectional multi-factor (`v7`–`v16` series)
  and event-driven (DSR — corporate actions / repurchases)
- **Backtest engine** (`backtest/engine.py`) with explicit slippage, T+1, ST
  filters, and survivorship-bias guards
- **Walk-forward validator** (`utils/walk_forward.py`) with López-de-Prado
  embargo and purged CV
- **5-gate admission system** (Sharpe / DSR / PSR / CI low / MDD)
- **Paper trading infrastructure** with ACID SQLite ledger, audit trail,
  reconciliation against backtest
- **Three-layer risk control**: research-stage gate → runtime kill switch →
  real-time monitor (Phase 8 adds vol targeting, divergence monitoring,
  capacity guards)
- **Agent layer** (`agents/`) using `claude -p` / Ollama for factor mining,
  reviewer adjudication, and operational execution under hard guardrails

---

## Architecture

```
                    ┌────────────────────────────────────────────────────┐
                    │  Data sources (akshare / tushare / local parquet)  │
                    └───────────────────────┬────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  utils/  — data_loader, fundamental_loader, factor_analysis, metrics  │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  research/factors/  — per-factor folder: factor.py + evaluate_*.py    │
   │  utils/alpha_factors.py — registered factor library                   │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  strategies/  — multi-factor (v7..v16) + event-driven (DSR)           │
   │  backtest/    — engine, comparison, standardized reports              │
   │  utils/walk_forward.py — purged CV + embargo, OOS evaluation          │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/risk_gate.py — 5-gate admission                             │
   │  pipeline/rx_factor_monitor.py — IC decay surveillance                │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/daily_signal.py → active_strategy.py → orchestrator.py      │
   │  pipeline/vol_targeting.py — gross scaling at target 12% vol          │
   │  pipeline/regime_detector.py — macro gate (high-vol/low-growth)       │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  live/paper_trader.py — order generation, fill simulation             │
   │  live/ledger.py — ACID SQLite ledger, NAV reconciliation              │
   │  live/event_kill_switch.py — DD/SR/divergence-driven HALT/HALVE       │
   │  live/risk_monitor.py — concentration, exposure, factor drift         │
   └───────────────────────────────────────────────────────────────────────┘
                                            ▼
   ┌───────────────────────────────────────────────────────────────────────┐
   │  pipeline/weekly_report.py + dashboard/ + portfolio/ (Next.js site)   │
   └───────────────────────────────────────────────────────────────────────┘
```

---

## Phase status

| Phase | Scope | State |
|-------|-------|-------|
| 0–2 | Environment, data, backtest engine | ✅ Complete |
| 3   | Factor research — 30+ tracks, IC/ICIR/FM analysis | ✅ Complete |
| 4   | Multi-factor strategy, walk-forward, reviewer gates | ✅ Complete |
| 5   | Paper-trade infra, ACID ledger, audit trail | ✅ Complete |
| 6   | Control plane — CLI + dashboard | ✅ Complete |
| 7   | Agentic research — AI operator with risk gate | ✅ Complete |
| **8** | **Real-money readiness — Tier 1 risk infra** | 🟡 **In progress (2/4 done)** |

**Active candidate**: `spec v4` — RIAD + DSR #30 BB-only 50/50 ensemble.
SR 1.87, PSR 0.998, DSR 0.920, MDD −4.86%; passes 4/5 gates pending Phase 8
Tier 1 completion. Spec frozen in
`journal/paper_trade_spec_v4_riad_dsr30_combo_20260422.md`.

---

## Repository layout

```
utils/             Reusable building blocks
                   ├── data_loader, fundamental_loader, tushare_loader  (data ingest)
                   ├── factor_analysis, multi_factor, alpha_factors     (factor framework)
                   ├── metrics, walk_forward, purged_cv                 (validation)
                   ├── risk_overlay, position_sizing, stop_loss         (risk math)
                   └── tradability_filter, universe, capacity           (universe construction)

research/          Per-factor research folders + notebooks
research/factors/  31 factor tracks, each with factor.py + evaluate_*.py

strategies/        Strategy implementations
                   ├── multi_factor.py        (cross-sectional v7..v16)
                   └── examples/, generated/  (templates + auto-generated)

backtest/          Event-driven engine: engine.py, comparison.py, standardized.py

pipeline/          Daily orchestration (27 modules)
                   ├── daily_signal, active_strategy, orchestrator      (signal → orders)
                   ├── risk_gate, rx_factor_monitor                     (research-stage gate)
                   ├── vol_targeting, regime_detector                   (Phase 8 risk infra)
                   ├── live_vs_backtest                                 (drift surveillance)
                   ├── weekly_report, alert_notifier                    (reporting)
                   └── experiment_runner, experiment_summarizer         (research mgmt)

live/              Paper trading + ACID ledger
                   ├── paper_trader, event_paper_trader                 (execution sim)
                   ├── ledger.py                                        (SQLite, atomic)
                   ├── event_kill_switch                                (DSR #30 spec v2 §5)
                   ├── risk_monitor                                     (concentration, drift)
                   └── broker_adapter                                   (broker-agnostic API)

agents/            LLM operators (claude -p / Ollama fallback)
                   ├── factor_miner, factor_analyst, factor_doctor     (research agents)
                   ├── debate, fund_manager                            (adjudication)
                   └── executor_agent                                   (gated execution)

dashboard/         FastAPI + Streamlit operational dashboard
portfolio/         Next.js public site (deployed to Vercel)
scripts/           Data backfills, audits, one-off analyses (60+ scripts)
tests/             pytest — 647 tests across 38 modules
journal/           Weekly reviews + investigation notes (the "lab notebook")
```

---

## Signal lifecycle (one trading day)

```
T-1 EOD          T morning         T 09:25     T 15:00       T 16:00
data update  →   signal gen   →   order gen  → fills   →   reconciliation
(scripts/    →   (pipeline/   →   (live/     → (live/   →   (pipeline/
 daily_       →    daily_       →   paper_   →  ledger) →    live_vs_backtest)
 update.sh)  →    signal.py)   →   trader)  →            →    + kill_switch eval
                                                              + alerts
```

Each step writes to a structured log (`logs/`) and to the ledger (`live/ledger.db`)
so any subsequent decision can be traced back to the input data fingerprint.

---

## Research methodology

| Tool | Purpose | Where |
|------|---------|-------|
| **Walk-Forward** | Train/test rolling windows, no look-ahead | `utils/walk_forward.py` |
| **Purged CV** | Embargo period (López de Prado) to remove serial overlap | `utils/purged_cv.py` |
| **DSR** | Deflated Sharpe Ratio — selection-bias correction | `utils/metrics.py` |
| **PSR** | Probabilistic Sharpe Ratio | `utils/metrics.py` |
| **5-Gate** | Hard admission thresholds | `pipeline/risk_gate.py` |

### 5-gate admission (any candidate must pass before paper trading)

| Metric | Threshold |
|--------|-----------|
| Annualized return | ≥ 15% |
| Sharpe ratio | ≥ 0.8 |
| Max drawdown | > −30% |
| PSR (Probabilistic Sharpe) | ≥ 95% |
| Sharpe CI lower bound | ≥ 0.5 |

Gates are codified in `CLAUDE.md` and **do not move** to accommodate a candidate.

---

## Risk control architecture

Three layers, each owns a different time horizon:

| Layer | Owner | Time scale | Triggers |
|-------|-------|------------|----------|
| **Research gate** | `pipeline/risk_gate.py` | Pre-deployment | 5-gate admission (above) |
| **Runtime kill switch** | `live/event_kill_switch.py` | Daily | DD > 20%, 30d SR < 0, monthly MDD > 12%, T+3mo/6mo fast-check |
| **Real-time monitor** | `live/risk_monitor.py` | Per-rebalance | Concentration, sector/factor exposure, position sizing |

**Phase 8 additions** (in progress) layer pre-emptive controls on top:

- `pipeline/vol_targeting.py` — gross-cap scaling to target 12% annualized vol
- `pipeline/live_vs_backtest.py` daily z-score divergence alert + kill linkage
- `pipeline/regime_detector.py` — macro gate (closes positions when
  vol/growth regime crosses learned thresholds)
- `pipeline/capacity_monitor.py` (TODO #39) — single-stock ADV-occupancy guard
- `scripts/stress_test.py` (TODO #40) — replay current portfolio against
  historical stress events (2015-08, 2020-02, 2024-09)

Roadmap: `journal/risk_infra_roadmap_phase8_20260423.md`.

---

## Quick start

```bash
# 1. Install (editable, requires Python ≥ 3.11)
pip install -e .

# 2. Verify environment
python -c "from utils import get_stock_history; from agents import LLMClient; print('env ok')"

# 3. Inspect available CLI surface
quant_dojo --help

# 4. Run the test suite (647 tests, ~30s)
pytest -q

# 5. Try a single-factor analysis (uses akshare, no API key)
python -m research.factors.low_vol.factor
```

Data backends: **akshare** (free, no key) and **tushare** (free tier).
No paid feeds required for any of the public research tracks.

---

## Key documents

| File | Purpose |
|------|---------|
| `ROADMAP.md` | Phase-by-phase plan with milestones |
| `TODO.md` | Active task list (live) |
| `CLAUDE.md` | Project rules (auto-loaded by Claude Code agents) |
| `WORKFLOW.md` | Git workflow, commit conventions, branching policy |
| `BRAINSTORM.md` | Design decisions, tradeoffs, alternatives considered |
| `ALPHA_THEORY_2026.md` | Current alpha thesis and search direction |
| `CHINA_QUANT_GUIDE.md` | A-share market reference (T+1, ST, fees, etc.) |
| `journal/risk_infra_roadmap_phase8_20260423.md` | Phase 8 executable plan |
| `journal/paper_trade_spec_v4_*.md` | Active live-trading specification |

---

## Research portfolio site

The `portfolio/` directory is a Next.js static site publishing the factor
library, strategy timeline, DSR event-driven records, and methodology glossary.

```bash
cd portfolio
npm install
npm run build          # static export → out/
vercel deploy --prod   # ships to https://quantdojo.vercel.app
```

---

## License

CC BY-NC-SA 4.0 — see [LICENSE](./LICENSE).
Non-commercial reuse with attribution; share-alike on derivatives.
