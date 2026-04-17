"""
ls_costs 回归测试 — L/S 组合摩擦成本模型的数学不变量。

覆盖四个不变量:
1. quintile_weights 每组当日等权且非零桶权重和=1
2. leg_turnover 始终 ∈ [0, 1], 首日 = 建仓权重和
3. tradable_ls_pnl 恒等式: net = (rl - rs) - txn*(tl+ts) - borrow/252
4. borrow 越高 net 越低 (单调性)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from utils.ls_costs import (
    quintile_weights,
    leg_turnover,
    leg_return,
    tradable_ls_pnl,
)


@pytest.fixture
def factor_60x40():
    """60 日 × 40 股票的模拟反转因子 (-pct_change(20))."""
    rng = np.random.default_rng(42)
    n_d, n_s = 60, 40
    dates = pd.bdate_range("2024-01-01", periods=n_d)
    syms = [f"S{i:03d}" for i in range(n_s)]
    price = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_d, n_s)), axis=0)),
        index=dates, columns=syms,
    )
    factor = -price.pct_change(20).shift(1)
    return factor, price


# ═══════════════════════════════════════════════════════════════════
# quintile_weights
# ═══════════════════════════════════════════════════════════════════

def test_quintile_weights_returns_n_groups(factor_60x40):
    factor, _ = factor_60x40
    weights = quintile_weights(factor, n_groups=5)
    assert len(weights) == 5


def test_quintile_weights_nonzero_buckets_sum_to_one(factor_60x40):
    """每组非零日, 权重和应等于 1 (等权分桶)."""
    factor, _ = factor_60x40
    weights = quintile_weights(factor, n_groups=5)
    for g, w in enumerate(weights):
        row_sums = w.sum(axis=1)
        nonzero_days = row_sums[row_sums > 0]
        assert np.allclose(nonzero_days, 1.0, atol=1e-9), (
            f"Q{g+1} 非零日权重和应为 1, 实际范围 [{nonzero_days.min():.6f}, {nonzero_days.max():.6f}]"
        )


def test_quintile_weights_handles_thin_days(factor_60x40):
    """因子样本不足的日应填 0, 不抛错."""
    factor, _ = factor_60x40
    # 前 20 日 pct_change 为 NaN
    weights = quintile_weights(factor, n_groups=5)
    # 至少首日应为空
    assert weights[0].iloc[0].sum() == 0


# ═══════════════════════════════════════════════════════════════════
# leg_turnover
# ═══════════════════════════════════════════════════════════════════

def test_leg_turnover_in_unit_interval(factor_60x40):
    """换手率定义为 one-way, 必须 ∈ [0, 1]."""
    factor, _ = factor_60x40
    weights = quintile_weights(factor, n_groups=5)
    for w in weights:
        tr = leg_turnover(w)
        assert (tr >= -1e-12).all(), f"出现负换手: {tr.min()}"
        assert (tr <= 1.0 + 1e-12).all(), f"换手超 1: {tr.max()}"


def test_leg_turnover_first_day_equals_buildup(factor_60x40):
    """首日换手 = 建仓权重绝对值和 (空仓 → 满仓 = 1)."""
    factor, _ = factor_60x40
    weights = quintile_weights(factor, n_groups=5)
    for w in weights:
        tr = leg_turnover(w)
        expected = 0.5 * w.iloc[0].abs().sum()
        assert tr.iloc[0] == pytest.approx(expected)


# ═══════════════════════════════════════════════════════════════════
# tradable_ls_pnl 恒等式
# ═══════════════════════════════════════════════════════════════════

def test_tradable_ls_pnl_arithmetic_identity():
    """net = (rl - rs) - txn*(tl+ts) - borrow/252 必须成立."""
    idx = pd.bdate_range("2024-01-01", periods=50)
    rl = pd.Series(np.full(50, 0.001), index=idx)
    rs = pd.Series(np.full(50, 0.0005), index=idx)
    tl = pd.Series(np.full(50, 0.10), index=idx)
    ts = pd.Series(np.full(50, 0.10), index=idx)

    net = tradable_ls_pnl(
        rl, rs, tl, ts,
        borrow_cost_annual=0.08,
        txn_cost_per_side=0.0015,
    )
    expected = (0.001 - 0.0005) - 0.0015 * (0.10 + 0.10) - 0.08 / 252
    assert np.allclose(net.values, expected, atol=1e-12), (
        f"恒等式失败: got {net.iloc[0]:.8f}, expected {expected:.8f}"
    )


def test_tradable_ls_pnl_zero_friction_equals_gross():
    """borrow=0, txn=0 时 net = gross (多-空)."""
    idx = pd.bdate_range("2024-01-01", periods=30)
    rl = pd.Series(np.linspace(0.001, 0.003, 30), index=idx)
    rs = pd.Series(np.linspace(0.0005, 0.002, 30), index=idx)
    tl = pd.Series(np.full(30, 0.15), index=idx)
    ts = pd.Series(np.full(30, 0.12), index=idx)

    net = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.0, txn_cost_per_side=0.0)
    gross = rl - rs
    assert np.allclose(net.values, gross.values, atol=1e-12)


def test_tradable_ls_pnl_monotonic_in_borrow():
    """borrow 提高 net 必降."""
    idx = pd.bdate_range("2024-01-01", periods=20)
    rl = pd.Series(np.full(20, 0.001), index=idx)
    rs = pd.Series(np.full(20, 0.0), index=idx)
    tl = pd.Series(np.full(20, 0.05), index=idx)
    ts = pd.Series(np.full(20, 0.05), index=idx)

    net_low = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.05, txn_cost_per_side=0.001)
    net_high = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.10, txn_cost_per_side=0.001)
    assert (net_low > net_high).all(), "borrow 上升 net 必下降"


def test_tradable_ls_pnl_monotonic_in_txn():
    """txn 提高 net 必降 (只要有换手)."""
    idx = pd.bdate_range("2024-01-01", periods=20)
    rl = pd.Series(np.full(20, 0.001), index=idx)
    rs = pd.Series(np.full(20, 0.0), index=idx)
    tl = pd.Series(np.full(20, 0.10), index=idx)
    ts = pd.Series(np.full(20, 0.08), index=idx)

    net_low = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.08, txn_cost_per_side=0.0005)
    net_high = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.08, txn_cost_per_side=0.0020)
    assert (net_low > net_high).all(), "txn 上升 net 必下降"


# ═══════════════════════════════════════════════════════════════════
# leg_return 一致性
# ═══════════════════════════════════════════════════════════════════

def test_leg_return_matches_manual_sum():
    """leg_return 结果应等于 (w * r).sum(axis=1), 对齐后."""
    idx = pd.bdate_range("2024-01-01", periods=10)
    syms = ["A", "B", "C"]
    w = pd.DataFrame(
        [[0.5, 0.5, 0], [0.3, 0.4, 0.3], [0.0, 0.0, 1.0]] + [[1/3]*3]*7,
        index=idx, columns=syms,
    )
    r = pd.DataFrame(
        np.random.default_rng(0).normal(0, 0.01, (10, 3)),
        index=idx, columns=syms,
    )
    out = leg_return(w, r)
    expected = (w * r).sum(axis=1)
    assert np.allclose(out.values, expected.values, atol=1e-12)
