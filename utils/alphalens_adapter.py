"""
alphalens 适配层

把 quant-dojo 的因子宽表（date × symbol）和价格宽表转成 alphalens-reloaded
要求的输入格式，并提供与 utils.factor_analysis 一致性校验工具。

设计原则:
    1. 只是格式转换层，不重新实现 IC / quintile / decay 算法
    2. utils.factor_analysis 保留作为算法参考实现，alphalens 作为研报报告层
    3. 保留 _consistency_check 让两边的 IC 均值差 < 1e-6（验证适配器无漂移）

参考:
    - alphalens-reloaded 0.4.6 API
    - utils.factor_analysis.compute_ic_series
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def to_alphalens_factor(factor_wide: pd.DataFrame) -> pd.Series:
    """
    把因子宽表转成 alphalens 要求的 (date, asset) MultiIndex Series

    参数:
        factor_wide : pd.DataFrame，index=date(datetime64)，columns=symbol(6 位字符串)

    返回:
        pd.Series，MultiIndex (level0=date, level1=asset)，无 NaN
    """
    if not isinstance(factor_wide.index, pd.DatetimeIndex):
        factor_wide = factor_wide.copy()
        factor_wide.index = pd.to_datetime(factor_wide.index)
    s = factor_wide.stack(future_stack=True).dropna()
    s.index = s.index.set_names(["date", "asset"])
    s.name = "factor"
    return s


def to_alphalens_pricing(price_wide: pd.DataFrame) -> pd.DataFrame:
    """
    把价格宽表转成 alphalens 要求的 pricing：index=date, columns=asset, values=price

    alphalens 用价格计算 forward returns，要求和 factor 在 asset 维度对齐。

    参数:
        price_wide : pd.DataFrame，index=date(datetime64)，columns=symbol

    返回:
        pd.DataFrame，纯净格式（DatetimeIndex + 升序）
    """
    out = price_wide.copy()
    if not isinstance(out.index, pd.DatetimeIndex):
        out.index = pd.to_datetime(out.index)
    out = out.sort_index()
    return out


def align_factor_pricing(
    factor_wide: pd.DataFrame,
    price_wide: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    把因子和价格在 (date, asset) 上对齐到公共子集。

    alphalens 计算 forward returns 时要求 factor.date 之后的若干日在 pricing 里存在，
    所以这里先做最大化对齐，让用户可以在 audit 脚本里直接传 (factor_wide, price_wide)
    而不必手动算交集。
    """
    common_dates = factor_wide.index.intersection(price_wide.index).sort_values()
    common_assets = factor_wide.columns.intersection(price_wide.columns)
    f = factor_wide.loc[common_dates, common_assets]
    p = price_wide.loc[common_dates, common_assets]
    return f, p


def consistency_check_ic(
    factor_wide: pd.DataFrame,
    price_wide: pd.DataFrame,
    fwd_period: int = 1,
    method: str = "spearman",
    atol: float = 1e-6,
) -> dict:
    """
    一致性校验：alphalens 的 IC 均值 vs utils.factor_analysis.compute_ic_series 的 IC 均值。

    用于验证适配器没有引入数据漂移、对齐错配、shift 方向反了等问题。
    任何 audit notebook 跑 alphalens 之前必须先调一次这个函数确认通过。

    参数:
        factor_wide  : 因子宽表
        price_wide   : 价格宽表
        fwd_period   : 前瞻天数（default 1）
        method       : 仅 'spearman' 有 alphalens 对照（alphalens 内部硬编码 Rank IC）；
                       'pearson' 仅作为本地参考，不会对照 alphalens
        atol         : 容许 IC 均值差（default 1e-6）

    返回:
        dict 含 ic_mean_local / ic_mean_alphalens / abs_diff / passed
    """
    from utils.factor_analysis import compute_ic_series
    from alphalens.utils import get_clean_factor_and_forward_returns

    f_aligned, p_aligned = align_factor_pricing(factor_wide, price_wide)

    # 1. 本地 IC: factor.shift(0) vs ret_t→t+fwd
    fwd_ret = p_aligned.pct_change(fwd_period).shift(-fwd_period)
    ic_local = compute_ic_series(f_aligned, fwd_ret, method=method).dropna()

    # 2. alphalens IC: 自己内部算 forward returns
    factor_s = to_alphalens_factor(f_aligned)
    factor_data = get_clean_factor_and_forward_returns(
        factor=factor_s,
        prices=to_alphalens_pricing(p_aligned),
        periods=(fwd_period,),
        quantiles=5,
        max_loss=0.5,
    )

    from alphalens.performance import factor_information_coefficient
    ic_al = factor_information_coefficient(factor_data).iloc[:, 0].dropna()

    mean_local = float(ic_local.mean())
    mean_al = float(ic_al.mean())
    diff = abs(mean_local - mean_al)
    passed = diff < atol

    return {
        "ic_mean_local": mean_local,
        "ic_mean_alphalens": mean_al,
        "abs_diff": diff,
        "atol": atol,
        "passed": passed,
        "n_obs_local": len(ic_local),
        "n_obs_alphalens": len(ic_al),
    }


if __name__ == "__main__":
    # 最小验证: 用合成数据跑通转换 + 一致性校验
    rng = np.random.default_rng(42)
    dates = pd.bdate_range("2024-01-02", periods=120)
    syms = [f"{i:06d}" for i in range(50)]

    price = pd.DataFrame(
        100.0 * np.exp(np.cumsum(rng.normal(0, 0.01, size=(len(dates), len(syms))), axis=0)),
        index=dates, columns=syms,
    )
    factor = price.pct_change(20)

    factor_s = to_alphalens_factor(factor.dropna())
    print(f"factor stacked: {factor_s.shape}, idx levels={factor_s.index.names}")

    res = consistency_check_ic(factor.dropna(), price, fwd_period=1)
    print(f"consistency: local={res['ic_mean_local']:.6e} | "
          f"alphalens={res['ic_mean_alphalens']:.6e} | "
          f"diff={res['abs_diff']:.2e} | passed={res['passed']}")
