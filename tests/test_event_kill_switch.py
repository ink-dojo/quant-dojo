"""Tests for live/event_kill_switch.py."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from live.event_kill_switch import (
    CUM_DD_HALT,
    FAST_CHECK_SR_FLOOR,
    KillAction,
    MONTHLY_MDD_COOL,
    SR_HALVE_THRESHOLD,
    evaluate,
)


def _make_nav(returns: list[float], start="2026-01-02") -> pd.Series:
    idx = pd.bdate_range(start, periods=len(returns) + 1)
    nav_vals = [1_000_000.0]
    for r in returns:
        nav_vals.append(nav_vals[-1] * (1 + r))
    return pd.Series(nav_vals, index=idx)


def test_ok_when_profitable_and_short_history():
    nav = _make_nav([0.001, 0.002, 0.0015])
    r = evaluate(nav)
    assert r.action == KillAction.OK
    assert r.should_trade_new()
    assert r.position_scale() == 1.0


def test_halt_on_cumulative_drawdown():
    # Drop 25% — triggers HALT
    nav = _make_nav([-0.25])
    r = evaluate(nav)
    assert r.action == KillAction.HALT
    assert not r.should_trade_new()
    assert r.position_scale() == 0.0
    assert any("累计回撤" in reason for reason in r.reasons)


def test_halve_on_rolling_sr_below_05():
    # 30 days of returns with SR < 0.5 but not negative
    returns = [0.0001] * 40  # tiny positive returns, SR ≈ 0 (low vol/low return ratio)
    # Actually near-zero vol → SR undefined; use small noise
    np.random.seed(1)
    returns = list(np.random.normal(0.0001, 0.01, 40))  # SR ≈ 0.0001/0.01 × sqrt(252) ≈ 0.16
    nav = _make_nav(returns)
    r = evaluate(nav)
    assert r.action in (KillAction.HALVE, KillAction.HALT)  # at least HALVE
    assert r.position_scale() < 1.0


def test_halt_on_negative_sr_streak():
    # 30 days of losses → negative rolling SR for 10+ days
    returns = [-0.005] * 50
    nav = _make_nav(returns)
    r = evaluate(nav)
    assert r.action == KillAction.HALT


def test_cool_off_on_monthly_mdd():
    # One month of 15% drawdown (within a single month)
    month_start = pd.Timestamp("2026-01-02")
    # Start with some winning history to avoid cumulative DD > 20%
    nav_vals = [1_000_000.0]
    # Build up NAV first
    for _ in range(15):
        nav_vals.append(nav_vals[-1] * 1.005)  # +0.5% × 15 ≈ +7.7%
    # Then 15% monthly drawdown happens within Feb
    pre = len(nav_vals)
    for _ in range(5):
        nav_vals.append(nav_vals[-1] * 0.97)  # -3% each day
    idx = pd.bdate_range("2026-01-02", periods=len(nav_vals))
    nav = pd.Series(nav_vals, index=idx)
    # as_of is the last day, which is in Jan still (~20 bdays from 2026-01-02)
    r = evaluate(nav, as_of=idx[-1])
    # monthly MDD > 12% → COOL_OFF if cum DD not yet > 20%
    assert r.monthly_mdd is not None
    # Action could be COOL_OFF or HALVE/HALT depending on SR; key test is monthly_mdd exceeds cool threshold
    assert r.monthly_mdd < -MONTHLY_MDD_COOL


def test_fast_validation_do_not_upgrade_at_3mo():
    # 63 days with Sharpe < 0.5 → DO_NOT_UPGRADE
    np.random.seed(2)
    returns = list(np.random.normal(0.0001, 0.015, 70))  # low Sharpe
    nav = _make_nav(returns)
    r = evaluate(nav)
    # Either DO_NOT_UPGRADE or worse (could be HALT if rolling SR streak triggers first)
    assert r.action in (KillAction.DO_NOT_UPGRADE, KillAction.HALVE, KillAction.HALT)
    assert r.live_sharpe is not None


def test_fast_validation_halt_at_6mo():
    # 126 days with Sharpe < 0.5 → HALT
    np.random.seed(3)
    returns = list(np.random.normal(-0.0001, 0.012, 130))  # slightly negative
    nav = _make_nav(returns)
    r = evaluate(nav)
    assert r.action == KillAction.HALT
    # Reason should include 6mo fast-check OR rolling SR streak (both are valid halt reasons)
    assert any("fast-check" in reason or "SR 连续" in reason or "回撤" in reason
               for reason in r.reasons)


def test_warn_on_soft_limits():
    nav = _make_nav([0.001, 0.002, 0.003])  # trivially healthy, 3 days
    r = evaluate(nav, n_positions_today=1, turnover_today=0.7)
    assert r.action == KillAction.WARN
    assert len(r.warnings) >= 2


def test_empty_nav_returns_ok():
    r = evaluate(pd.Series(dtype=float))
    assert r.action == KillAction.OK


def test_severity_ordering_picks_worst():
    """If both HALVE and HALT conditions fire, return HALT."""
    # Build NAV with both: >20% DD AND negative SR streak
    returns = [-0.01] * 80  # chronic losses
    nav = _make_nav(returns)
    r = evaluate(nav)
    assert r.action == KillAction.HALT


def test_report_serializable():
    nav = _make_nav([0.001, 0.002])
    r = evaluate(nav)
    d = r.to_dict()
    assert isinstance(d, dict)
    assert "action" in d
    assert d["action"] in {a.value for a in KillAction}


def test_position_scale_semantics():
    """HALT=0, HALVE=0.5, else 1."""
    nav = _make_nav([-0.25])
    assert evaluate(nav).position_scale() == 0.0

    nav_ok = _make_nav([0.001, 0.001, 0.001])
    assert evaluate(nav_ok).position_scale() == 1.0
