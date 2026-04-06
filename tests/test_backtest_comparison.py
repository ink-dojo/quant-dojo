"""
tests/test_backtest_comparison.py — 策略对比报告测试
"""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import patch

from backtest.standardized import BacktestConfig, BacktestResult
from backtest.comparison import generate_comparison_report


def _make_result(strategy="v7", n_stocks=30, seed=42):
    np.random.seed(seed)
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    returns = pd.Series(np.random.randn(252) * 0.01, index=dates)
    equity = pd.DataFrame({"portfolio_return": returns}, index=dates)

    total_ret = float((1 + returns).prod() - 1)
    return BacktestResult(
        config=BacktestConfig(strategy=strategy, start="2024-01-01", end="2024-12-31", n_stocks=n_stocks),
        metrics={
            "total_return": total_ret,
            "annualized_return": total_ret,
            "sharpe": 0.85,
            "max_drawdown": -0.12,
            "calmar": 0.7,
            "win_rate": 0.52,
            "n_trading_days": 252,
        },
        equity_curve=equity,
        status="success",
        run_id=f"{strategy}_{n_stocks}_{seed}",
    )


class TestComparisonReport:
    def test_generates_html(self, tmp_path):
        r1 = _make_result("v7", 30, seed=42)
        r2 = _make_result("v8", 50, seed=99)

        with patch("backtest.comparison.RUNS_DIR", tmp_path):
            path = generate_comparison_report([r1, r2], title="Test Compare")

        assert path.exists()
        content = path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "v7" in content
        assert "v8" in content
        assert "compareChart" in content

    def test_filters_failed_results(self, tmp_path):
        r1 = _make_result("v7")
        r_fail = BacktestResult(
            config=BacktestConfig(strategy="v8", start="2024-01-01", end="2024-12-31"),
            status="failed", error="no data",
        )

        with patch("backtest.comparison.RUNS_DIR", tmp_path):
            path = generate_comparison_report([r1, r_fail])

        content = path.read_text()
        assert "v7" in content
        # v8 should not appear in metrics table since it failed
        assert content.count("<tr>") < 5  # header + 1 data row + </tr>

    def test_raises_on_no_valid(self):
        r_fail = BacktestResult(
            config=BacktestConfig(strategy="v7", start="2024-01-01", end="2024-12-31"),
            status="failed",
        )
        with pytest.raises(ValueError, match="无有效"):
            generate_comparison_report([r_fail])

    def test_multiple_strategies(self, tmp_path):
        results = [_make_result("v7", n, seed=n) for n in [10, 20, 30, 50]]

        with patch("backtest.comparison.RUNS_DIR", tmp_path):
            path = generate_comparison_report(results, title="N-stocks sweep")

        content = path.read_text()
        assert "n=10" in content
        assert "n=50" in content
