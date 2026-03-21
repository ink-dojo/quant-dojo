"""
多因子合成框架
提供标准化、排名归一化、等权合成、IC加权合成、评分合成等函数

所有函数均以宽表（date × symbol 的 DataFrame）为输入/输出。
"""
import numpy as np
import pandas as pd
from scipy import stats


# ─────────────────────────────────────────────
# 标准化工具
# ─────────────────────────────────────────────

def zscore_normalize(factor_wide: pd.DataFrame) -> pd.DataFrame:
    """
    截面 Z-score 标准化（按行/日期）

    对每个交易日，将因子值减去截面均值再除以截面标准差，
    使每日截面均值为0、标准差为1。

    参数:
        factor_wide : 因子宽表 (date × symbol)

    返回:
        zscore_wide : 标准化后的因子宽表，形状与输入相同
    """
    mean = factor_wide.mean(axis=1)
    std = factor_wide.std(axis=1)
    # 避免标准差为0时除以零
    std = std.replace(0, np.nan)
    return factor_wide.sub(mean, axis=0).div(std, axis=0)


def rank_normalize(factor_wide: pd.DataFrame) -> pd.DataFrame:
    """
    截面排名归一化（按行/日期），结果缩放到 [0, 1]

    对每个交易日，将因子值转换为截面百分比排名（pct=True），
    最小值映射为接近0，最大值映射为接近1。

    参数:
        factor_wide : 因子宽表 (date × symbol)

    返回:
        rank_wide : 排名归一化后的因子宽表，值域约 [0, 1]
    """
    return factor_wide.rank(axis=1, pct=True)


# ─────────────────────────────────────────────
# 等权合成
# ─────────────────────────────────────────────

def equal_weight_composite(
    factors: dict,
    normalize: str = "zscore",
) -> pd.DataFrame:
    """
    等权多因子合成

    对每个因子先做截面标准化，然后取各因子的简单平均。
    自动对齐所有因子的日期和股票池（取交集）。

    参数:
        factors   : {"因子名": factor_wide, ...}，宽表字典
        normalize : 标准化方式，"zscore"（默认）或 "rank"
                    "zscore" → zscore_normalize
                    "rank"   → rank_normalize

    返回:
        composite : 合成因子宽表 (date × symbol)
    """
    if normalize == "zscore":
        norm_fn = zscore_normalize
    elif normalize == "rank":
        norm_fn = rank_normalize
    else:
        raise ValueError(f"normalize 须为 'zscore' 或 'rank'，收到: {normalize!r}")

    # 对齐公共日期和股票
    all_dates = None
    all_cols = None
    for fac in factors.values():
        if all_dates is None:
            all_dates = fac.index
            all_cols = fac.columns
        else:
            all_dates = all_dates.intersection(fac.index)
            all_cols = all_cols.intersection(fac.columns)

    if all_dates is None or len(all_dates) == 0:
        return pd.DataFrame()

    normed_list = []
    for fac in factors.values():
        normed = norm_fn(fac.loc[all_dates, all_cols])
        normed_list.append(normed)

    # 叠加后取均值（nan 不参与计数）
    stack = np.stack([df.values for df in normed_list], axis=0)
    composite_vals = np.nanmean(stack, axis=0)

    return pd.DataFrame(composite_vals, index=all_dates, columns=all_cols)


# ─────────────────────────────────────────────
# IC 加权合成
# ─────────────────────────────────────────────

def ic_weighted_composite(
    factors: dict,
    ic_lookback: int = 60,
    ret_wide: pd.DataFrame = None,
) -> pd.DataFrame:
    """
    IC 加权多因子合成

    每个月重新计算各因子在过去 ic_lookback 个交易日内的滚动均值 IC（Spearman），
    以 |IC均值| 为权重对各因子做加权平均合成。若 ret_wide 为 None，
    退化为等权合成（等同于 equal_weight_composite 使用 zscore）。

    参数:
        factors      : {"因子名": factor_wide, ...}，宽表字典
        ic_lookback  : 计算权重所用的滚动回看窗口（交易日），默认60
        ret_wide     : 下期收益率宽表 (date × symbol)；
                       若为 None，则退化为等权合成

    返回:
        composite : IC加权合成因子宽表 (date × symbol)
    """
    if ret_wide is None:
        return equal_weight_composite(factors, normalize="zscore")

    names = list(factors.keys())

    # 对齐公共日期和股票
    all_dates = None
    all_cols = None
    for fac in factors.values():
        if all_dates is None:
            all_dates = fac.index
            all_cols = fac.columns
        else:
            all_dates = all_dates.intersection(fac.index)
            all_cols = all_cols.intersection(fac.columns)

    common_stocks = all_cols.intersection(ret_wide.columns)
    common_dates = all_dates.intersection(ret_wide.index)

    if len(common_dates) == 0:
        return pd.DataFrame()

    # 先对每个因子做 z-score 标准化（在公共截面上）
    normed = {}
    for name, fac in factors.items():
        normed[name] = zscore_normalize(fac.loc[common_dates, common_stocks])

    # 计算各因子截面 IC 序列
    ic_series = {}
    for name in names:
        fac_n = normed[name]
        ret_n = ret_wide.loc[common_dates, common_stocks]
        ic_list = []
        for date in common_dates:
            f_vals = fac_n.loc[date].dropna()
            r_vals = ret_n.loc[date].dropna()
            idx = f_vals.index.intersection(r_vals.index)
            if len(idx) < 10:
                ic_list.append(np.nan)
                continue
            corr, _ = stats.spearmanr(f_vals[idx], r_vals[idx])
            ic_list.append(corr)
        ic_series[name] = pd.Series(ic_list, index=common_dates)

    ic_df = pd.DataFrame(ic_series)
    # 滚动均值 IC（按月重算权重：取每月最后一个交易日的滚动值）
    min_periods = min(max(3, ic_lookback // 4), ic_lookback)
    rolling_ic = ic_df.rolling(ic_lookback, min_periods=min_periods).mean()

    # 逐日计算权重并加权合成
    result_vals = np.full((len(common_dates), len(common_stocks)), np.nan)

    for i, date in enumerate(common_dates):
        if date not in rolling_ic.index:
            continue
        w_row = rolling_ic.loc[date].abs()
        total_w = w_row.sum()
        if np.isnan(total_w) or total_w == 0:
            # 退化为等权
            w_arr = np.array([1.0 / len(names)] * len(names))
        else:
            w_arr = (w_row / total_w).values

        weighted = np.zeros(len(common_stocks))
        weight_sum = np.zeros(len(common_stocks))

        for j, name in enumerate(names):
            vals = normed[name].loc[date].values
            mask = ~np.isnan(vals)
            weighted[mask] += w_arr[j] * vals[mask]
            weight_sum[mask] += w_arr[j]

        result_vals[i] = np.where(weight_sum > 0, weighted / weight_sum, np.nan)

    return pd.DataFrame(result_vals, index=common_dates, columns=common_stocks)


# ─────────────────────────────────────────────
# 评分合成
# ─────────────────────────────────────────────

def score_composite(
    factors: dict,
    direction: dict = None,
) -> pd.DataFrame:
    """
    评分法多因子合成

    对每个因子做截面排名归一化（0~1），若指定方向为 -1 则将该因子取反
    （即 1 - rank，使小值变高分）。然后对所有因子做等权平均得到综合评分。

    参数:
        factors   : {"因子名": factor_wide, ...}，宽表字典
        direction : {"因子名": 1 或 -1, ...}，可选。
                    1  → 数值越大越好（默认）
                    -1 → 数值越小越好（如波动率、估值）

    返回:
        composite : 综合评分宽表 (date × symbol)，值域约 [0, 1]
    """
    if direction is None:
        direction = {}

    # 对齐公共日期和股票
    all_dates = None
    all_cols = None
    for fac in factors.values():
        if all_dates is None:
            all_dates = fac.index
            all_cols = fac.columns
        else:
            all_dates = all_dates.intersection(fac.index)
            all_cols = all_cols.intersection(fac.columns)

    if all_dates is None or len(all_dates) == 0:
        return pd.DataFrame()

    ranked_list = []
    for name, fac in factors.items():
        ranked = rank_normalize(fac.loc[all_dates, all_cols])
        d = direction.get(name, 1)
        if d == -1:
            ranked = 1.0 - ranked
        ranked_list.append(ranked)

    stack = np.stack([df.values for df in ranked_list], axis=0)
    composite_vals = np.nanmean(stack, axis=0)

    return pd.DataFrame(composite_vals, index=all_dates, columns=all_cols)


# ─────────────────────────────────────────────
# 最小验证
# ─────────────────────────────────────────────

if __name__ == "__main__":
    import numpy as np
    import pandas as pd

    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=10, freq="B")
    symbols = ["A", "B", "C", "D", "E"]

    # 构造合成测试因子
    f1 = pd.DataFrame(np.random.randn(10, 5), index=dates, columns=symbols)
    f2 = pd.DataFrame(np.random.randn(10, 5), index=dates, columns=symbols)
    f3 = pd.DataFrame(np.random.randn(10, 5), index=dates, columns=symbols)
    ret = pd.DataFrame(np.random.randn(10, 5) * 0.01, index=dates, columns=symbols)

    factors = {"f1": f1, "f2": f2, "f3": f3}

    # zscore_normalize
    z = zscore_normalize(f1)
    assert z.shape == f1.shape, "zscore shape 不匹配"
    assert abs(z.mean(axis=1).mean()) < 1e-10, "zscore 截面均值应为0"
    print(f"✅ zscore_normalize OK | shape={z.shape}")

    # rank_normalize
    r = rank_normalize(f1)
    assert r.shape == f1.shape
    assert r.min().min() > 0 and r.max().max() <= 1.0
    print(f"✅ rank_normalize OK | shape={r.shape}")

    # equal_weight_composite
    eq = equal_weight_composite(factors, normalize="zscore")
    assert eq.shape == (10, 5)
    print(f"✅ equal_weight_composite OK | shape={eq.shape}")

    eq_rank = equal_weight_composite(factors, normalize="rank")
    assert eq_rank.shape == (10, 5)
    print(f"✅ equal_weight_composite(rank) OK | shape={eq_rank.shape}")

    # ic_weighted_composite — 有 ret
    ic_w = ic_weighted_composite(factors, ic_lookback=5, ret_wide=ret)
    assert ic_w.shape == (10, 5)
    print(f"✅ ic_weighted_composite(with ret) OK | shape={ic_w.shape}")

    # ic_weighted_composite — 无 ret（退化等权）
    ic_w2 = ic_weighted_composite(factors, ret_wide=None)
    assert ic_w2.shape == (10, 5)
    print(f"✅ ic_weighted_composite(no ret) OK | shape={ic_w2.shape}")

    # score_composite
    sc = score_composite(factors, direction={"f1": 1, "f2": -1, "f3": 1})
    assert sc.shape == (10, 5)
    assert sc.min().min() >= 0 and sc.max().max() <= 1.0
    print(f"✅ score_composite OK | shape={sc.shape}")

    print("\n✅ 所有多因子合成函数冒烟测试通过")
