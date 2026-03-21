"""
动量因子计算模块
支持多周期动量因子、复合动量因子
"""
import numpy as np
import pandas as pd


def compute_momentum(
    price_wide: pd.DataFrame,
    lookback: int,
    skip: int = 1,
) -> pd.DataFrame:
    """
    计算动量因子（过去 lookback 日的收益率，跳过最近 skip 日）

    参数:
        price_wide : 价格宽表 (date × symbol)
        lookback   : 回看窗口天数
        skip       : 跳过最近的天数（避免短期反转噪音），默认 1

    返回:
        momentum_wide : 动量因子宽表 (date × symbol)
                        值为 [T-lookback-skip, T-skip] 区间的收益率
    """
    # 跳过最近 skip 天的价格
    if skip > 0:
        price_shifted = price_wide.shift(skip)
    else:
        price_shifted = price_wide

    # lookback 天前的价格
    price_past = price_wide.shift(lookback + skip)

    # 动量 = (P_{t-skip} - P_{t-lookback-skip}) / P_{t-lookback-skip}
    momentum = (price_shifted - price_past) / price_past

    return momentum


def compute_multi_period_momentum(
    price_wide: pd.DataFrame,
    periods: list = None,
    skip: int = 1,
) -> dict:
    """
    计算多周期动量因子

    参数:
        price_wide : 价格宽表 (date × symbol)
        periods    : 回看周期列表，默认 [5, 10, 20, 60, 120]
        skip       : 跳过天数

    返回:
        dict: {周期: 动量因子宽表}，如 {5: DataFrame, 10: DataFrame, ...}
    """
    if periods is None:
        periods = [5, 10, 20, 60, 120]

    return {p: compute_momentum(price_wide, lookback=p, skip=skip) for p in periods}


def equal_weight_composite(factor_dict: dict) -> pd.DataFrame:
    """
    等权合成多周期动量因子

    参数:
        factor_dict : {周期: 因子宽表}

    返回:
        合成因子宽表（各周期因子截面排名后等权平均）
    """
    ranked = {}
    for period, fac in factor_dict.items():
        ranked[period] = fac.rank(axis=1, pct=True)

    # 等权平均
    all_ranked = list(ranked.values())
    composite = all_ranked[0].copy()
    for r in all_ranked[1:]:
        composite = composite.add(r, fill_value=np.nan)
    composite = composite / len(all_ranked)

    return composite


if __name__ == "__main__":
    # 最小验证
    import numpy as np

    # 构造测试数据：5只股票 × 30天
    np.random.seed(42)
    dates = pd.bdate_range("2024-01-01", periods=30)
    symbols = ["000001", "000002", "000003", "000004", "000005"]
    prices = pd.DataFrame(
        100 + np.random.randn(30, 5).cumsum(axis=0),
        index=dates,
        columns=symbols,
    )

    # 测试单周期
    mom_5 = compute_momentum(prices, lookback=5, skip=1)
    print(f"5日动量 形状: {mom_5.shape}")
    print(f"5日动量 非空行数: {mom_5.dropna(how='all').shape[0]}")
    assert mom_5.shape == prices.shape
    assert mom_5.iloc[:6].isna().all().all()  # 前 6 行应该是 NaN (lookback+skip=6)

    # 测试多周期
    multi = compute_multi_period_momentum(prices, periods=[5, 10])
    assert len(multi) == 2
    assert 5 in multi and 10 in multi

    # 测试等权合成
    composite = equal_weight_composite(multi)
    assert composite.shape == prices.shape

    print("✅ 动量因子模块验证通过")
