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
# ICIR 加权（训练期学习权重）
# ─────────────────────────────────────────────

def icir_weight(
    factors: dict,
    price_wide: pd.DataFrame,
    train_start,
    train_end,
    fwd_days: int = 20,
    min_weight: float = 0.0,
    min_stocks: int = 30,
) -> dict:
    """
    基于训练期 ICIR 计算各因子权重（严格无未来泄漏）。

    算法：
      1. 构造 fwd_ret = 未来 fwd_days 日收益率（shift(-fwd_days)）
      2. 在 [train_start, train_end - fwd_days] 区间内计算每个因子的每日截面 Rank IC
         （上限截断确保 fwd_ret 值完全落在训练期内，不用到测试期价格）
      3. ICIR_i = mean(IC_i) / std(IC_i)
      4. 权重_i = |ICIR_i| / Σ|ICIR|
      5. 应用 min_weight 地板并重新归一化
      6. 方向 sign_i = sign(mean(IC_i))，供调用方将负IC因子翻转

    参数:
        factors     : {因子名: 因子宽表}，所有因子已对齐相同 index/columns
        price_wide  : 原始价格宽表，用于计算前向收益
        train_start : 训练期起始（Timestamp 或字符串）
        train_end   : 训练期结束
        fwd_days    : 前向收益窗口（交易日），默认 20（约一个月）
        min_weight  : 权重下限，默认 0（无下限）。设为 0.05 可防止极端稀疏
        min_stocks  : 单日 IC 计算的最低有效股票数

    返回:
        dict:
          "weights"  : {因子名: 权重}，和=1，值域 [min_weight, 1]
          "signs"    : {因子名: +1 或 -1}，IC 均值为负的因子翻转
          "ic_stats" : {因子名: {"ic_mean", "ic_std", "icir", "n"}}

    幂等性与退化：
      - 若训练期天数 ≤ fwd_days：返回等权
      - 若所有因子 IC 都是 NaN：返回等权
      - 若某因子 n<20（IC 样本不足）：该因子 |ICIR| 记为 0，权重降至 min_weight
    """
    from utils.factor_analysis import compute_ic_series

    n_factors = len(factors)
    if n_factors == 0:
        return {"weights": {}, "signs": {}, "ic_stats": {}}

    # 构造前向收益
    fwd_ret = price_wide.pct_change(fwd_days).shift(-fwd_days)

    # 训练期日期
    train_dates = price_wide.loc[train_start:train_end].index
    if len(train_dates) <= fwd_days + 5:
        # 训练期太短 → 退化等权
        w_eq = 1.0 / n_factors
        return {
            "weights":  {name: w_eq for name in factors},
            "signs":    {name: 1 for name in factors},
            "ic_stats": {name: {"ic_mean": np.nan, "ic_std": np.nan, "icir": 0.0, "n": 0}
                         for name in factors},
        }

    # 截断到训练期末 - fwd_days：确保 fwd_ret 只用训练期价格
    # 前提：train_dates 是 price_wide.index 在 [train_start, train_end] 的连续切片，
    # 所以 train_dates[-fwd_days-1] 向后 fwd_days 行恰好是 train_dates[-1]（最后训练日）
    cutoff = train_dates[-fwd_days - 1]

    ic_stats = {}
    abs_icirs = {}
    signs = {}

    for name, fac in factors.items():
        fac_slice = fac.loc[train_start:cutoff]
        ret_slice = fwd_ret.loc[train_start:cutoff]
        ic = compute_ic_series(fac_slice, ret_slice, method="spearman",
                               min_stocks=min_stocks)
        ic = ic.dropna()
        if len(ic) < 20:
            ic_stats[name] = {"ic_mean": np.nan, "ic_std": np.nan, "icir": 0.0, "n": len(ic)}
            abs_icirs[name] = 0.0
            signs[name] = 1
            continue
        ic_mean = ic.mean()
        ic_std = ic.std()
        icir = ic_mean / ic_std if ic_std > 0 else 0.0
        abs_icirs[name] = abs(icir)
        signs[name] = 1 if ic_mean >= 0 else -1
        ic_stats[name] = {"ic_mean": ic_mean, "ic_std": ic_std, "icir": icir, "n": len(ic)}

    # 构造权重：先扣除 floor，剩余按 |ICIR| 比例分配
    total_icir = sum(abs_icirs.values())
    w_eq = 1.0 / n_factors

    if min_weight <= 0 or min_weight * n_factors >= 1.0 - 1e-9:
        # 无 floor，或 floor 不可行（n*min > 1）→ 纯比例或等权
        if min_weight * n_factors >= 1.0 - 1e-9:
            weights = {name: w_eq for name in factors}
        elif total_icir <= 1e-12:
            weights = {name: w_eq for name in factors}
        else:
            weights = {name: v / total_icir for name, v in abs_icirs.items()}
    else:
        # Floor 可行：每人先分 min_weight，剩余按 |ICIR| 比例
        remainder = 1.0 - min_weight * n_factors
        if total_icir <= 1e-12:
            # ICIR 全零 → 等权
            weights = {name: w_eq for name in factors}
        else:
            weights = {
                name: min_weight + remainder * (abs_icirs[name] / total_icir)
                for name in factors
            }

    return {"weights": weights, "signs": signs, "ic_stats": ic_stats}


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

    # ─────────── icir_weight 测试 ───────────
    # 构造一个"信号强"的因子：f_strong[t] 和 未来收益同号
    # 和一个"纯噪音"的因子：f_noise 与未来收益无关
    np.random.seed(2025)
    n_days = 400
    n_stocks = 60
    dates_big = pd.date_range("2024-01-01", periods=n_days, freq="B")
    symbols_big = [f"S{i:02d}" for i in range(n_stocks)]

    # 价格：随机游走
    returns = np.random.randn(n_days, n_stocks) * 0.02
    prices = pd.DataFrame(100 * np.exp(np.cumsum(returns, axis=0)),
                          index=dates_big, columns=symbols_big)

    # 强因子：前向 20 日收益 + 小噪音（IC 应该很高）
    fwd20 = prices.pct_change(20).shift(-20)
    f_strong = fwd20 + np.random.randn(n_days, n_stocks) * 0.01
    f_noise  = pd.DataFrame(np.random.randn(n_days, n_stocks),
                            index=dates_big, columns=symbols_big)
    f_medium = 0.5 * fwd20 + 0.5 * pd.DataFrame(
        np.random.randn(n_days, n_stocks), index=dates_big, columns=symbols_big)

    fac_dict = {"strong": f_strong, "noise": f_noise, "medium": f_medium}

    train_start = dates_big[0]
    train_end = dates_big[250]

    # 基础测试
    result = icir_weight(fac_dict, prices, train_start, train_end, fwd_days=20)
    ws = result["weights"]
    assert len(ws) == 3, "权重个数应等于因子数"
    assert abs(sum(ws.values()) - 1.0) < 1e-9, f"权重应和为 1，实际 {sum(ws.values())}"
    assert ws["strong"] > ws["noise"], f"强因子权重应>噪音因子，实际 strong={ws['strong']:.3f}, noise={ws['noise']:.3f}"
    assert ws["strong"] > ws["medium"], "强因子权重应>中等因子"
    assert all(w >= 0 for w in ws.values()), "权重不应为负"
    print(f"✅ icir_weight 基础测试 OK | strong={ws['strong']:.3f} medium={ws['medium']:.3f} noise={ws['noise']:.3f}")

    # 方向检测测试：构造一个反向因子（IC 为负）
    f_inverse = -f_strong  # 和未来收益反向
    fac_inv = {"strong": f_strong, "inverse": f_inverse, "noise": f_noise}
    res_inv = icir_weight(fac_inv, prices, train_start, train_end, fwd_days=20)
    assert res_inv["signs"]["inverse"] == -1, f"反向因子 sign 应为 -1，实际 {res_inv['signs']['inverse']}"
    assert res_inv["signs"]["strong"] == 1, "强因子 sign 应为 +1"
    # inverse 的 |ICIR| 应接近 strong（只是方向反了）
    assert abs(res_inv["weights"]["inverse"] - res_inv["weights"]["strong"]) < 0.1, \
        "反向因子权重幅值应接近强因子"
    print(f"✅ icir_weight 方向检测 OK | inverse sign={res_inv['signs']['inverse']}")

    # min_weight floor 测试
    res_floor = icir_weight(fac_dict, prices, train_start, train_end,
                             fwd_days=20, min_weight=0.2)
    assert all(w >= 0.2 - 1e-9 for w in res_floor["weights"].values()), \
        f"min_weight floor 失效：{res_floor['weights']}"
    assert abs(sum(res_floor["weights"].values()) - 1.0) < 1e-9, "floor 后应重新归一化"
    print(f"✅ icir_weight min_weight floor OK | 最低={min(res_floor['weights'].values()):.3f}")

    # 退化测试：训练期太短
    res_short = icir_weight(fac_dict, prices, dates_big[0], dates_big[10], fwd_days=20)
    ws_short = res_short["weights"]
    assert all(abs(w - 1/3) < 1e-9 for w in ws_short.values()), \
        f"训练期太短应退化等权：{ws_short}"
    print(f"✅ icir_weight 训练期太短退化等权 OK")

    # 诊断信息完整性
    stats_dict = result["ic_stats"]
    for name in fac_dict:
        assert name in stats_dict, f"缺少 {name} 的 ic_stats"
        s = stats_dict[name]
        assert {"ic_mean", "ic_std", "icir", "n"}.issubset(s.keys()), \
            f"{name} ic_stats 缺字段：{s.keys()}"
    print(f"✅ icir_weight 诊断信息完整")

    print("\n✅ 所有多因子合成函数冒烟测试通过")
