"""
Tier 1.3 Stress Test 单元测试.

用合成价格 + 合成事件验证 `replay_portfolio_in_event` 和 `check_hard_gates`,
不依赖真实市场数据. 每项测试独立可读.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from scripts.stress_test import (
    StressEvent,
    StressResult,
    check_hard_gates,
    load_events,
    replay_portfolio_in_event,
    summarize_results,
)


# ─────────────────────────────────────────────────────────────
# fixtures
# ─────────────────────────────────────────────────────────────

@pytest.fixture
def synthetic_prices():
    """5 只股 × 10 个交易日. 000001 每日 -5%, 000002 每日 +2%, 其他 flat."""
    dates = pd.bdate_range("2020-01-01", periods=10)
    n = len(dates)
    df = pd.DataFrame(index=dates)
    df["000001"] = 100.0 * (0.95 ** np.arange(n))   # 每日 -5%
    df["000002"] = 100.0 * (1.02 ** np.arange(n))   # 每日 +2%
    df["000003"] = 100.0                             # flat
    df["000004"] = np.nan                            # 全缺 (模拟未上市)
    df["000005"] = [100.0, 100.0, np.nan, np.nan, np.nan, 100.0, 100.0, 100.0, 100.0, 100.0]
    return df


@pytest.fixture
def synthetic_hs300(synthetic_prices):
    """HS300 每日 -1%. 长度同 synthetic_prices, +1 个 prior day."""
    dates = list(synthetic_prices.index)
    prior = dates[0] - pd.offsets.BDay(1)
    all_dates = [prior] + dates
    vals = 100.0 * (0.99 ** np.arange(len(all_dates)))
    return pd.Series(vals, index=all_dates, name="close")


@pytest.fixture
def crash_event():
    """事件 = 合成价格的中间 5 天."""
    return StressEvent(
        name="synthetic_crash",
        start_date="2020-01-06",    # 第 2 个交易日 (Monday)
        end_date="2020-01-10",      # 第 6 个交易日
        benchmark_return=-0.05,
        category="crash",
        description="test",
    )


# ─────────────────────────────────────────────────────────────
# replay_portfolio_in_event
# ─────────────────────────────────────────────────────────────

def test_replay_single_stock_matches_price_path(synthetic_prices, synthetic_hs300, crash_event):
    """100% 000001 (每日 -5%) 在 5 日事件期里累计收益应 ~ (0.95)^5 - 1."""
    weights = {"000001": 1.0}
    r = replay_portfolio_in_event(weights, crash_event, synthetic_prices, synthetic_hs300)

    expected = 0.95 ** 5 - 1
    assert r.model_return == pytest.approx(expected, abs=1e-6)
    assert r.worst_day_return == pytest.approx(-0.05, abs=1e-6)
    assert r.n_symbols == 1
    assert r.n_symbols_traded == 1
    assert r.n_symbols_missing == 0


def test_replay_two_stock_weighted_average(synthetic_prices, synthetic_hs300, crash_event):
    """50/50 的 000001(-5%) 和 000002(+2%), 每日组合收益 = 0.5*-5% + 0.5*+2% = -1.5%."""
    weights = {"000001": 0.5, "000002": 0.5}
    r = replay_portfolio_in_event(weights, crash_event, synthetic_prices, synthetic_hs300)

    daily = r.daily_returns.values
    assert np.allclose(daily, -0.015, atol=1e-6)


def test_replay_missing_symbol_filled_by_benchmark(
    synthetic_prices, synthetic_hs300, crash_event
):
    """未上市 symbol (000004, 全 NaN) 100% 权重, 应退化为 HS300 每日 -1% 收益率."""
    weights = {"000004": 1.0}
    r = replay_portfolio_in_event(
        weights, crash_event, synthetic_prices, synthetic_hs300, missing_fill="benchmark"
    )

    assert r.n_symbols_missing == 1
    assert r.n_symbols_traded == 0
    # HS300 每日 -1%, 5 日累计 -0.99^5 ≈ -0.0490
    assert r.model_return == pytest.approx(0.99 ** 5 - 1, abs=1e-6)


def test_replay_missing_symbol_zero_fill(synthetic_prices, synthetic_hs300, crash_event):
    """missing_fill=zero 时, 未上市 symbol 收益 0%, 累计 0%."""
    weights = {"000004": 1.0}
    r = replay_portfolio_in_event(
        weights, crash_event, synthetic_prices, synthetic_hs300, missing_fill="zero"
    )
    assert r.model_return == 0.0
    assert r.worst_day_return == 0.0


def test_replay_partial_missing_days_uses_benchmark(
    synthetic_prices, synthetic_hs300, crash_event
):
    """000005 有部分天 NaN (index 2-4), 缺失日用 HS300 收益率填."""
    weights = {"000005": 1.0}
    r = replay_portfolio_in_event(
        weights, crash_event, synthetic_prices, synthetic_hs300, missing_fill="benchmark"
    )
    # traded 但 partial; n_symbols_traded 计数"至少有一个有效日"
    assert r.n_symbols_traded == 1
    assert r.n_symbols_missing == 0


def test_replay_max_dd_is_peak_to_trough(synthetic_prices, synthetic_hs300):
    """构造 up-then-down, max_dd 应取峰谷差."""
    # 价格需包含事件起点之前的一个交易日作为 t0
    full_dates = pd.bdate_range("2020-01-01", periods=8)
    prices = pd.DataFrame(index=full_dates)
    # t0 = 100, 然后事件期 7 天 up-then-down
    prices["AAA"] = [100, 100, 105, 110, 115, 110, 100, 90]

    hs = pd.Series([100.0] * len(full_dates), index=full_dates, name="close")

    event = StressEvent(
        name="up_then_down",
        start_date=full_dates[1].strftime("%Y-%m-%d"),  # 第 2 天作为事件起点
        end_date=full_dates[-1].strftime("%Y-%m-%d"),
        benchmark_return=0.0,
        category="crash",
        description="",
    )
    weights = {"AAA": 1.0}
    r = replay_portfolio_in_event(weights, event, prices, hs)

    # peak at 115/100 = 1.15, trough at 90/100 = 0.90 → dd = 0.90/1.15 - 1 = -0.2174
    assert r.max_drawdown == pytest.approx(90 / 115 - 1, abs=1e-6)
    assert r.worst_day_return == pytest.approx(90 / 100 - 1, abs=1e-6)  # 最后一天 -10%


# ─────────────────────────────────────────────────────────────
# check_hard_gates
# ─────────────────────────────────────────────────────────────

def _make_result(
    name="test",
    category="crash",
    worst_day=-0.05,
    worst_week=-0.10,
    max_dd=-0.15,
):
    """辅助构造 StressResult."""
    ev = StressEvent(name, "2020-01-01", "2020-01-05", 0.0, category, "")
    return StressResult(
        event=ev,
        n_symbols=1, n_symbols_traded=1, n_symbols_missing=0,
        model_return=-0.10,
        benchmark_return=0.0,
        worst_day_date="2020-01-02",
        worst_day_return=worst_day,
        worst_week_return=worst_week,
        max_drawdown=max_dd,
        daily_returns=pd.Series([-0.01] * 5),
        cum_curve=pd.Series([1.0] * 5),
    )


def test_gate_pass_all_within_limits():
    gates = {"single_day_loss_pct": 0.08, "single_week_loss_pct": 0.15, "cumulative_max_dd_pct": 0.25}
    r = _make_result(worst_day=-0.05, worst_week=-0.10, max_dd=-0.15)
    ok, failures = check_hard_gates([r], gates)
    assert ok
    assert failures == []


def test_gate_fail_single_day():
    gates = {"single_day_loss_pct": 0.08, "single_week_loss_pct": 0.15, "cumulative_max_dd_pct": 0.25}
    r = _make_result(worst_day=-0.10)
    ok, failures = check_hard_gates([r], gates)
    assert not ok
    assert any("单日" in f for f in failures)


def test_gate_fail_max_dd():
    gates = {"single_day_loss_pct": 0.08, "single_week_loss_pct": 0.15, "cumulative_max_dd_pct": 0.25}
    r = _make_result(max_dd=-0.30)
    ok, failures = check_hard_gates([r], gates)
    assert not ok
    assert any("max DD" in f for f in failures)


def test_gate_rally_event_not_checked_on_loss_limits():
    """rally 事件 (上涨 stress) 只检查被大涨反向烫到的情况, 不检查 loss 硬门槛."""
    gates = {"single_day_loss_pct": 0.08, "single_week_loss_pct": 0.15, "cumulative_max_dd_pct": 0.25}
    # rally 事件 worst_week 合理为 +25%, max_dd 0, 不应被判 fail
    r = _make_result(category="rally", worst_day=+0.02, worst_week=+0.25, max_dd=0.0)
    ok, failures = check_hard_gates([r], gates)
    assert ok
    assert failures == []


def test_gate_rally_event_flags_only_on_short_side_burn():
    """若 rally 里反而掉了 > 8% (做空腿被反噬), 仍要 flag."""
    gates = {"single_day_loss_pct": 0.08, "single_week_loss_pct": 0.15, "cumulative_max_dd_pct": 0.25}
    r = _make_result(category="rally", worst_day=-0.12, worst_week=+0.10, max_dd=-0.12)
    ok, failures = check_hard_gates([r], gates)
    assert not ok
    assert any("rally" in f for f in failures)


# ─────────────────────────────────────────────────────────────
# 事件 JSON 解析
# ─────────────────────────────────────────────────────────────

def test_load_events_roundtrip(tmp_path: Path):
    """自己写一份最小 events.json, 验证解析."""
    payload = {
        "events": [
            {
                "name": "test",
                "start_date": "2020-01-01",
                "end_date": "2020-01-05",
                "benchmark_return": -0.05,
                "category": "crash",
                "description": "x",
            }
        ],
        "hard_gates": {"single_day_loss_pct": 0.08},
    }
    p = tmp_path / "ev.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    events, gates = load_events(p)
    assert len(events) == 1
    assert events[0].name == "test"
    assert gates["single_day_loss_pct"] == 0.08


def test_load_real_events_file_valid():
    """生产 events.json 能被正确解析, 且都有必需字段."""
    events, gates = load_events()
    assert len(events) >= 8, "spec 要求 8-10 个事件"
    for ev in events:
        assert ev.name
        assert ev.start_date
        assert ev.end_date
        assert ev.category in ("crash", "drawdown", "single_day", "rally")
    assert "single_day_loss_pct" in gates
    assert "single_week_loss_pct" in gates
    assert "cumulative_max_dd_pct" in gates


# ─────────────────────────────────────────────────────────────
# summarize_results
# ─────────────────────────────────────────────────────────────

def test_summarize_results_has_expected_columns():
    results = [_make_result(name="e1"), _make_result(name="e2")]
    df = summarize_results(results)
    assert len(df) == 2
    for col in ("event", "model_return", "benchmark_return", "relative",
                "worst_day_return", "worst_week_return", "max_drawdown"):
        assert col in df.columns
