"""Generate a rich demo `state.json` for the /live/paper-trade page.

Uses the BB-only strict-match replay (same as paper_trade_smoke_test but just
the replay half) over a chosen window, then serializes NAV + last 30 trades +
current open entries + kill status — identical schema to production state.json.

Writes to `portfolio/public/data/paper_trade/state.json` (overwrite). If you
want to keep the real one, back it up first:

    cp portfolio/public/data/paper_trade/state.json /tmp/state.real.json
    python scripts/paper_trade_gen_demo_state.py --start 2025-01-01 --end 2026-04-17
    # view page, then restore:
    cp /tmp/state.real.json portfolio/public/data/paper_trade/state.json

This script is for illustration; do NOT use its output as production audit.
"""
from __future__ import annotations

import argparse
import json
import logging
import tempfile
import time
from pathlib import Path

import numpy as np
import pandas as pd

from live.event_kill_switch import evaluate as eval_kill
from live.event_paper_trader import EventPaperTrader
from pipeline.event_signal import (
    BB_UNIT_WEIGHT,
    HOLD_DAYS,
    POST_OFFSET,
    TOP_PCT,
    EventEntry,
    _load_bb_events,
    _load_main_board_set,
)
from utils.local_data_loader import load_adj_price_wide

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
STATE_OUT = PROJECT_ROOT / "portfolio" / "public" / "data" / "paper_trade" / "state.json"
CONFIG_PATH = PROJECT_ROOT / "paper_trade" / "config.json"


def _precompute_bb_admissions(bb_events: pd.DataFrame,
                               trading_days: pd.DatetimeIndex,
                               main_board: set[str]) -> dict:
    """Same as smoke_test strict BB-only: monthly top 30% by signal."""
    admissions: dict[pd.Timestamp, list[EventEntry]] = {}
    td_arr = trading_days.values
    ev = bb_events[bb_events["symbol"].isin(main_board)].copy()
    ev["month"] = ev["event_date"].dt.to_period("M")

    for _, grp in ev.groupby("month", observed=True):
        grp = grp.sort_values("signal", ascending=False)
        if len(grp) < 10:
            continue
        n_top = max(1, int(np.floor(len(grp) * TOP_PCT)))
        for _, r in grp.iloc[:n_top].iterrows():
            event_date = pd.Timestamp(r["event_date"]).normalize()
            i_t = int(np.searchsorted(td_arr, event_date.to_datetime64(), side="left"))
            i_open = i_t + POST_OFFSET
            if i_open >= len(td_arr):
                continue
            entry_td = pd.Timestamp(td_arr[i_open])
            i_close = min(len(td_arr) - 1, i_open + HOLD_DAYS)
            exit_td = pd.Timestamp(td_arr[i_close])
            admissions.setdefault(entry_td, []).append(EventEntry(
                symbol=r["symbol"],
                leg="bb",
                event_date=event_date.strftime("%Y-%m-%d"),
                entry_date=entry_td.strftime("%Y-%m-%d"),
                exit_date=exit_td.strftime("%Y-%m-%d"),
                unit_weight=BB_UNIT_WEIGHT,
                signal=float(r["signal"]),
                threshold=0.0,
            ))
    return admissions


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2025-01-01")
    parser.add_argument("--end", default="2026-04-17")
    parser.add_argument("--capital", type=float, default=1_000_000.0)
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    # Load events + universe
    bb = _load_bb_events()
    main_board = _load_main_board_set()
    bb = bb[(bb["event_date"] >= pd.Timestamp(args.start))
            & (bb["event_date"] <= pd.Timestamp(args.end))]
    logger.info(f"BB events: {len(bb)}")

    universe = sorted(set(bb["symbol"]) & main_board)
    prices = load_adj_price_wide(universe, start=args.start, end=args.end)
    prices = prices.dropna(axis=1, how="all")
    trading_days = prices.index
    logger.info(f"prices: {prices.shape}, trading days: {len(trading_days)}")

    admissions = _precompute_bb_admissions(bb, trading_days, main_board)
    logger.info(f"admissions: {sum(len(v) for v in admissions.values())} "
                f"across {len(admissions)} days")

    with tempfile.TemporaryDirectory(prefix="demo_state_") as tmp:
        trader = EventPaperTrader(
            args.capital, Path(tmp),
            ensemble_mix={"bb": 1.0, "pv": 0.0},
        )
        cols = prices.columns.tolist()
        col_idx = {c: i for i, c in enumerate(cols)}
        prices_np = prices.to_numpy(dtype=float)
        t0 = time.time()
        for i, td in enumerate(trading_days):
            new_entries = admissions.get(td, [])
            row = prices_np[i]
            day_prices = {sym: row[col_idx[sym]] for sym in cols
                          if not np.isnan(row[col_idx[sym]])}
            trader.process_day(td.strftime("%Y-%m-%d"), new_entries, day_prices)
            if (i + 1) % 100 == 0:
                logger.info(f"  {i+1}/{len(trading_days)} days replayed "
                            f"({time.time()-t0:.1f}s)")

        last_td = trading_days[-1]
        last_str = last_td.strftime("%Y-%m-%d")
        nav = trader.nav_series()
        active = trader.active_positions_df()
        open_entries = trader.open_entries

        # Build last-day summary (fake, since we already processed it)
        today_trades = [t for t in trader.trades if t["date"] == last_str]
        gross_w = active["cost_price"].astype(float).sum() if not active.empty else 0.0
        # approximate gross weight from current prices × shares / nav
        gross_w = 0.0
        if not active.empty and nav.iloc[-1] > 0:
            for _, r in active.iterrows():
                gross_w += float(r["shares"]) * float(r["current_price"]) / nav.iloc[-1]

        kill = eval_kill(
            nav,
            as_of=last_td,
            n_positions_today=len(active),
            turnover_today=0.0,
        )

        # Real config
        cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8")) \
            if CONFIG_PATH.exists() else {}

        # Use trailing last 30 trades for display
        recent_trades = trader.trades[-30:]

        state = {
            "spec_version": cfg.get("spec_version", "v3"),
            "strategy_id": cfg.get("strategy_id"),
            "phase": cfg.get("phase"),
            "started_at": args.start,
            "enabled": cfg.get("enabled", False),
            "initial_capital": args.capital,
            "initial_capital_pct_of_total": cfg.get("initial_capital_pct_of_total"),
            "legs_enabled": cfg.get("legs_enabled"),
            "ensemble_mix": cfg.get("ensemble_mix"),
            "last_run_ts": pd.Timestamp.now(tz="Asia/Shanghai").isoformat(),
            "last_trading_day": last_str,
            "nav_series": [{"date": idx.strftime("%Y-%m-%d"), "nav": float(v)}
                           for idx, v in nav.items()],
            "last_nav": float(nav.iloc[-1]),
            "cum_return": float(nav.iloc[-1] / args.capital - 1),
            "pnl_today": float(nav.iloc[-1] - nav.iloc[-2]) if len(nav) >= 2 else 0.0,
            "daily_summary": {
                "n_buys": sum(1 for t in today_trades if t["action"] == "buy"),
                "n_sells": sum(1 for t in today_trades if t["action"] == "sell"),
                "turnover": 0.0,
                "gross_weight": float(gross_w),
                "cash_after": trader._cash(),
                "nav_after": float(nav.iloc[-1]),
                "skipped_buys": [],
                "dropped_no_price": [],
                "duplicate_skipped": [],
            },
            "today_trades": [
                {"symbol": str(t["symbol"]),
                 "action": str(t["action"]),
                 "shares": int(t["shares"]),
                 "price": float(t["price"]),
                 "cost": float(t["cost"])}
                for t in recent_trades
            ],
            "positions": [
                {"symbol": str(r["symbol"]),
                 "shares": int(r["shares"]),
                 "cost_price": float(r["cost_price"]),
                 "current_price": float(r["current_price"]),
                 "pnl_pct": float(r["pnl_pct"])}
                for _, r in active.iterrows()
            ],
            "open_entries_count": len(open_entries),
            "open_entries": [e.to_dict() for e in open_entries[:50]],
            "kill": {
                "action": kill.action.value,
                "position_scale": kill.position_scale(),
                "rolling_sr_30d": kill.rolling_sr_30d,
                "live_sharpe": kill.live_sharpe,
                "cum_drawdown": kill.cum_drawdown,
                "monthly_mdd": kill.monthly_mdd,
                "running_days": kill.running_days,
                "reasons": list(kill.reasons),
                "warnings": list(kill.warnings),
            },
            "_demo": True,  # so UI can flag
        }
        trader.close()

    STATE_OUT.parent.mkdir(parents=True, exist_ok=True)
    STATE_OUT.write_text(json.dumps(state, indent=2, ensure_ascii=False,
                                     default=float), encoding="utf-8")
    print(f"wrote {STATE_OUT}")
    print(f"  {len(state['nav_series'])} NAV days · "
          f"cum_return={state['cum_return']*100:.2f}% · "
          f"positions={len(state['positions'])} · "
          f"today_trades(last 30)={len(state['today_trades'])}")


if __name__ == "__main__":
    main()
