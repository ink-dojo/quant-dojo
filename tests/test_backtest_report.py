"""
tests/test_backtest_report.py — 回测报告生成测试
"""
import numpy as np
import pandas as pd
import pytest
from pathlib import Path
from unittest.mock import patch

from backtest.standardized import BacktestConfig, BacktestResult
from backtest.report import (
    generate_html_report,
    _render_metrics_table,
    _render_factor_table,
    _render_config_table,
    _render_trade_log,
    _render_correlation_matrix,
    _render_monthly_heatmap,
    _compute_monthly_returns,
    _heatmap_color,
)


# ═══════════════════════════════════════════════════════════
# Helper
# ═══════════════════════════════════════════════════════════

def _make_result():
    """Create a minimal BacktestResult for testing"""
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=252, freq="B")
    returns = pd.Series(np.random.randn(252) * 0.01, index=dates)
    equity = pd.DataFrame({
        "portfolio_return": returns,
        "cumulative_return": (1 + returns).cumprod() - 1,
    }, index=dates)

    config = BacktestConfig(strategy="v7", start="2024-01-01", end="2024-12-31")

    return BacktestResult(
        config=config,
        metrics={
            "total_return": 0.0523,
            "annualized_return": 0.0523,
            "sharpe": 0.85,
            "max_drawdown": -0.12,
            "annualized_volatility": 0.15,
            "calmar": 0.44,
            "win_rate": 0.52,
            "profit_loss_ratio": 1.1,
            "n_trading_days": 252,
        },
        equity_curve=equity,
        factor_stats={
            "team_coin": {"ic_mean": 0.03, "ic_std": 0.06, "icir": 0.5, "direction": 1},
            "low_vol_20d": {"ic_mean": 0.05, "ic_std": 0.08, "icir": 0.625, "direction": 1},
        },
        trade_log=[
            {"date": "2024-01-02", "n_holdings": 30, "n_buys": 30, "n_sells": 0,
             "buys": ["000001", "000002"], "sells": [], "turnover": 1.0, "cost": 0.0003},
            {"date": "2024-02-01", "n_holdings": 30, "n_buys": 10, "n_sells": 10,
             "buys": ["000010", "000011"], "sells": ["000001"], "turnover": 0.33, "cost": 0.0001},
        ],
        run_id="test_report_001",
        status="success",
    )


# ═══════════════════════════════════════════════════════════
# Metrics rendering
# ═══════════════════════════════════════════════════════════

class TestRenderMetrics:
    def test_empty_metrics(self):
        html = _render_metrics_table({})
        assert "无指标数据" in html

    def test_basic_metrics(self):
        html = _render_metrics_table({
            "total_return": 0.05, "sharpe": 1.2, "max_drawdown": -0.1,
            "annualized_return": 0.05, "annualized_volatility": 0.15,
            "calmar": 0.33, "win_rate": 0.55, "profit_loss_ratio": 1.1,
        })
        assert "5.00%" in html
        assert "1.20" in html
        assert "metric-box" in html

    def test_with_benchmark(self):
        html = _render_metrics_table(
            {"total_return": 0.1, "sharpe": 1.5, "max_drawdown": -0.05,
             "annualized_return": 0.1, "annualized_volatility": 0.1,
             "calmar": 2.0, "win_rate": 0.6, "profit_loss_ratio": 1.5,
             "excess_return": 0.05, "excess_sharpe": 0.8},
            benchmark_metrics={"total_return": 0.05, "sharpe": 0.7, "max_drawdown": -0.15},
        )
        assert "超额收益" in html
        assert "基准总收益" in html

    def test_negative_returns_colored(self):
        html = _render_metrics_table({
            "total_return": -0.1, "annualized_return": -0.1,
            "sharpe": -0.5, "max_drawdown": -0.3,
            "annualized_volatility": 0.2, "calmar": -0.33,
            "win_rate": 0.4, "profit_loss_ratio": 0.8,
        })
        assert "negative" in html


# ═══════════════════════════════════════════════════════════
# Factor table
# ═══════════════════════════════════════════════════════════

class TestRenderFactorTable:
    def test_empty(self):
        assert "无因子数据" in _render_factor_table({})

    def test_with_factors(self):
        html = _render_factor_table({
            "momentum": {"ic_mean": 0.03, "ic_std": 0.05, "icir": 0.6, "direction": 1},
        })
        assert "momentum" in html
        assert "0.0300" in html
        assert "正向" in html

    def test_reverse_direction(self):
        html = _render_factor_table({
            "vol": {"ic_mean": -0.02, "ic_std": 0.04, "icir": -0.5, "direction": -1},
        })
        assert "反向" in html


# ═══════════════════════════════════════════════════════════
# Config table
# ═══════════════════════════════════════════════════════════

class TestRenderConfigTable:
    def test_renders_all_fields(self):
        config = BacktestConfig(strategy="v7", start="2024-01-01", end="2025-12-31")
        html = _render_config_table(config)
        assert "v7" in html
        assert "2024-01-01" in html
        assert "30" in html  # n_stocks default


# ═══════════════════════════════════════════════════════════
# Trade log
# ═══════════════════════════════════════════════════════════

class TestRenderCorrelationMatrix:
    def test_empty(self):
        assert "无相关性数据" in _render_correlation_matrix(None)

    def test_with_data(self):
        corr = {
            "momentum": {"momentum": 1.0, "vol": 0.3},
            "vol": {"momentum": 0.3, "vol": 1.0},
        }
        html = _render_correlation_matrix(corr)
        assert "momentum" in html
        assert "1.00" in html
        assert "0.30" in html

    def test_high_correlation_highlighted(self):
        corr = {
            "a": {"a": 1.0, "b": 0.85},
            "b": {"a": 0.85, "b": 1.0},
        }
        html = _render_correlation_matrix(corr)
        assert "#ff7675" in html  # high correlation color


class TestRenderTradeLog:
    def test_empty(self):
        assert "无调仓记录" in _render_trade_log([])

    def test_with_trades(self):
        trades = [
            {"date": "2024-01-02", "n_holdings": 30, "n_buys": 10, "n_sells": 5,
             "buys": ["A", "B"], "sells": ["C"], "turnover": 0.33, "cost": 0.0001},
        ]
        html = _render_trade_log(trades)
        assert "2024-01-02" in html
        assert "A, B" in html
        assert "33.0%" in html

    def test_truncates_long_lists(self):
        trades = [
            {"date": "2024-01-02", "n_holdings": 30, "n_buys": 8, "n_sells": 0,
             "buys": [f"S{i}" for i in range(8)], "sells": [], "turnover": 1.0, "cost": 0.0003},
        ]
        html = _render_trade_log(trades)
        assert "+3" in html  # 8 buys, shows 5 + "+3"


# ═══════════════════════════════════════════════════════════
# Monthly returns
# ═══════════════════════════════════════════════════════════

class TestMonthlyReturns:
    def test_compute_monthly(self):
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        returns = pd.Series(0.001, index=dates)
        monthly = _compute_monthly_returns(returns)
        assert not monthly.empty
        assert 2024 in monthly.index

    def test_heatmap_render(self):
        dates = pd.date_range("2024-01-01", periods=252, freq="B")
        returns = pd.Series(0.001, index=dates)
        monthly = _compute_monthly_returns(returns)
        html = _render_monthly_heatmap(monthly)
        assert "2024" in html
        assert "heatmap-table" in html

    def test_empty_heatmap(self):
        html = _render_monthly_heatmap(pd.DataFrame())
        assert "无月度数据" in html


# ═══════════════════════════════════════════════════════════
# Heatmap color
# ═══════════════════════════════════════════════════════════

class TestHeatmapColor:
    def test_positive_colors(self):
        assert _heatmap_color(0.06) == "#00b894"
        assert _heatmap_color(0.03) == "#55efc4"
        assert _heatmap_color(0.01) == "#dfe6e9"

    def test_negative_colors(self):
        assert _heatmap_color(-0.01) == "#fab1a0"
        assert _heatmap_color(-0.03) == "#ff7675"
        assert _heatmap_color(-0.06) == "#d63031"


# ═══════════════════════════════════════════════════════════
# Full report generation
# ═══════════════════════════════════════════════════════════

class TestGenerateReport:
    def test_generates_html(self, tmp_path):
        result = _make_result()

        with patch("backtest.report.RUNS_DIR", tmp_path):
            path = generate_html_report(result)

        assert path.exists()
        content = path.read_text()
        assert "<!DOCTYPE html>" in content
        assert "V7" in content.upper()
        assert "Chart.js" in content or "chart.js" in content.lower()
        assert "navChart" in content
        assert "ddChart" in content

    def test_report_with_benchmark(self, tmp_path):
        result = _make_result()
        bm_dates = result.equity_curve.index
        result.benchmark_returns = pd.Series(0.0002, index=bm_dates)
        result.benchmark_metrics = {"total_return": 0.05, "sharpe": 0.5, "max_drawdown": -0.1}
        result.metrics["excess_return"] = 0.002
        result.metrics["excess_sharpe"] = 0.35

        with patch("backtest.report.RUNS_DIR", tmp_path):
            path = generate_html_report(result)

        content = path.read_text()
        assert "benchmarkData" in content
        assert "基准" in content

    def test_report_no_equity(self, tmp_path):
        result = BacktestResult(
            config=BacktestConfig(strategy="v7", start="2024-01-01", end="2024-12-31"),
            status="failed",
            error="no data",
            run_id="fail_001",
        )

        with patch("backtest.report.RUNS_DIR", tmp_path):
            path = generate_html_report(result)

        assert path.exists()
