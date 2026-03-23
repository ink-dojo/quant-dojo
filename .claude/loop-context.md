# Loop Context — 2026-03-22

## Project structure
```
pipeline/cli.py              — CLI entry (signal, positions, rebalance, performance, factor-health, risk-check, weekly-report)
pipeline/daily_signal.py     — Daily signal generation (run_daily_pipeline)
pipeline/data_checker.py     — Data freshness check
pipeline/factor_monitor.py   — Factor health monitoring
pipeline/weekly_report.py    — Weekly report generation
pipeline/__init__.py         — Package init
live/paper_trader.py         — PaperTrader class (positions, trades, NAV)
live/risk_monitor.py         — Risk monitoring (drawdown, concentration)
utils/local_data_loader.py   — Local CSV data loader (HARDCODED path: /Users/karan/Desktop/20260320)
config/config.example.yaml   — Example config (needs Phase 5 fields)
```

## Recent commits
```
8e41beb docs: add master workplan entry point
d318a8c docs: refine phase 5 infrastructure workplan
0f21167 fix: harden backtest and paper trading flow
94722b0 fix: portfolio 307 redirect, remove deprecated on_event
```

## Key code patterns

### Hardcoded path (utils/local_data_loader.py)
```python
LOCAL_DATA_DIR = Path("/Users/karan/Desktop/20260320")
```
This is the #1 thing WS1 must fix — centralize into runtime config.

### PaperTrader (live/paper_trader.py)
```python
PORTFOLIO_DIR = Path(__file__).parent / "portfolio"
TRANSACTION_COST_RATE = 0.003
class PaperTrader:
    def __init__(self, initial_capital=1_000_000): ...
```
Hardcoded constants, needs config integration.

### Daily signal (pipeline/daily_signal.py)
```python
SIGNAL_DIR = Path(__file__).parent.parent / "live" / "signals"
SNAPSHOT_DIR = Path(__file__).parent.parent / "live" / "factor_snapshot"
def run_daily_pipeline(date=None, n_stocks=30, symbols=None) -> dict: ...
```
Needs metadata, error handling, fixed output structure.

### CLI (pipeline/cli.py)
```python
# Commands: signal, positions, rebalance, performance, factor-health, weekly-report, risk-check
```

## Data location
The actual data is at `/Users/karan/Desktop/20260320` (now symlinked from SSD: `/Volumes/Crucial X10/20260320`).

## Conventions
- Commit: `git add <specific files> && git commit -m "type: message"` — NEVER `git add .`
- No AI attribution in commits (no Co-Authored-By)
- All new functions must have Chinese docstrings
- Verify: `python -m py_compile <file>` for syntax, `python -m pytest tests/ -v` if tests exist
- `live/portfolio/`, `live/signals/`, `live/factor_snapshot/` are NOT tracked in git
