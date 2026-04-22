# quant-dojo

Systematic research stack for the A-share equity market: factor library, multi-factor
and event-driven strategies, backtest engine, paper-trading pipeline, and an AI research
operator layer.

Project site: **https://quantdojo.vercel.app**

## Status

| Phase | Scope | State |
|-------|-------|-------|
| 0–2   | Environment, basics, backtest engine | Complete |
| 3     | Factor research — 70 implemented factors, IC/ICIR/FM analysis | Complete |
| 4     | Multi-factor strategy, walk-forward, risk, reviewer gates | Complete |
| 5     | Paper-trade infrastructure, ACID ledger, audit trail | Complete |
| 6     | Control plane — CLI + dashboard | Complete |
| 7     | Agentic research — AI operator with risk gate | Complete |
| 8     | Real-money readiness | Not started |

Current active candidate: **DSR #30** (回购 drift, BB main-board rescaled) — 4/5 admission
gates pass; `CI_low = 0.20` below the 0.5 threshold. Paper-trade spec in
`journal/paper_trade_spec_v3_bb_only_20260422.md`.

## Repository layout

```
utils/             Factor library (70), data loaders, metrics, WF, analysis
research/          Notebooks and per-factor research folders
strategies/        Multi-factor and event-driven strategy implementations
backtest/          Event-driven engine (BacktestEngine)
live/              Paper trader, SQLite ledger, risk monitor
pipeline/          Daily signal → rebalance → risk → weekly report
agents/            LLM research operator (claude -p / Ollama)
dashboard/         FastAPI + Streamlit operational dashboard
portfolio/         Next.js public research portfolio (deployed to Vercel)
tests/             36 test modules (pytest)
journal/           Weekly reviews + investigation notes
scripts/           One-off data / export scripts
archive/           Superseded planning documents
```

## Quick start

```bash
pip install -e .
python -c "from utils import get_stock_history; from agents import LLMClient; print('env ok')"
quant_dojo --help
```

Requires Python ≥ 3.11. Data sources: `akshare` (free) and `tushare` (free tier);
no paid feeds required.

## Admission gate

Any strategy proposed for paper trading must pass all five checks:

| Metric                       | Threshold |
|------------------------------|-----------|
| Annualized return            | ≥ 15%     |
| Sharpe ratio                 | ≥ 0.8     |
| Max drawdown                 | > −30%    |
| Probabilistic Sharpe (PSR)   | ≥ 95%     |
| Sharpe CI lower bound        | ≥ 0.5     |

Gates are codified in `CLAUDE.md` and do not move to accommodate a candidate.

## Key documents

| File | Purpose |
|------|---------|
| `ROADMAP.md`              | Phase-by-phase plan |
| `TODO.md`                 | Active task list |
| `CLAUDE.md`               | Project rules (auto-loaded by Claude Code) |
| `WORKFLOW.md`             | Git workflow and commit conventions |
| `VERIFY.md`               | Acceptance checkpoints |
| `BRAINSTORM.md`           | Design decisions and tradeoffs |
| `ALPHA_THEORY_2026.md`    | Current alpha thesis |
| `CHINA_QUANT_GUIDE.md`    | A-share market reference |

## Research portfolio

The `portfolio/` directory is a Next.js static site publishing the factor library,
strategy timeline, DSR event-driven records, and glossary.

```bash
cd portfolio
npm install
npm run build          # static export → out/
vercel deploy --prod   # ships to https://quantdojo.vercel.app
```

## License

CC BY-NC-SA 4.0 — see [LICENSE](./LICENSE).
