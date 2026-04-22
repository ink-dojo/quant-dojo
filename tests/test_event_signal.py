"""Tests for pipeline/event_signal.py — DSR #30 causal daily signal generator."""
from __future__ import annotations

import pandas as pd
import pytest

from pipeline.event_signal import (
    BB_UNIT_WEIGHT,
    HOLD_DAYS,
    PV_UNIT_WEIGHT,
    TOP_PCT,
    THRESHOLD_WINDOW_DAYS,
    _compute_threshold,
    _previous_trading_day,
    _shift_trading_day,
    generate_daily_signal,
    generate_strict_match_signal,
)


def _make_trading_days(start="2025-01-02", n=60) -> pd.DatetimeIndex:
    """Approx. A-share trading calendar: weekdays only."""
    bd = pd.bdate_range(start=start, periods=n)
    return pd.DatetimeIndex(bd)


def _make_events(dates_signals_symbols: list[tuple[str, float, str]]) -> pd.DataFrame:
    """Convenience: build events df from list of (date_str, signal, symbol)."""
    rows = [{"event_date": pd.Timestamp(d), "signal": s, "symbol": sym}
            for d, s, sym in dates_signals_symbols]
    if not rows:
        return pd.DataFrame(columns=["event_date", "signal", "symbol"])
    return pd.DataFrame(rows).sort_values("event_date").reset_index(drop=True)


def test_previous_trading_day_normal():
    td = _make_trading_days("2025-06-02", 10)  # Mon 2025-06-02 onward
    # Wednesday's prior trading day = Tuesday
    assert _previous_trading_day(td, pd.Timestamp("2025-06-04")) == pd.Timestamp("2025-06-03")


def test_previous_trading_day_first_day_returns_none():
    td = _make_trading_days("2025-06-02", 5)
    assert _previous_trading_day(td, pd.Timestamp("2025-06-02")) is None


def test_shift_trading_day_forward():
    td = _make_trading_days("2025-06-02", 30)
    mon = pd.Timestamp("2025-06-02")
    # 5 trading days forward = next Mon (2025-06-09)
    assert _shift_trading_day(td, mon, 5) == pd.Timestamp("2025-06-09")


def test_shift_trading_day_out_of_range():
    td = _make_trading_days("2025-06-02", 5)
    last = td[-1]
    assert _shift_trading_day(td, last, 10) is None


def test_threshold_returns_none_when_insufficient_history():
    events = _make_events([
        ("2025-06-01", 1.0, "A"),
        ("2025-06-02", 2.0, "B"),
    ])
    as_of = pd.Timestamp("2025-06-10")
    assert _compute_threshold(events, as_of, 60) is None


def test_threshold_computes_correct_percentile():
    # 20 events with signals 1..20 in the window
    events = _make_events([
        (f"2025-05-{i:02d}", float(i), f"S{i}") for i in range(1, 21)
    ])
    as_of = pd.Timestamp("2025-06-10")  # window is 2025-04-11 to 2025-06-09
    thr = _compute_threshold(events, as_of, 60)
    # 70th percentile of 1..20 = 14.3 (linear interp: at index 0.7*19 = 13.3 → signal 14.3)
    assert thr == pytest.approx(14.3, abs=0.5)


def test_threshold_excludes_as_of_date():
    # Event on as_of itself should NOT be in window. 10 historical + 2 on as_of day.
    hist = [(f"2025-05-{i:02d}", float(i), f"H{i}") for i in range(20, 30)]  # May 20..29
    events = _make_events(hist + [
        ("2025-06-09", 9.0, "I"),
        ("2025-06-10", 10.0, "J"),
        ("2025-06-10", 999.0, "K"),  # same-day, should be excluded from threshold
    ])
    as_of = pd.Timestamp("2025-06-10")
    thr = _compute_threshold(events, as_of, 60)
    assert thr is not None
    assert thr < 100  # 999 excluded


def test_signal_admits_top_events_and_rejects_below():
    td = _make_trading_days("2025-04-01", 80)
    main_board = {f"S{i}" for i in range(1, 30)}

    # Build 25 events in trailing window (signals 1..25). Use td[30..54] so all
    # fall within 60 calendar days before as_of = td[60].
    lookback_events = [
        (td[30 + i].strftime("%Y-%m-%d"), float(i + 1), f"S{i+1}") for i in range(25)
    ]
    # as_of day: T+1 of the day we check. Candidates have event_date = T-1.
    as_of = td[60]
    prev_td = td[59]
    # Place one big candidate (signal=100, should pass) and one tiny (signal=2, should fail)
    candidate_events = [
        (prev_td.strftime("%Y-%m-%d"), 100.0, "S28"),
        (prev_td.strftime("%Y-%m-%d"), 2.0, "S29"),
    ]
    bb = _make_events(lookback_events + candidate_events)

    pv = _make_events([])  # empty

    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=bb,
        pv_events=pv,
        main_board_symbols=main_board,
    )
    admitted_syms = {e.symbol for e in sig.new_entries if e.leg == "bb"}
    assert "S28" in admitted_syms
    assert "S29" not in admitted_syms


def test_signal_only_uses_prev_trading_day_events():
    td = _make_trading_days("2025-04-01", 80)
    main_board = {"S1", "S2", "S3"}
    # Build history spread across trailing 60-day window before td[40]
    history = [(td[15 + i].strftime("%Y-%m-%d"), float(i + 1), f"H{i}") for i in range(20)]
    main_board.update(f"H{i}" for i in range(20))

    as_of = td[40]
    prev_td = td[39]
    two_days_ago = td[38]

    events = _make_events(history + [
        (prev_td.strftime("%Y-%m-%d"), 50.0, "S1"),
        (two_days_ago.strftime("%Y-%m-%d"), 50.0, "S2"),  # should be IGNORED
        (as_of.strftime("%Y-%m-%d"), 50.0, "S3"),          # today's event, IGNORED
    ])

    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=events,
        pv_events=_make_events([]),
        main_board_symbols=main_board,
    )
    admitted = {e.symbol for e in sig.new_entries}
    assert "S1" in admitted
    assert "S2" not in admitted
    assert "S3" not in admitted


def test_signal_filters_non_main_board():
    td = _make_trading_days("2025-04-01", 80)
    main_board = {"MAIN"}

    history = [(td[15 + i].strftime("%Y-%m-%d"), float(i + 1), f"MAIN") for i in range(20)]
    as_of = td[40]
    prev_td = td[39]
    bb = _make_events(history + [
        (prev_td.strftime("%Y-%m-%d"), 50.0, "MAIN"),
        (prev_td.strftime("%Y-%m-%d"), 50.0, "CHINEXT"),  # not main board
    ])

    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=bb,
        pv_events=_make_events([]),
        main_board_symbols=main_board,
    )
    syms = {e.symbol for e in sig.new_entries}
    assert "MAIN" in syms
    assert "CHINEXT" not in syms


def test_signal_sets_entry_and_exit_dates():
    td = _make_trading_days("2025-04-01", 80)
    main_board = {"S1"}
    # Spread history across trailing window of as_of = td[50] (need ≥10 in window)
    history = [(td[25 + i].strftime("%Y-%m-%d"), float(i + 1), "S1") for i in range(15)]
    as_of = td[50]
    prev_td = td[49]
    exit_expected = td[50 + HOLD_DAYS]
    bb = _make_events(history + [(prev_td.strftime("%Y-%m-%d"), 100.0, "S1")])

    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=bb,
        pv_events=_make_events([]),
        main_board_symbols=main_board,
    )
    assert len(sig.new_entries) == 1
    e = sig.new_entries[0]
    assert e.entry_date == as_of.strftime("%Y-%m-%d")
    assert e.exit_date == exit_expected.strftime("%Y-%m-%d")
    assert e.unit_weight == BB_UNIT_WEIGHT


def test_signal_rejects_non_trading_day_as_of():
    td = _make_trading_days("2025-04-01", 80)
    saturday = pd.Timestamp("2025-04-05")  # not in bdate_range
    with pytest.raises(ValueError, match="not a trading day"):
        generate_daily_signal(
            as_of_date=saturday,
            trading_days=td,
            bb_events=_make_events([]),
            pv_events=_make_events([]),
            main_board_symbols=set(),
        )


def test_signal_deduplicates_same_symbol_same_day():
    td = _make_trading_days("2025-04-01", 80)
    main_board = {"S1"}
    history = [(td[15 + i].strftime("%Y-%m-%d"), float(i + 1), "S1") for i in range(15)]
    as_of = td[40]
    prev_td = td[39]
    # Same symbol, same day, two events (unusual but possible)
    bb = _make_events(history + [
        (prev_td.strftime("%Y-%m-%d"), 50.0, "S1"),
        (prev_td.strftime("%Y-%m-%d"), 80.0, "S1"),
    ])
    sig = generate_daily_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=bb,
        pv_events=_make_events([]),
        main_board_symbols=main_board,
    )
    s1_entries = [e for e in sig.new_entries if e.symbol == "S1"]
    assert len(s1_entries) == 1
    assert s1_entries[0].signal == 80.0  # kept the bigger


def test_signal_respects_legs_enabled_pv_off():
    """spec v3: legs_enabled={bb:True, pv:False} → PV admissions always 0."""
    td = _make_trading_days("2025-04-01", 80)
    main_board = {f"S{i}" for i in range(30)}

    as_of = td[60]
    prev_td = td[59]
    history = [(td[30 + i].strftime("%Y-%m-%d"), float(i + 1), f"S{i+1}") for i in range(25)]
    # BB candidate (signal 100) + PV candidate (signal 100) both with enough history
    bb = _make_events(history + [(prev_td.strftime("%Y-%m-%d"), 100.0, "S28")])
    pv = _make_events(history + [(prev_td.strftime("%Y-%m-%d"), 100.0, "S29")])

    # Default: both legs → both admitted
    sig_both = generate_daily_signal(
        as_of_date=as_of, trading_days=td,
        bb_events=bb, pv_events=pv, main_board_symbols=main_board,
    )
    legs_both = {e.leg for e in sig_both.new_entries}
    assert "bb" in legs_both
    assert "pv" in legs_both

    # BB-only: pv admissions == 0
    sig_bb_only = generate_daily_signal(
        as_of_date=as_of, trading_days=td,
        bb_events=bb, pv_events=pv, main_board_symbols=main_board,
        legs_enabled={"bb": True, "pv": False},
    )
    assert sig_bb_only.stats["pv_admitted"] == 0
    assert sig_bb_only.stats["pv_candidates"] == 0
    assert sig_bb_only.stats["bb_admitted"] > 0
    assert all(e.leg == "bb" for e in sig_bb_only.new_entries)


def test_unit_weights_match_backtest_formula():
    # BB: 1/15 × (0.8/0.403) ≈ 0.1323
    assert BB_UNIT_WEIGHT == pytest.approx(1.0 / 15 * (0.8 / 0.403), rel=1e-9)
    # PV: 1/75 × (0.8/0.350) ≈ 0.03048
    assert PV_UNIT_WEIGHT == pytest.approx(1.0 / 75 * (0.8 / 0.350), rel=1e-9)


def test_strict_match_signal_picks_month_top_30pct():
    td = _make_trading_days("2025-06-02", 25)
    main_board = {f"S{i}" for i in range(1, 30)}

    # 10 events in one month, signals 1..10
    month_events = [
        (td[i].strftime("%Y-%m-%d"), float(i + 1), f"S{i+1}") for i in range(10)
    ]
    bb = _make_events(month_events)
    # Pick an as_of where prev_td is one of the high-signal events
    as_of = td[9]
    prev_td = td[8]

    sig = generate_strict_match_signal(
        as_of_date=as_of,
        trading_days=td,
        bb_events=bb,
        pv_events=_make_events([]),
        main_board_symbols=main_board,
    )
    # top 30% of 10 = 3 → signals 10, 9, 8. If prev_td's event has signal 9 → admitted.
    admitted = [e for e in sig.new_entries if e.leg == "bb"]
    # S9 has signal 9, event on td[8] (prev_td). S9 is in top 3 → admitted
    assert any(e.symbol == "S9" for e in admitted)
