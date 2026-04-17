"""
Purged k-fold CV 的回归测试。

覆盖 4 个不变量：

1. **折覆盖完整**：所有折的测试集之并集 = 全样本索引（0..N-1）。
2. **训练/测试不相交**：每折训练集 ∩ 测试集 = ∅。
3. **Purge 边界正确**：对任何训练样本 t，标签窗 [t, t+label_horizon]
   不与测试集区间相交。
4. **Embargo 生效**：测试集结束后 embargo_days 内的样本不在训练集。

这些是数学不变量，违反任一条说明实现有 off-by-one 或逻辑错误。
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from utils.purged_cv import purged_kfold_indices, cross_val_score_purged


DATES_500 = pd.bdate_range("2020-01-01", periods=500)
DATES_1000 = pd.bdate_range("2020-01-01", periods=1000)


# ═══════════════════════════════════════════════════════════════════
# 不变量 1: 折覆盖完整
# ═══════════════════════════════════════════════════════════════════

def test_folds_cover_all_samples():
    """n_splits 个测试集之并集应等于全样本 0..N-1，不重不漏。"""
    splits = list(purged_kfold_indices(DATES_500, n_splits=5, label_horizon=5))
    all_test = np.concatenate([s.test_idx for s in splits])
    all_test_sorted = np.sort(all_test)
    expected = np.arange(len(DATES_500))
    assert np.array_equal(all_test_sorted, expected), (
        f"测试集并集应覆盖全样本；缺失 {set(expected) - set(all_test_sorted)}"
    )


def test_test_folds_are_disjoint():
    """任意两折的测试集不应有交集。"""
    splits = list(purged_kfold_indices(DATES_500, n_splits=5, label_horizon=5))
    for i in range(len(splits)):
        for j in range(i + 1, len(splits)):
            overlap = set(splits[i].test_idx) & set(splits[j].test_idx)
            assert not overlap, f"fold {i} 与 fold {j} 测试集重叠: {overlap}"


# ═══════════════════════════════════════════════════════════════════
# 不变量 2: 训练/测试不相交
# ═══════════════════════════════════════════════════════════════════

def test_train_test_disjoint_per_fold():
    """每折训练集与测试集应不相交。"""
    for split in purged_kfold_indices(DATES_500, n_splits=5, label_horizon=5):
        overlap = set(split.train_idx) & set(split.test_idx)
        assert not overlap, f"fold {split.fold} 训练集与测试集重叠: {overlap}"


# ═══════════════════════════════════════════════════════════════════
# 不变量 3: Purge 正确 — 训练样本标签窗不入测试集
# ═══════════════════════════════════════════════════════════════════

def test_purge_removes_label_window_overlap():
    """对每个训练样本 t，[t, t+label_horizon] 不应与测试集相交。

    这是 purge 的核心保证：标签 y_t 用 t+1..t+h 未来数据，如果这段
    未来落在测试集内，训练样本就泄漏了。
    """
    label_horizon = 5
    for split in purged_kfold_indices(
        DATES_500, n_splits=5, label_horizon=label_horizon, embargo_pct=0.0,
    ):
        test_set = set(split.test_idx.tolist())
        for t in split.train_idx:
            label_window = set(range(int(t), int(t) + label_horizon + 1))
            overlap = label_window & test_set
            assert not overlap, (
                f"fold {split.fold}: 训练样本 t={t} 的标签窗 {label_window} "
                f"与测试集相交 {overlap}；purge 未生效"
            )


# ═══════════════════════════════════════════════════════════════════
# 不变量 4: Embargo 生效
# ═══════════════════════════════════════════════════════════════════

def test_embargo_removes_post_test_samples():
    """测试集结束后 embargo_days 内的索引不应在训练集中（除最后一折）。"""
    n = len(DATES_500)
    embargo_pct = 0.02
    embargo_days = int(round(n * embargo_pct))
    for split in purged_kfold_indices(
        DATES_500, n_splits=5, label_horizon=1, embargo_pct=embargo_pct,
    ):
        test_end = int(split.test_idx.max()) + 1  # exclusive
        banned = set(range(test_end, min(test_end + embargo_days, n)))
        if not banned:
            continue  # 最后一折，测试集到末尾
        overlap = set(split.train_idx.tolist()) & banned
        assert not overlap, (
            f"fold {split.fold}: 训练集包含 embargo 区间 {banned} 内的索引 {overlap}"
        )


# ═══════════════════════════════════════════════════════════════════
# 参数验证
# ═══════════════════════════════════════════════════════════════════

def test_requires_monotonic_dates():
    """乱序 index 应被拒绝。"""
    shuffled = pd.DatetimeIndex(DATES_500.tolist()[::-1])  # 倒序
    with pytest.raises(ValueError, match="递增"):
        list(purged_kfold_indices(shuffled, n_splits=5, label_horizon=5))


def test_rejects_duplicates():
    """重复日期应被拒绝。"""
    dup = pd.DatetimeIndex(DATES_500.tolist() + [DATES_500[-1]])
    with pytest.raises(ValueError, match="重复"):
        list(purged_kfold_indices(dup, n_splits=5, label_horizon=5))


def test_rejects_too_few_splits():
    """n_splits=1 不算 CV，应被拒绝。"""
    with pytest.raises(ValueError, match="n_splits"):
        list(purged_kfold_indices(DATES_500, n_splits=1, label_horizon=5))


def test_rejects_invalid_embargo_pct():
    """embargo_pct 不在 [0, 0.5) 应被拒绝。"""
    with pytest.raises(ValueError, match="embargo_pct"):
        list(purged_kfold_indices(DATES_500, n_splits=5, label_horizon=5, embargo_pct=0.5))
    with pytest.raises(ValueError, match="embargo_pct"):
        list(purged_kfold_indices(DATES_500, n_splits=5, label_horizon=5, embargo_pct=-0.1))


# ═══════════════════════════════════════════════════════════════════
# 集成：cross_val_score_purged 端到端
# ═══════════════════════════════════════════════════════════════════

def test_cross_val_score_runs_end_to_end():
    """简单线性模型应能在 purged CV 下跑通，得到 5 个分数。"""
    rng = np.random.default_rng(42)
    n = 500
    X = pd.DataFrame(
        rng.normal(size=(n, 3)),
        index=DATES_500[:n],
        columns=["f1", "f2", "f3"],
    )
    y = pd.Series(X["f1"] * 0.3 + rng.normal(size=n) * 0.1, index=X.index)

    def fit_predict(X_tr, y_tr, X_te):
        # 最简单的 OLS
        coef = np.linalg.lstsq(X_tr.values, y_tr.values, rcond=None)[0]
        return X_te.values @ coef

    def score(y_true, y_pred):
        # 相关系数（预测 vs 真实）
        return float(np.corrcoef(y_true.values, y_pred)[0, 1])

    result = cross_val_score_purged(
        fit_predict, X, y, score, n_splits=5, label_horizon=5, embargo_pct=0.01,
    )
    assert len(result) == 5
    assert "score" in result.columns
    # 真实信号存在，CV 分数应该都是正的（至少中位数）
    assert result["score"].median() > 0.1


if __name__ == "__main__":
    import sys
    # 直接跑也行（不需要 pytest）
    test_folds_cover_all_samples()
    print("✓ test_folds_cover_all_samples")
    test_test_folds_are_disjoint()
    print("✓ test_test_folds_are_disjoint")
    test_train_test_disjoint_per_fold()
    print("✓ test_train_test_disjoint_per_fold")
    test_purge_removes_label_window_overlap()
    print("✓ test_purge_removes_label_window_overlap")
    test_embargo_removes_post_test_samples()
    print("✓ test_embargo_removes_post_test_samples")
    test_requires_monotonic_dates()
    print("✓ test_requires_monotonic_dates")
    test_rejects_duplicates()
    print("✓ test_rejects_duplicates")
    test_rejects_too_few_splits()
    print("✓ test_rejects_too_few_splits")
    test_rejects_invalid_embargo_pct()
    print("✓ test_rejects_invalid_embargo_pct")
    test_cross_val_score_runs_end_to_end()
    print("✓ test_cross_val_score_runs_end_to_end")
    print("\n所有 purged CV 不变量通过 ✓")
