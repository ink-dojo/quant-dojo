"""Tests for live/event_paper_trader.py — DSR #30 event-driven trader."""
from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import pandas as pd
import pytest

from live.event_paper_trader import (
    DEFAULT_COST_RATE,
    EventPaperTrader,
    OpenEntry,
)
from pipeline.event_signal import (
    BB_UNIT_WEIGHT,
    ENSEMBLE_MIX,
    EventEntry,
    PV_UNIT_WEIGHT,
)


@pytest.fixture
def tmp_portfolio():
    d = Path(tempfile.mkdtemp(prefix="ept_test_"))
    yield d
    shutil.rmtree(d, ignore_errors=True)


def _bb_entry(symbol: str, entry_date: str, exit_date: str,
              signal: float = 5.0) -> EventEntry:
    return EventEntry(
        symbol=symbol, leg="bb",
        event_date=entry_date, entry_date=entry_date, exit_date=exit_date,
        unit_weight=BB_UNIT_WEIGHT, signal=signal, threshold=3.0,
    )


def _pv_entry(symbol: str, entry_date: str, exit_date: str,
              signal: float = 50.0) -> EventEntry:
    return EventEntry(
        symbol=symbol, leg="pv",
        event_date=entry_date, entry_date=entry_date, exit_date=exit_date,
        unit_weight=PV_UNIT_WEIGHT, signal=signal, threshold=25.0,
    )


def test_trader_opens_position_at_unit_weight(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    entries = [_bb_entry("600000", "2025-06-16", "2025-07-14")]
    prices = {"600000": 10.0}
    summary = trader.process_day("2025-06-16", entries, prices)

    assert summary["n_buys"] == 1
    assert summary["n_sells"] == 0
    # Target weight for 1 BB entry = 0.5 × 0.1323 ≈ 0.0661
    expected_gross = ENSEMBLE_MIX * BB_UNIT_WEIGHT
    assert summary["gross_weight"] == pytest.approx(expected_gross, abs=1e-4)
    # Actual position should be close to target_value / price (whole shares)
    expected_dollars = expected_gross * 1_000_000
    assert trader.positions["600000"]["shares"] > 0
    actual_value = trader.positions["600000"]["shares"] * 10.0
    assert actual_value <= expected_dollars  # should not overshoot
    assert actual_value >= expected_dollars * 0.98  # but close
    trader.close()


def test_trader_expires_at_exit_date(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    # Enter on day 1 with exit_date = day 3
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-06-18")],
                       {"600000": 10.0})
    assert "600000" in trader.positions
    # Day 2: still active (exit_date > today)
    trader.process_day("2025-06-17", [], {"600000": 10.1})
    assert "600000" in trader.positions
    # Day 3: exit_date == today → position should close (exit_date > today fails)
    trader.process_day("2025-06-18", [], {"600000": 10.2})
    # Position sold out (or zero shares)
    assert trader.positions.get("600000", {"shares": 0})["shares"] == 0 \
        or "600000" not in trader.positions
    assert len(trader.open_entries) == 0
    trader.close()


def test_trader_bb_and_pv_on_same_symbol(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    entries = [
        _bb_entry("600000", "2025-06-16", "2025-07-14"),
        _pv_entry("600000", "2025-06-16", "2025-07-14"),
    ]
    summary = trader.process_day("2025-06-16", entries, {"600000": 10.0})
    # Target = 0.5 × (BB_UNIT + PV_UNIT)
    expected = ENSEMBLE_MIX * (BB_UNIT_WEIGHT + PV_UNIT_WEIGHT)
    assert summary["gross_weight"] == pytest.approx(expected, abs=1e-4)
    assert len(trader.open_entries) == 2
    # But only one position (same symbol)
    assert len([k for k in trader.positions if k != "__cash__"]) == 1
    trader.close()


def test_trader_leg_gross_cap_scales_down(tmp_portfolio):
    """If many BB entries push leg > 1.0, they get scaled proportionally."""
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    # BB_UNIT ≈ 0.1323, 10 entries → sum = 1.323 > 1.0 → scale to 1.0
    entries = [
        _bb_entry(f"60000{i}", "2025-06-16", "2025-07-14") for i in range(10)
    ]
    prices = {f"60000{i}": 10.0 for i in range(10)}
    summary = trader.process_day("2025-06-16", entries, prices)
    # After leg cap: each sym gets 0.1 (= 1/10), then × 0.5 ensemble → 0.05 each
    # Total = 10 × 0.05 = 0.5 ≤ 1.0 so no portfolio cap
    assert summary["gross_weight"] == pytest.approx(ENSEMBLE_MIX, abs=1e-4)
    trader.close()


def test_trader_portfolio_gross_cap(tmp_portfolio):
    """Combined BB+PV at full cap hit portfolio-level cap of 1.0 (not 1.5 = 0.5*3)."""
    # Use synthetic large unit weights to force portfolio-level cap
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    # Manually stuff open_entries with UNIT=1.0 each to test the cap logic
    trader.open_entries = [
        OpenEntry(symbol="A", leg="bb", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=1.0, signal=1, entry_price=10.0),
        OpenEntry(symbol="B", leg="pv", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=1.0, signal=1, entry_price=10.0),
    ]
    weights = trader._compute_target_weights()
    # Each leg already at cap (1.0), mix gives A=0.5, B=0.5, sum=1.0 (no extra cap)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)
    assert weights["A"] == pytest.approx(0.5, abs=1e-4)
    assert weights["B"] == pytest.approx(0.5, abs=1e-4)

    # Now push BOTH legs way past 1.0; expect them both scaled to 1.0 then mixed
    trader.open_entries = [
        OpenEntry(symbol="A", leg="bb", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=2.0, signal=1, entry_price=10.0),
        OpenEntry(symbol="C", leg="bb", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=2.0, signal=1, entry_price=10.0),
        OpenEntry(symbol="B", leg="pv", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=3.0, signal=1, entry_price=10.0),
        OpenEntry(symbol="D", leg="pv", entry_date="2025-06-16",
                  exit_date="2025-07-14", unit_weight=1.0, signal=1, entry_price=10.0),
    ]
    weights = trader._compute_target_weights()
    # BB leg: A=2, C=2 → sum 4 → scale /4 → A=0.5, C=0.5
    # PV leg: B=3, D=1 → sum 4 → scale /4 → B=0.75, D=0.25
    # Portfolio: A=0.25, C=0.25, B=0.375, D=0.125; sum=1.0 → no extra cap
    assert weights["A"] == pytest.approx(0.25, abs=1e-4)
    assert weights["C"] == pytest.approx(0.25, abs=1e-4)
    assert weights["B"] == pytest.approx(0.375, abs=1e-4)
    assert weights["D"] == pytest.approx(0.125, abs=1e-4)
    assert sum(weights.values()) == pytest.approx(1.0, abs=1e-4)
    trader.close()


def test_trader_persists_and_reloads(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-07-14")],
                       {"600000": 10.0})
    first_nav = trader._nav({"600000": 10.0})
    first_shares = trader.positions["600000"]["shares"]
    trader.close()

    # Reload
    trader2 = EventPaperTrader(1_000_000, tmp_portfolio)
    assert len(trader2.open_entries) == 1
    assert trader2.open_entries[0].symbol == "600000"
    assert trader2.positions["600000"]["shares"] == first_shares
    assert trader2._nav({"600000": 10.0}) == pytest.approx(first_nav, abs=0.01)
    trader2.close()


def test_trader_nav_series_grows_with_winning_trade(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-07-14")],
                       {"600000": 10.0})
    # Price rises 20% after entry
    trader.process_day("2025-06-17", [], {"600000": 12.0})
    nav_series = trader.nav_series()
    assert len(nav_series) == 2
    assert nav_series.iloc[1] > nav_series.iloc[0]
    # Expected gain ≈ 0.5 × BB_UNIT × 0.2 = 0.0132 on NAV = 1M → ~13K
    # (minus cost, plus slight discretization)
    gain = nav_series.iloc[1] - 1_000_000
    assert 10_000 < gain < 15_000
    trader.close()


def test_trader_handles_missing_price(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    entries = [
        _bb_entry("600000", "2025-06-16", "2025-07-14"),
        _bb_entry("600001", "2025-06-16", "2025-07-14"),
    ]
    # Only 600000 has a price; 600001 should be silently dropped (can't fill)
    summary = trader.process_day("2025-06-16", entries, {"600000": 10.0})
    assert summary["n_buys"] == 1
    syms = {e.symbol for e in trader.open_entries}
    assert "600000" in syms
    assert "600001" not in syms
    trader.close()


def test_trader_cost_rate_deducts_correctly(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio, cost_rate=0.001)
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-07-14")],
                       {"600000": 10.0})
    # Cash reduction should match shares × price × (1 + cost_rate)
    info = trader.positions["600000"]
    expected_cash = 1_000_000 - info["shares"] * 10.0 * 1.001
    assert trader._cash() == pytest.approx(expected_cash, abs=0.01)
    trader.close()


def test_trader_no_overshoot_on_gross_cap(tmp_portfolio):
    """Adding many entries shouldn't let gross_weight exceed 1.0."""
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    # Add 20 BB + 50 PV entries — well over any single-leg cap
    entries = []
    prices = {}
    for i in range(20):
        sym = f"60{i:04d}"
        entries.append(_bb_entry(sym, "2025-06-16", "2025-07-14"))
        prices[sym] = 10.0
    for i in range(50):
        sym = f"70{i:04d}"
        entries.append(_pv_entry(sym, "2025-06-16", "2025-07-14"))
        prices[sym] = 10.0
    summary = trader.process_day("2025-06-16", entries, prices)
    assert summary["gross_weight"] <= 1.0 + 1e-4
    trader.close()


def test_trader_tracks_trade_costs_in_trades(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-07-14")],
                       {"600000": 10.0})
    assert len(trader.trades) == 1
    t = trader.trades[0]
    assert t["action"] == "buy"
    assert t["symbol"] == "600000"
    assert t["cost"] == pytest.approx(t["shares"] * t["price"] * DEFAULT_COST_RATE,
                                     abs=0.01)
    trader.close()


def test_trader_active_positions_df_pnl(tmp_portfolio):
    trader = EventPaperTrader(1_000_000, tmp_portfolio)
    trader.process_day("2025-06-16",
                       [_bb_entry("600000", "2025-06-16", "2025-07-14")],
                       {"600000": 10.0})
    trader.process_day("2025-06-17", [], {"600000": 11.0})  # +10%
    df = trader.active_positions_df()
    assert len(df) == 1
    assert df.iloc[0]["pnl_pct"] == pytest.approx(0.10, abs=1e-4)
    trader.close()


def test_trader_bb_only_mode_doubles_weight(tmp_portfolio):
    """spec v3: ensemble_mix={bb:1.0, pv:0.0} → BB position at full UNIT, no 0.5 scale."""
    trader = EventPaperTrader(
        1_000_000, tmp_portfolio,
        ensemble_mix={"bb": 1.0, "pv": 0.0},
    )
    entries = [_bb_entry("600000", "2025-06-16", "2025-07-14")]
    summary = trader.process_day("2025-06-16", entries, {"600000": 10.0})
    # Target weight = 1.0 × BB_UNIT = 0.1323, not 0.5 × BB_UNIT
    assert summary["gross_weight"] == pytest.approx(BB_UNIT_WEIGHT, abs=1e-4)
    trader.close()


def test_trader_bb_only_ignores_pv_entries(tmp_portfolio):
    """spec v3: ensemble_mix.pv=0 → any PV entries get zero weight even if supplied."""
    trader = EventPaperTrader(
        1_000_000, tmp_portfolio,
        ensemble_mix={"bb": 1.0, "pv": 0.0},
    )
    entries = [
        _bb_entry("600000", "2025-06-16", "2025-07-14"),
        _pv_entry("600001", "2025-06-16", "2025-07-14"),
    ]
    summary = trader.process_day("2025-06-16", entries,
                                  {"600000": 10.0, "600001": 10.0})
    # Only BB got weight; PV mixed with 0.0 → 0
    assert summary["gross_weight"] == pytest.approx(BB_UNIT_WEIGHT, abs=1e-4)
    # PV entry is still recorded in open_entries (will be pruned at exit_date)
    # but its position weight is zero so it shouldn't be bought
    assert "600001" not in trader.positions or \
           trader.positions.get("600001", {"shares": 0})["shares"] == 0
    trader.close()


def test_trader_idempotent_on_same_day_retry(tmp_portfolio):
    """Cron 重试: 同一交易日跑两次 process_day 不应该让 open_entries 翻倍."""
    entry = _bb_entry("600000", "2025-06-16", "2025-07-14")

    # First run
    trader1 = EventPaperTrader(1_000_000, tmp_portfolio)
    summary1 = trader1.process_day("2025-06-16", [entry], {"600000": 10.0})
    shares_after_first = trader1.positions["600000"]["shares"]
    n_open_first = len(trader1.open_entries)
    trader1.close()
    assert n_open_first == 1
    assert summary1.get("duplicate_skipped", []) == []

    # Second run same day (simulate cron retry after transient failure)
    trader2 = EventPaperTrader(1_000_000, tmp_portfolio)
    summary2 = trader2.process_day("2025-06-16", [entry], {"600000": 10.0})
    # open_entries must still be 1 — de-duped by (symbol, leg, entry_date)
    assert len(trader2.open_entries) == 1
    # duplicate should be reported
    assert "bb:600000" in summary2["duplicate_skipped"]
    # shares unchanged (no second buy)
    assert trader2.positions["600000"]["shares"] == shares_after_first
    # no new trade row appended
    assert summary2["n_buys"] == 0
    trader2.close()
