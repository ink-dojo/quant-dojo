"""
skfolio 接入测试 (#54)

覆盖:
    1. CombinatorialPurgedCV: path 数 = C(n_folds, n_test_folds), train/test 不重叠
    2. HRP / MinCVaR / MaxDiv: 权重和=1, 非负, 不退化全押单只
    3. 与现有 PurgedKFold 共存 (不破坏 purged_kfold_indices 行为)

跑法:
    pytest tests/test_skfolio_integration.py -v
"""
from __future__ import annotations

from math import comb

import numpy as np
import pandas as pd
import pytest

skfolio = pytest.importorskip("skfolio")  # 没装就 skip 整个文件

from utils.position_sizing import skfolio_optimizer  # noqa: E402
from utils.purged_cv import (  # noqa: E402
    combinatorial_purged_cv_splits,
    purged_kfold_indices,
)


@pytest.fixture
def synthetic_dates() -> pd.DatetimeIndex:
    return pd.bdate_range("2020-01-01", periods=500)


@pytest.fixture
def synthetic_returns() -> pd.DataFrame:
    rng = np.random.default_rng(2026)
    syms = [f"{i:06d}" for i in range(8)]
    return pd.DataFrame(
        rng.normal(0.0005, 0.012, size=(252, len(syms))),
        index=pd.bdate_range("2024-01-01", periods=252),
        columns=syms,
    )


# ─── CombinatorialPurgedCV ─────────────────────────────────────────

@pytest.mark.parametrize("n_folds,n_test", [(6, 2), (10, 2), (10, 3)])
def test_cpcv_path_count(synthetic_dates, n_folds, n_test):
    splits = list(combinatorial_purged_cv_splits(
        synthetic_dates, n_folds=n_folds, n_test_folds=n_test,
        purged_size=5, embargo_size=2,
    ))
    assert len(splits) == comb(n_folds, n_test), (
        f"CPCV(n_folds={n_folds}, n_test={n_test}) 应产 C={comb(n_folds, n_test)} 个 path"
    )


def test_cpcv_train_test_disjoint(synthetic_dates):
    """skfolio CPCV: test_idx 是 list[np.ndarray] (n_test_folds 个不连续段),
    train_idx 是单个 np.ndarray. 把 test 各段合并后检查与 train 不重叠。"""
    for train_idx, test_idx in combinatorial_purged_cv_splits(
        synthetic_dates, n_folds=8, n_test_folds=2, purged_size=5, embargo_size=2
    ):
        test_flat = np.concatenate(test_idx) if isinstance(test_idx, list) else test_idx
        overlap = set(train_idx.tolist()) & set(test_flat.tolist())
        assert not overlap, f"train/test 索引重叠: {len(overlap)} 个样本"


def test_cpcv_purge_actually_removes(synthetic_dates):
    """purged_size>0 时 train 应该比无 purge 的 train 少 (至少大多数 path)"""
    no_purge = list(combinatorial_purged_cv_splits(
        synthetic_dates, n_folds=8, n_test_folds=2, purged_size=0, embargo_size=0
    ))
    with_purge = list(combinatorial_purged_cv_splits(
        synthetic_dates, n_folds=8, n_test_folds=2, purged_size=10, embargo_size=0
    ))
    assert len(no_purge) == len(with_purge)
    smaller = sum(
        1 for (tr_a, _), (tr_b, _) in zip(no_purge, with_purge)
        if len(tr_b) < len(tr_a)
    )
    assert smaller > len(no_purge) // 2, (
        f"purge 没生效: 只有 {smaller}/{len(no_purge)} path 的 train 变小"
    )


# ─── PurgedKFold 不被破坏 ─────────────────────────────────────────

def test_purged_kfold_still_works(synthetic_dates):
    splits = list(purged_kfold_indices(
        synthetic_dates, n_splits=5, label_horizon=5, embargo_pct=0.01
    ))
    assert len(splits) == 5
    total_test = sum(len(s.test_idx) for s in splits)
    assert total_test == len(synthetic_dates), "PurgedKFold test 集应覆盖全样本"


# ─── skfolio optimizers ─────────────────────────────────────────

@pytest.mark.parametrize("method", ["hrp", "min_cvar", "max_div"])
def test_optimizer_weights_sum_to_one(synthetic_returns, method):
    syms = list(synthetic_returns.columns)
    weights = skfolio_optimizer(syms, synthetic_returns, method=method)
    assert len(weights) == len(syms)
    s = sum(weights.values())
    assert abs(s - 1.0) < 1e-3, f"{method} 权重和={s}, 不为 1"


@pytest.mark.parametrize("method", ["hrp", "min_cvar", "max_div"])
def test_optimizer_weights_non_negative(synthetic_returns, method):
    syms = list(synthetic_returns.columns)
    weights = skfolio_optimizer(syms, synthetic_returns, method=method)
    assert all(w >= -1e-6 for w in weights.values()), f"{method} 出现负权重"


@pytest.mark.parametrize("method", ["hrp", "min_cvar", "max_div"])
def test_optimizer_not_degenerate(synthetic_returns, method):
    """权重不应该全押单只 (max < 0.95)"""
    syms = list(synthetic_returns.columns)
    weights = skfolio_optimizer(syms, synthetic_returns, method=method)
    max_w = max(weights.values())
    assert max_w < 0.95, f"{method} 退化 全押 {max_w:.3f} 单只"


def test_optimizer_max_weight_constraint(synthetic_returns):
    """min_cvar 显式 max_weight=0.3 应该被遵守 (HRP 的 cap 实现不同, 不测它)"""
    syms = list(synthetic_returns.columns)
    weights = skfolio_optimizer(syms, synthetic_returns, method="min_cvar", max_weight=0.3)
    max_w = max(weights.values())
    assert max_w <= 0.3 + 1e-3, f"min_cvar max_weight=0.3 没遵守, max={max_w:.3f}"


def test_optimizer_skips_missing_symbols(synthetic_returns):
    """selected 含 returns_wide 没有的 symbol 应被跳过, 不 crash"""
    syms = list(synthetic_returns.columns) + ["999999"]
    weights = skfolio_optimizer(syms, synthetic_returns, method="hrp")
    assert "999999" not in weights
    assert len(weights) == len(synthetic_returns.columns)


def test_optimizer_short_history_falls_back(synthetic_returns):
    """< 60 天历史应降级为 equal_weight, 不报错"""
    short = synthetic_returns.iloc[:30]
    syms = list(short.columns)
    weights = skfolio_optimizer(syms, short, method="hrp")
    assert all(abs(w - 1.0 / len(syms)) < 1e-9 for w in weights.values())
