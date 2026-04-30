"""
Purged K-Fold Cross-Validation (López de Prado, AFML Ch. 7).

动机
----
常规 k-fold CV 在金融时间序列上会泄漏：标签 y_t 通常是 forward-looking
（用 t+1..t+h 的未来信息计算），相邻样本的标签时间窗重叠。如果训练集里
有 t=10 的样本、测试集里有 t=12 的样本、而标签窗口 h=5，那么 t=10 的
标签覆盖 11..15，与 t=12 的标签窗口 13..17 重叠；CV 把它们分到不同折里
也无法阻止信息串通。

Purged k-fold 解决这个问题：对每一折测试集，先把训练集里**与测试集标签
窗口重叠**的样本移除（purge），再在两端加**禁运期**（embargo）以防止序
列相关性从测试集倒灌回训练集。

参考
----
- López de Prado, "Advances in Financial Machine Learning", 2018
  - Ch. 7.4 "Purging the Training Set"
  - Ch. 7.5 "Embargo"

模块职责
--------
`purged_kfold_indices(dates, n_splits, label_horizon, embargo_pct)`
  → 返回 n_splits 个 (train_idx, test_idx) 对，train_idx 已 purge + embargo。

这是纯索引生成器，不绑定具体模型或策略，和 sklearn 的 KFold 同构，可以
直接喂给 cross_val_score / 自定义 CV 循环。
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class CVSplit:
    """单个 CV 折的 train/test 索引对。

    属性:
        fold: 折编号（从 0 开始）
        train_idx: 训练集整数索引（已 purge + embargo）
        test_idx: 测试集整数索引
        n_purged: 被 purge 掉的训练样本数（仅统计用）
        n_embargoed: 被 embargo 掉的训练样本数（仅统计用）
    """
    fold: int
    train_idx: np.ndarray
    test_idx: np.ndarray
    n_purged: int
    n_embargoed: int


def _validate_inputs(
    dates: pd.DatetimeIndex,
    n_splits: int,
    label_horizon: int,
    embargo_pct: float,
) -> None:
    if not isinstance(dates, pd.DatetimeIndex):
        raise TypeError(f"dates 必须是 pd.DatetimeIndex，收到 {type(dates).__name__}")
    if not dates.is_monotonic_increasing:
        raise ValueError("dates 必须按时间递增排序")
    if dates.has_duplicates:
        raise ValueError("dates 含重复日期；purged_kfold 要求日期唯一")
    if n_splits < 2:
        raise ValueError(f"n_splits 必须 ≥ 2，收到 {n_splits}")
    if label_horizon < 1:
        raise ValueError(f"label_horizon 必须 ≥ 1，收到 {label_horizon}")
    if not (0.0 <= embargo_pct < 0.5):
        raise ValueError(f"embargo_pct 必须在 [0, 0.5)，收到 {embargo_pct}")
    if len(dates) < n_splits * (label_horizon + 1):
        raise ValueError(
            f"样本数 {len(dates)} 过少：至少需要 n_splits*(label_horizon+1) = "
            f"{n_splits*(label_horizon+1)}"
        )


def purged_kfold_indices(
    dates: pd.DatetimeIndex,
    n_splits: int = 5,
    label_horizon: int = 5,
    embargo_pct: float = 0.01,
) -> Iterator[CVSplit]:
    """
    生成 purged k-fold CV 折的整数索引。

    算法:
      1. 按时间顺序把 dates 切成 n_splits 段，每段作为一折的测试集。
      2. 对每折测试集 [test_start, test_end]：
         a. 初始训练集 = 所有不在测试集内的索引
         b. **Purge**: 从训练集删除 "训练样本 t 的标签窗 [t, t+label_horizon]
            与测试集区间有交集" 的样本。因为标签 y_t 用到了 t+1..t+h 的
            未来信息，如果这段未来落在测试集内，y_t 就跟测试集串通了。
         c. **Embargo**: 从训练集删除 "在测试集结束后 embargo_days 天内"
            的样本。这防止测试集→训练集方向的序列相关泄漏（例如测试集中
            的波动率 spike 还会持续影响后续 M 天的收益分布）。

    参数:
        dates: 所有样本的时间索引（必须递增、唯一）
        n_splits: 折数（默认 5）
        label_horizon: 标签所用的未来天数（例如 5 日前向收益 label_horizon=5）
        embargo_pct: 测试集后禁运期长度占总样本数的比例（默认 1%）

    产出:
        CVSplit（train_idx, test_idx, n_purged, n_embargoed）迭代器，共 n_splits 个

    示例:
        >>> dates = pd.bdate_range("2020-01-01", periods=500)
        >>> for split in purged_kfold_indices(dates, n_splits=5, label_horizon=5):
        ...     print(split.fold, len(split.train_idx), len(split.test_idx))
    """
    _validate_inputs(dates, n_splits, label_horizon, embargo_pct)

    n = len(dates)
    embargo_days = int(round(n * embargo_pct))
    all_idx = np.arange(n)

    # 切出 n_splits 段测试集；保证起止索引连续
    fold_edges = np.linspace(0, n, n_splits + 1, dtype=int)

    for fold, (test_start, test_end) in enumerate(
        zip(fold_edges[:-1], fold_edges[1:])
    ):
        # test_end 是 exclusive
        test_idx = all_idx[test_start:test_end]
        # 初始训练集
        train_mask = np.ones(n, dtype=bool)
        train_mask[test_start:test_end] = False
        n_before = int(train_mask.sum())

        # Purge: 训练样本 t 的标签窗 [t, t+label_horizon] 与测试集相交 → 删除
        #   条件: t <= test_end - 1 且 t + label_horizon >= test_start
        #   即:   test_start - label_horizon <= t <= test_end - 1
        purge_lo = max(test_start - label_horizon, 0)
        purge_hi = test_end  # 不含；test_start..test_end-1 已在测试集
        train_mask[purge_lo:purge_hi] = False
        n_after_purge = int(train_mask.sum())

        # Embargo: 测试集之后 embargo_days 天也从训练集中删除
        embargo_lo = test_end
        embargo_hi = min(test_end + embargo_days, n)
        train_mask[embargo_lo:embargo_hi] = False
        n_after_embargo = int(train_mask.sum())

        train_idx = all_idx[train_mask]
        # purge 统计：在非测试区段被删除的数量（减去测试集自身）
        n_purged = (n_before - n_after_purge) - 0  # 测试集早已 False 不计入
        # 更准确：purge_lo..test_start 段被删的都是训练样本
        actual_purged = int(
            ((purge_lo < test_start) * (test_start - purge_lo))
        )
        n_embargoed = n_after_purge - n_after_embargo

        yield CVSplit(
            fold=fold,
            train_idx=train_idx,
            test_idx=test_idx,
            n_purged=actual_purged,
            n_embargoed=n_embargoed,
        )


def cross_val_score_purged(
    fit_predict_fn,
    X: pd.DataFrame,
    y: pd.Series,
    score_fn,
    n_splits: int = 5,
    label_horizon: int = 5,
    embargo_pct: float = 0.01,
) -> pd.DataFrame:
    """
    Purged k-fold CV 上跑分。

    参数:
        fit_predict_fn: 回调 (X_train, y_train, X_test) → y_pred
        X: 特征 (DataFrame，索引为 DatetimeIndex)
        y: 标签 (Series，索引与 X 对齐)
        score_fn: 回调 (y_true, y_pred) → float
        n_splits, label_horizon, embargo_pct: 见 purged_kfold_indices

    返回:
        DataFrame，每行对应一折：
            fold, n_train, n_test, n_purged, n_embargoed, score
    """
    if not X.index.equals(y.index):
        raise ValueError("X 和 y 的索引必须一致")
    dates = X.index
    if not isinstance(dates, pd.DatetimeIndex):
        raise TypeError("X/y 的 index 必须是 DatetimeIndex")

    rows = []
    for split in purged_kfold_indices(dates, n_splits, label_horizon, embargo_pct):
        X_tr = X.iloc[split.train_idx]
        y_tr = y.iloc[split.train_idx]
        X_te = X.iloc[split.test_idx]
        y_te = y.iloc[split.test_idx]
        y_pred = fit_predict_fn(X_tr, y_tr, X_te)
        rows.append({
            "fold": split.fold,
            "n_train": len(split.train_idx),
            "n_test": len(split.test_idx),
            "n_purged": split.n_purged,
            "n_embargoed": split.n_embargoed,
            "score": float(score_fn(y_te, y_pred)),
        })
    return pd.DataFrame(rows)


def combinatorial_purged_cv_splits(
    dates: pd.DatetimeIndex,
    n_folds: int = 10,
    n_test_folds: int = 2,
    purged_size: int = 5,
    embargo_size: int = 0,
):
    """
    Combinatorial Purged CV (López de Prado AFML Ch.12) — 通过 skfolio 提供。

    与本模块的 `purged_kfold_indices` 区别:
      - PurgedKFold: 把样本切成 k 折, 每折轮流当 1 个 test segment, 共 k 个 train/test 对
      - CombinatorialPurgedCV: 把样本切成 n_folds 折, 每次选 n_test_folds 个折作 test
        (其余作 train), 共 C(n_folds, n_test_folds) 个 train/test 对 → 多条 backtest paths
        → 提供 Sharpe / DSR 的 sampling distribution, 而不是单点估计

    参数:
        dates       : 样本时间索引 (递增唯一)
        n_folds     : 切分的折数
        n_test_folds: 每次选作 test 的折数 (1 ≤ n_test_folds < n_folds)
        purged_size : 训练集中要 purge 的样本数 (= label_horizon, AFML 用样本数而非比例)
        embargo_size: test 后禁运的样本数

    产出:
        Iterator[(train_idx, test_idx)] —— 共 C(n_folds, n_test_folds) 个对
        即 n_folds=10, n_test_folds=2 → 45 个 paths

    注:
        skfolio 的实现走过 1.9k stars + sklearn API 验证, 比手搓更稳;
        但模块内 `purged_kfold_indices` 仍保留作 reference + 简单场景。
    """
    _validate_inputs(dates, n_folds, max(purged_size, 1), embargo_size / max(len(dates), 1))
    from skfolio.model_selection import CombinatorialPurgedCV
    cpcv = CombinatorialPurgedCV(
        n_folds=n_folds,
        n_test_folds=n_test_folds,
        purged_size=purged_size,
        embargo_size=embargo_size,
    )
    n = len(dates)
    X_dummy = np.zeros((n, 1))
    yield from cpcv.split(X_dummy)


if __name__ == "__main__":
    dates = pd.bdate_range("2020-01-01", periods=500)
    total_test = 0
    for split in purged_kfold_indices(dates, n_splits=5, label_horizon=5, embargo_pct=0.01):
        print(
            f"fold={split.fold} train={len(split.train_idx)} "
            f"test={len(split.test_idx)} purged={split.n_purged} "
            f"embargoed={split.n_embargoed}"
        )
        total_test += len(split.test_idx)
    assert total_test == 500, f"测试集之和应覆盖全样本，实际 {total_test}"
    print("✓ purged_kfold_indices 自测通过")

    cpcv_splits = list(combinatorial_purged_cv_splits(
        dates, n_folds=10, n_test_folds=2, purged_size=5, embargo_size=2
    ))
    from math import comb
    expected_paths = comb(10, 2)
    assert len(cpcv_splits) == expected_paths, (
        f"CPCV 应产 C(10,2)={expected_paths} 个 path, 实际 {len(cpcv_splits)}"
    )
    print(f"✓ combinatorial_purged_cv_splits 自测通过 ({expected_paths} paths)")
