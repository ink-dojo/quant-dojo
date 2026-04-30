"""
alphalens_adapter 一致性测试

确保适配器:
    1. 转换格式无丢数据
    2. alphalens IC 均值 == compute_ic_series IC 均值（差 < 1e-6）
    3. 多个前瞻周期都过

跑法:
    pytest tests/test_alphalens_adapter.py -v
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from utils.alphalens_adapter import (
    align_factor_pricing,
    consistency_check_ic,
    to_alphalens_factor,
    to_alphalens_pricing,
)


@pytest.fixture(scope="module")
def synthetic_panel() -> tuple[pd.DataFrame, pd.DataFrame]:
    """生成 200 日 × 80 股票的合成价格 + 20 日动量因子"""
    rng = np.random.default_rng(2026)
    dates = pd.bdate_range("2023-01-02", periods=200)
    syms = [f"{i:06d}" for i in range(80)]
    log_ret = rng.normal(0, 0.012, size=(len(dates), len(syms)))
    price = pd.DataFrame(
        100.0 * np.exp(np.cumsum(log_ret, axis=0)),
        index=dates, columns=syms,
    )
    factor = price.pct_change(20).dropna()
    return factor, price


def test_factor_stacking_preserves_count(synthetic_panel):
    factor, _ = synthetic_panel
    s = to_alphalens_factor(factor)
    expected = factor.stack(future_stack=True).dropna().shape[0]
    assert s.shape[0] == expected, "stack 后元素数不应该变"
    assert list(s.index.names) == ["date", "asset"]


def test_pricing_index_is_datetime(synthetic_panel):
    _, price = synthetic_panel
    p = to_alphalens_pricing(price)
    assert isinstance(p.index, pd.DatetimeIndex)
    assert p.index.is_monotonic_increasing


def test_align_returns_intersection(synthetic_panel):
    factor, price = synthetic_panel
    f, p = align_factor_pricing(factor, price)
    assert (f.index == p.index).all()
    assert list(f.columns) == list(p.columns)


@pytest.mark.parametrize("fwd", [1, 5, 10])
def test_ic_consistency_across_periods(synthetic_panel, fwd):
    """适配器零漂移红线: 多个前瞻周期 alphalens IC == 本地 IC"""
    factor, price = synthetic_panel
    res = consistency_check_ic(factor, price, fwd_period=fwd, atol=1e-6)
    assert res["passed"], (
        f"fwd={fwd}: local={res['ic_mean_local']:.6e} "
        f"alphalens={res['ic_mean_alphalens']:.6e} "
        f"diff={res['abs_diff']:.2e}"
    )


# 注: alphalens.factor_information_coefficient 内部硬编码 spearman（Rank IC），
# 不支持 pearson IC。本地 compute_ic_series(method='pearson') 没有可比较的 alphalens 对照，
# 所以一致性测试只覆盖 spearman 路径。Rank IC 也是因子研究的行业默认。
