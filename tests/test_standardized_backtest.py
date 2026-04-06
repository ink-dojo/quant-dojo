"""
tests/test_standardized_backtest.py — 标准化回测框架测试
"""
import json
from dataclasses import asdict
from pathlib import Path
from unittest.mock import patch, MagicMock

import numpy as np
import pandas as pd
import pytest

from backtest.standardized import (
    BacktestConfig,
    BacktestResult,
    STRATEGY_FACTORS,
    _compute_metrics,
    _validate_config,
    run_backtest,
    run_walk_forward,
)


# ═══════════════════════════════════════════════════════════
# BacktestConfig 测试
# ═══════════════════════════════════════════════════════════

class TestBacktestConfig:
    def test_defaults(self):
        cfg = BacktestConfig()
        assert cfg.strategy == "v7"
        assert cfg.n_stocks == 30
        assert cfg.commission == 0.0003
        assert cfg.initial_capital == 1_000_000
        assert cfg.neutralize is True
        assert cfg.random_seed == 42

    def test_custom_values(self):
        cfg = BacktestConfig(
            strategy="v8",
            start="2024-01-01",
            end="2025-12-31",
            n_stocks=50,
            commission=0.001,
        )
        assert cfg.strategy == "v8"
        assert cfg.n_stocks == 50

    def test_serializable(self):
        cfg = BacktestConfig(start="2024-01-01", end="2025-12-31")
        d = asdict(cfg)
        assert isinstance(d, dict)
        assert d["strategy"] == "v7"
        # JSON-serializable
        json.dumps(d)


# ═══════════════════════════════════════════════════════════
# 配置验证测试
# ═══════════════════════════════════════════════════════════

class TestValidateConfig:
    def test_valid_config(self):
        cfg = BacktestConfig(strategy="v7", start="2024-01-01", end="2025-12-31")
        _validate_config(cfg)  # should not raise

    def test_missing_dates(self):
        with pytest.raises(ValueError, match="必须指定"):
            _validate_config(BacktestConfig(strategy="v7"))

    def test_start_after_end(self):
        with pytest.raises(ValueError, match="必须早于"):
            _validate_config(BacktestConfig(
                strategy="v7", start="2025-12-31", end="2024-01-01"
            ))

    def test_unknown_strategy(self):
        with pytest.raises(ValueError, match="未知策略"):
            _validate_config(BacktestConfig(
                strategy="v999", start="2024-01-01", end="2025-12-31"
            ))

    def test_invalid_n_stocks(self):
        with pytest.raises(ValueError, match="n_stocks"):
            _validate_config(BacktestConfig(
                strategy="v7", start="2024-01-01", end="2025-12-31", n_stocks=0
            ))

    def test_negative_commission(self):
        with pytest.raises(ValueError, match="commission"):
            _validate_config(BacktestConfig(
                strategy="v7", start="2024-01-01", end="2025-12-31", commission=-0.01
            ))


# ═══════════════════════════════════════════════════════════
# 绩效指标测试
# ═══════════════════════════════════════════════════════════

class TestComputeMetrics:
    def test_basic_metrics(self):
        np.random.seed(42)
        returns = pd.Series(np.random.randn(252) * 0.01)
        m = _compute_metrics(returns)

        assert "total_return" in m
        assert "annualized_return" in m
        assert "sharpe" in m
        assert "max_drawdown" in m
        assert "win_rate" in m
        assert "n_trading_days" in m
        assert m["n_trading_days"] == 252

    def test_empty_returns(self):
        m = _compute_metrics(pd.Series(dtype=float))
        assert m == {}

    def test_positive_returns(self):
        returns = pd.Series([0.01] * 252)
        m = _compute_metrics(returns)
        assert m["total_return"] > 0
        assert m["annualized_return"] > 0
        assert m["win_rate"] == 1.0

    def test_max_drawdown_negative(self):
        returns = pd.Series([0.01, 0.01, -0.05, 0.01, 0.01])
        m = _compute_metrics(returns)
        assert m["max_drawdown"] < 0


# ═══════════════════════════════════════════════════════════
# 策略因子映射测试
# ═══════════════════════════════════════════════════════════

class TestStrategyFactors:
    def test_v7_factors(self):
        assert "team_coin" in STRATEGY_FACTORS["v7"]
        assert "bp" in STRATEGY_FACTORS["v7"]
        assert len(STRATEGY_FACTORS["v7"]) == 5

    def test_v8_has_shadow_lower(self):
        assert "shadow_lower" in STRATEGY_FACTORS["v8"]
        assert len(STRATEGY_FACTORS["v8"]) == 6

    def test_ad_hoc_factors(self):
        assert "momentum_20" in STRATEGY_FACTORS["ad_hoc"]


# ═══════════════════════════════════════════════════════════
# BacktestResult 测试
# ═══════════════════════════════════════════════════════════

class TestBacktestResult:
    def test_default_status(self):
        r = BacktestResult(config=BacktestConfig())
        assert r.status == "pending"
        assert r.error is None
        assert r.equity_curve is None

    def test_failed_result(self):
        r = BacktestResult(
            config=BacktestConfig(),
            status="failed",
            error="数据不可用",
        )
        assert r.status == "failed"
        assert r.error == "数据不可用"


# ═══════════════════════════════════════════════════════════
# 集成测试（使用 mock 数据）
# ═══════════════════════════════════════════════════════════

class TestRunBacktestMocked:
    """用 mock 数据测试 run_backtest 完整流程"""

    def _make_mock_data(self):
        """生成模拟数据"""
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=600, freq="B")
        symbols = [f"00{i:04d}.SZ" for i in range(1, 101)]
        price = pd.DataFrame(
            np.cumprod(1 + np.random.randn(600, 100) * 0.01, axis=0) * 10,
            index=dates,
            columns=symbols,
        )
        return dates, symbols, price

    @patch("backtest.standardized._persist_result", return_value="test_run_001")
    @patch("backtest.standardized._compute_factors")
    @patch("backtest.standardized.load_price_wide")
    @patch("backtest.standardized.get_all_symbols")
    @patch("backtest.standardized.load_factor_wide", return_value=pd.DataFrame())
    def test_successful_run(
        self, mock_st, mock_symbols, mock_price, mock_factors, mock_persist
    ):
        dates, symbols, price = self._make_mock_data()

        mock_symbols.return_value = symbols
        mock_price.return_value = price

        # 模拟因子
        factor1 = pd.DataFrame(
            np.random.randn(600, 100), index=dates, columns=symbols
        )
        factor2 = pd.DataFrame(
            np.random.randn(600, 100), index=dates, columns=symbols
        )
        mock_factors.return_value = {
            "factor_a": (factor1, 1),
            "factor_b": (factor2, 1),
        }

        config = BacktestConfig(
            strategy="v7",
            start="2024-01-01",
            end="2025-06-30",
            n_stocks=10,
        )
        result = run_backtest(config)

        assert result.status == "success"
        assert result.run_id == "test_run_001"
        assert result.metrics["n_trading_days"] > 0
        assert "sharpe" in result.metrics
        assert result.equity_curve is not None
        assert not result.equity_curve.empty

    @patch("backtest.standardized._persist_result", return_value="test_fail_001")
    @patch("backtest.standardized.get_all_symbols", return_value=[])
    @patch("backtest.standardized.load_price_wide", return_value=pd.DataFrame())
    def test_empty_data_fails(self, mock_price, mock_symbols, mock_persist):
        config = BacktestConfig(
            strategy="v7",
            start="2024-01-01",
            end="2025-06-30",
        )
        result = run_backtest(config)
        assert result.status == "failed"
        assert result.error is not None

    def test_invalid_config_fails(self):
        config = BacktestConfig(strategy="v7", start="", end="")
        result = run_backtest(config)
        assert result.status == "failed"
        assert "必须指定" in result.error


# ═══════════════════════════════════════════════════════════
# Walk-Forward 测试
# ═══════════════════════════════════════════════════════════

class TestRunWalkForward:
    """Walk-Forward 集成测试"""

    def _make_mock_data(self):
        np.random.seed(42)
        # 需要足够长的数据来支撑 train_years=1 + test_months=3
        dates = pd.date_range("2022-01-01", periods=800, freq="B")
        symbols = [f"00{i:04d}.SZ" for i in range(1, 51)]
        price = pd.DataFrame(
            np.cumprod(1 + np.random.randn(800, 50) * 0.01, axis=0) * 10,
            index=dates,
            columns=symbols,
        )
        return dates, symbols, price

    @patch("backtest.standardized._compute_factors")
    @patch("backtest.standardized.load_price_wide")
    @patch("backtest.standardized.get_all_symbols")
    @patch("backtest.standardized.load_factor_wide", return_value=pd.DataFrame())
    def test_walk_forward_runs(
        self, mock_st, mock_symbols, mock_price, mock_factors,
    ):
        dates, symbols, price = self._make_mock_data()
        mock_symbols.return_value = symbols
        mock_price.return_value = price

        factor1 = pd.DataFrame(np.random.randn(800, 50), index=dates, columns=symbols)
        factor2 = pd.DataFrame(np.random.randn(800, 50), index=dates, columns=symbols)
        mock_factors.return_value = {
            "factor_a": (factor1, 1),
            "factor_b": (factor2, 1),
        }

        config = BacktestConfig(
            strategy="v7",
            start="2022-01-01",
            end="2025-03-31",
            n_stocks=10,
        )
        wf = run_walk_forward(config, train_years=1, test_months=3)

        assert "windows" in wf
        assert "summary" in wf
        assert len(wf["windows"]) > 0
        assert "sharpe_mean" in wf["summary"]

    def test_walk_forward_invalid_config(self):
        config = BacktestConfig(strategy="v7", start="", end="")
        with pytest.raises(ValueError, match="必须指定"):
            run_walk_forward(config)


# ═══════════════════════════════════════════════════════════
# Benchmark 测试
# ═══════════════════════════════════════════════════════════

class TestBenchmark:
    def test_benchmark_fields_in_result(self):
        r = BacktestResult(config=BacktestConfig())
        assert r.benchmark_returns is None
        assert r.benchmark_metrics == {}

    @patch("backtest.standardized._load_benchmark")
    @patch("backtest.standardized._persist_result", return_value="test_bm_001")
    @patch("backtest.standardized._compute_factors")
    @patch("backtest.standardized.load_price_wide")
    @patch("backtest.standardized.get_all_symbols")
    @patch("backtest.standardized.load_factor_wide", return_value=pd.DataFrame())
    def test_benchmark_included_when_available(
        self, mock_st, mock_symbols, mock_price, mock_factors, mock_persist, mock_bm
    ):
        np.random.seed(42)
        dates = pd.date_range("2023-01-01", periods=600, freq="B")
        symbols = [f"00{i:04d}.SZ" for i in range(1, 51)]
        price = pd.DataFrame(
            np.cumprod(1 + np.random.randn(600, 50) * 0.01, axis=0) * 10,
            index=dates, columns=symbols,
        )
        mock_symbols.return_value = symbols
        mock_price.return_value = price

        factor1 = pd.DataFrame(np.random.randn(600, 50), index=dates, columns=symbols)
        mock_factors.return_value = {"f1": (factor1, 1)}

        # mock benchmark: slightly positive returns
        bm_ret = pd.Series(0.0003, index=dates)
        mock_bm.return_value = bm_ret

        config = BacktestConfig(strategy="v7", start="2024-01-01", end="2025-06-30", n_stocks=10)
        result = run_backtest(config)

        assert result.status == "success"
        assert result.benchmark_returns is not None
        assert "excess_return" in result.metrics
        assert "excess_sharpe" in result.metrics
