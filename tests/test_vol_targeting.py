"""Tests for pipeline/vol_targeting.py."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from pipeline.vol_targeting import (
    TRADING_DAYS_PER_YEAR,
    VolTargetReport,
    apply_vol_target_to_positions,
    compute_vol_scale,
    compute_vol_scale_series,
)


def _make_synthetic_nav(
    annual_vol: float,
    n_days: int = 200,
    drift: float = 0.0003,
    seed: int = 42,
    start: str = "2024-01-02",
) -> pd.Series:
    """生成给定年化波动率的合成 NAV."""
    rng = np.random.default_rng(seed)
    daily_vol = annual_vol / math.sqrt(TRADING_DAYS_PER_YEAR)
    returns = rng.normal(drift, daily_vol, n_days)
    nav = np.cumprod(1 + returns) * 1_000_000
    return pd.Series(nav, index=pd.bdate_range(start, periods=n_days))


# ══════════════════════════════════════════════════════════════
# compute_vol_scale — 主路径
# ══════════════════════════════════════════════════════════════

def test_low_vol_clipped_to_max():
    """8% 实现波动率, target 12% → raw scale=1.5, 等于 max_scale."""
    nav = _make_synthetic_nav(annual_vol=0.08)
    report = compute_vol_scale(nav, target_vol=0.12)
    assert report.scale == pytest.approx(1.50, abs=0.01)
    assert report.realized_vol < 0.10


def test_target_vol_gives_scale_one():
    """实现波动率 ≈ 目标, scale 应 ≈ 1.0."""
    nav = _make_synthetic_nav(annual_vol=0.12)
    report = compute_vol_scale(nav, target_vol=0.12)
    assert 0.85 <= report.scale <= 1.20
    assert 0.10 <= report.realized_vol <= 0.14


def test_high_vol_reduces_scale():
    """24% 实现 vs 12% target → scale ≈ 0.5."""
    nav = _make_synthetic_nav(annual_vol=0.24)
    report = compute_vol_scale(nav, target_vol=0.12)
    assert 0.40 <= report.scale <= 0.65
    assert 0.20 <= report.realized_vol <= 0.28


def test_extreme_vol_clipped_to_min():
    """50% 实现 vs 12% target → raw scale=0.24, clip 到 0.30."""
    nav = _make_synthetic_nav(annual_vol=0.50)
    report = compute_vol_scale(nav, target_vol=0.12)
    assert report.scale == 0.30
    assert report.fallback_reason is None  # 不是 fallback, 是 clip


def test_custom_target_and_clips():
    """自定义阈值: target 8%, min 0.5, max 2.0."""
    nav = _make_synthetic_nav(annual_vol=0.04)  # 远低于 target
    report = compute_vol_scale(
        nav, target_vol=0.08, min_scale=0.5, max_scale=2.0
    )
    assert report.scale == pytest.approx(2.0, abs=0.01)


# ══════════════════════════════════════════════════════════════
# compute_vol_scale — 边界 / fallback
# ══════════════════════════════════════════════════════════════

def test_empty_nav_fallback():
    """空 series → scale=1.0 + fallback_reason."""
    nav = pd.Series([], dtype=float)
    report = compute_vol_scale(nav)
    assert report.scale == 1.0
    assert report.fallback_reason is not None
    assert report.realized_vol is None


def test_single_value_nav_fallback():
    """只有 1 个 NAV → 不能算 return, fallback."""
    nav = pd.Series([1_000_000.0], index=pd.bdate_range("2024-01-02", periods=1))
    report = compute_vol_scale(nav)
    assert report.scale == 1.0
    assert "长度不足" in report.fallback_reason


def test_too_few_observations_fallback():
    """观测数不足 min_observations → fallback."""
    nav = _make_synthetic_nav(annual_vol=0.12, n_days=15)
    report = compute_vol_scale(nav, min_observations=20)
    assert report.scale == 1.0
    assert "观测数" in report.fallback_reason


def test_constant_nav_fallback():
    """NAV 全平 (vol=0) → 防除零, fallback."""
    nav = pd.Series(
        [1_000_000.0] * 100,
        index=pd.bdate_range("2024-01-02", periods=100),
    )
    report = compute_vol_scale(nav)
    assert report.scale == 1.0
    assert "接近 0" in report.fallback_reason


def test_nav_with_nans_dropped():
    """NAV 有 NaN, dropna 后剩余足够也能算."""
    nav = _make_synthetic_nav(annual_vol=0.12, n_days=100)
    nav.iloc[5:10] = np.nan
    report = compute_vol_scale(nav)
    assert report.scale > 0.5  # 能算出有效值
    assert report.fallback_reason is None


def test_invalid_input_type_raises():
    """非 pd.Series 输入应 raise."""
    with pytest.raises(TypeError):
        compute_vol_scale([1.0, 2.0, 3.0])  # type: ignore[arg-type]


# ══════════════════════════════════════════════════════════════
# apply_vol_target_to_positions
# ══════════════════════════════════════════════════════════════

def test_apply_scale_multiplies_each_value():
    positions = {"600519.SH": 100_000.0, "000001.SZ": 50_000.0}
    result = apply_vol_target_to_positions(positions, scale=0.7)
    assert result["600519.SH"] == 70_000.0
    assert result["000001.SZ"] == 35_000.0


def test_apply_scale_zero_zeroes_out():
    positions = {"600519.SH": 100_000.0}
    result = apply_vol_target_to_positions(positions, scale=0.0)
    assert result["600519.SH"] == 0.0


def test_apply_scale_one_is_identity():
    positions = {"600519.SH": 100_000.0, "000001.SZ": 50_000.0}
    result = apply_vol_target_to_positions(positions, scale=1.0)
    assert result == positions


def test_apply_scale_does_not_mutate_input():
    """不应修改原 dict."""
    positions = {"600519.SH": 100_000.0}
    original = positions.copy()
    _ = apply_vol_target_to_positions(positions, scale=0.5)
    assert positions == original


def test_apply_negative_scale_raises():
    with pytest.raises(ValueError):
        apply_vol_target_to_positions({"x": 100.0}, scale=-0.5)


def test_apply_empty_positions():
    result = apply_vol_target_to_positions({}, scale=0.7)
    assert result == {}


# ══════════════════════════════════════════════════════════════
# compute_vol_scale_series — 回测用
# ══════════════════════════════════════════════════════════════

def test_scale_series_length_matches_nav():
    nav = _make_synthetic_nav(annual_vol=0.12, n_days=100)
    series = compute_vol_scale_series(nav, lookback_days=30)
    assert len(series) == 100


def test_scale_series_early_days_fallback():
    """前 min_observations 日, 数据不足应是 1.0."""
    nav = _make_synthetic_nav(annual_vol=0.24, n_days=100)
    series = compute_vol_scale_series(nav, lookback_days=60, min_observations=20)
    # 前 20 天数据不足 (实际 < 20 个 returns 时 fallback)
    assert series.iloc[0] == 1.0
    assert series.iloc[5] == 1.0
    # 后期数据足够, 高波动应缩小 scale
    assert series.iloc[-1] < 0.8


def test_scale_series_responds_to_vol_regime_change():
    """合成: 前半段低波动, 后半段高波动. scale 应在中间下降."""
    n_per_segment = 150
    rng = np.random.default_rng(42)
    low_vol_returns = rng.normal(
        0.0003, 0.08 / math.sqrt(TRADING_DAYS_PER_YEAR), n_per_segment
    )
    high_vol_returns = rng.normal(
        0.0003, 0.30 / math.sqrt(TRADING_DAYS_PER_YEAR), n_per_segment
    )
    returns = np.concatenate([low_vol_returns, high_vol_returns])
    nav = pd.Series(
        np.cumprod(1 + returns) * 1_000_000,
        index=pd.bdate_range("2024-01-02", periods=len(returns)),
    )
    series = compute_vol_scale_series(nav, lookback_days=60)

    # 前段 (低波动) scale 应高
    early_mean = series.iloc[60:140].mean()
    # 后段 (高波动, 完全填充 60d 窗口需要 +60 天)
    late_mean = series.iloc[-30:].mean()

    assert early_mean > 1.0, f"低波动期 scale 应 > 1, 得 {early_mean:.3f}"
    assert late_mean < 0.6, f"高波动期 scale 应 < 0.6, 得 {late_mean:.3f}"
    assert early_mean > late_mean + 0.5, "regime change 应清晰反映在 scale 上"


# ══════════════════════════════════════════════════════════════
# VolTargetReport 数据完整性
# ══════════════════════════════════════════════════════════════

def test_report_has_asof_date():
    nav = _make_synthetic_nav(annual_vol=0.12)
    report = compute_vol_scale(nav)
    assert report.asof_date == nav.index[-1]


def test_report_records_lookback_used():
    nav = _make_synthetic_nav(annual_vol=0.12, n_days=100)
    report = compute_vol_scale(nav, lookback_days=60)
    assert report.lookback_days_used == 60


def test_report_short_lookback_when_data_short():
    nav = _make_synthetic_nav(annual_vol=0.12, n_days=40)
    report = compute_vol_scale(nav, lookback_days=60, min_observations=20)
    # 总共 40 天 → 39 个 return, 但 lookback 60 取不满, 取全部
    assert report.lookback_days_used == 39
    assert report.fallback_reason is None  # 39 ≥ 20, 不 fallback


def test_report_immutable():
    """VolTargetReport 应是 frozen dataclass."""
    nav = _make_synthetic_nav(annual_vol=0.12)
    report = compute_vol_scale(nav)
    with pytest.raises((AttributeError, Exception)):  # frozen dataclass FrozenInstanceError
        report.scale = 999.0  # type: ignore[misc]
