"""
tradability_filter.py — 最小可交易约束过滤模块

提供统一的可交易性过滤，返回 bool mask DataFrame（True = 可交易）。
适用于因子研究和回测中的股票池预筛选。

用法：
    from utils.tradability_filter import apply_tradability_filter, cap_weights
    mask = apply_tradability_filter(price_wide)
    capped = cap_weights(weights, max_weight=0.1)
"""

import numpy as np
import pandas as pd


def _st_proxy_mask(daily_ret: pd.DataFrame, threshold: float = -0.045,
                   count: int = 3, window: int = 20) -> pd.DataFrame:
    """
    ST 股票代理检测：在 window 日内单日跌幅超过 threshold 次数 > count 的标记为疑似 ST。

    参数:
        daily_ret: 日收益率 wide DataFrame (index=日期, columns=股票代码)
        threshold: 单日跌幅阈值，默认 -4.5%
        count: 触发次数阈值
        window: 滚动窗口天数

    返回:
        bool DataFrame，True = 疑似 ST（应排除）
    """
    big_drop = daily_ret < threshold
    rolling_count = big_drop.rolling(window=window, min_periods=1).sum()
    return rolling_count > count


def _min_listing_mask(price_wide: pd.DataFrame, min_days: int = 60) -> pd.DataFrame:
    """
    排除上市不足 min_days 交易日的股票（IPO 溢价期）。
    通过每列第一个非 NaN 的位置来判断上市日。

    参数:
        price_wide: 价格 wide DataFrame
        min_days: 最少上市交易日数

    返回:
        bool DataFrame，True = 上市天数不足（应排除）
    """
    mask = pd.DataFrame(False, index=price_wide.index, columns=price_wide.columns)
    for col in price_wide.columns:
        first_valid = price_wide[col].first_valid_index()
        if first_valid is None:
            # 全是 NaN，整列排除
            mask[col] = True
            continue
        loc = price_wide.index.get_loc(first_valid)
        # 上市后前 min_days 天标记为不可交易
        end_loc = min(loc + min_days, len(price_wide))
        mask.iloc[loc:end_loc, mask.columns.get_loc(col)] = True
    return mask


def _min_price_mask(price_wide: pd.DataFrame, min_price: float = 2.0) -> pd.DataFrame:
    """
    排除价格低于 min_price 的股票。

    参数:
        price_wide: 价格 wide DataFrame
        min_price: 最低价格阈值（元）

    返回:
        bool DataFrame，True = 价格过低（应排除）
    """
    return price_wide < min_price


def _illiquidity_mask(daily_ret: pd.DataFrame, window: int = 20,
                      pct: float = 0.05) -> pd.DataFrame:
    """
    排除流动性最差的股票：20 日平均日收益率绝对值在截面最低 5% 的股票。
    当无成交量数据时，用收益率绝对值的均值作为流动性代理。

    参数:
        daily_ret: 日收益率 wide DataFrame
        window: 滚动窗口天数
        pct: 截面排除百分位（底部）

    返回:
        bool DataFrame，True = 流动性不足（应排除）
    """
    avg_abs_ret = daily_ret.abs().rolling(window=window, min_periods=max(1, window // 2)).mean()
    # 逐行计算截面分位数阈值
    quantile_threshold = avg_abs_ret.quantile(pct, axis=1)
    # 广播比较：低于阈值的标记为不可交易
    return avg_abs_ret.lt(quantile_threshold, axis=0)


def apply_tradability_filter(
    price_wide: pd.DataFrame,
    daily_ret: pd.DataFrame = None,
    volume_wide: pd.DataFrame = None,
    min_listing_days: int = 60,
    min_price: float = 2.0,
    st_threshold: float = -0.045,
    st_count: int = 3,
    st_window: int = 20,
    illiquidity_window: int = 20,
    illiquidity_pct: float = 0.05,
) -> pd.DataFrame:
    """
    综合可交易性过滤，返回 bool mask（True = 可交易）。

    参数:
        price_wide: 收盘价 wide DataFrame (index=日期, columns=股票代码)
        daily_ret: 日收益率 wide DataFrame，为 None 时自动从 price_wide 计算
        volume_wide: 成交量 wide DataFrame（暂未使用，预留接口）
        min_listing_days: 排除上市不足天数，默认 60
        min_price: 最低价格阈值（元），默认 2.0
        st_threshold: ST 代理检测跌幅阈值，默认 -4.5%
        st_count: ST 代理检测触发次数
        st_window: ST 代理检测滚动窗口
        illiquidity_window: 流动性检测滚动窗口
        illiquidity_pct: 流动性截面排除百分位

    返回:
        bool DataFrame（同 price_wide 形状），True = 可交易
    """
    # 自动计算日收益率
    if daily_ret is None:
        daily_ret = price_wide.pct_change()

    # 基础 mask：有价格数据的位置
    tradable = price_wide.notna()

    # 1. ST 代理过滤
    st_exclude = _st_proxy_mask(daily_ret, threshold=st_threshold,
                                count=st_count, window=st_window)
    tradable = tradable & ~st_exclude

    # 2. 上市天数过滤
    listing_exclude = _min_listing_mask(price_wide, min_days=min_listing_days)
    tradable = tradable & ~listing_exclude

    # 3. 最低价格过滤
    price_exclude = _min_price_mask(price_wide, min_price=min_price)
    tradable = tradable & ~price_exclude

    # 4. 流动性过滤
    liq_exclude = _illiquidity_mask(daily_ret, window=illiquidity_window,
                                    pct=illiquidity_pct)
    tradable = tradable & ~liq_exclude

    return tradable


def cap_weights(weights_series: pd.Series, max_weight: float = 0.1) -> pd.Series:
    """
    权重上限截断并重新分配：超过 max_weight 的部分按比例分配给未超限的股票。

    参数:
        weights_series: 原始权重 Series (index=股票代码, values=权重)
        max_weight: 单只股票最大权重，默认 0.1 (10%)

    返回:
        截断后的权重 Series，总和保持与输入一致
    """
    if weights_series.empty:
        return weights_series.copy()

    weights = weights_series.copy()
    total = weights.sum()
    if total == 0:
        return weights

    # 迭代截断直到所有权重 <= max_weight
    for _ in range(100):  # 安全上限防止无限循环
        over = weights > max_weight
        if not over.any():
            break
        excess = (weights[over] - max_weight).sum()
        weights[over] = max_weight
        under = ~over & (weights > 0)
        if under.sum() == 0:
            break
        # 按比例分配超出部分
        under_total = weights[under].sum()
        if under_total > 0:
            weights[under] += excess * (weights[under] / under_total)

    # 确保总和一致（浮点误差修正）
    current_total = weights.sum()
    if current_total > 0:
        weights = weights * (total / current_total)

    return weights


if __name__ == "__main__":
    # 最小烟雾测试
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=120, freq="B")
    stocks = [f"SH60000{i}" for i in range(10)]
    price = pd.DataFrame(
        np.random.uniform(1.5, 50, size=(120, 10)),
        index=dates, columns=stocks
    )
    # 模拟一只股票前 30 天没数据（新股）
    price.iloc[:30, 0] = np.nan
    # 模拟一只低价股
    price.iloc[:, 1] = 1.5

    mask = apply_tradability_filter(price)
    assert mask.shape == price.shape, f"形状不匹配: {mask.shape} vs {price.shape}"
    assert mask.dtypes.apply(lambda x: x == bool).all(), "非 bool 类型"
    # 低价股应该被过滤
    assert not mask.iloc[-1, 1], "低价股应被排除"
    # 新股前 60 天应被过滤
    assert not mask.iloc[35, 0], "新股 IPO 期应被排除"

    # 测试 cap_weights
    w = pd.Series([0.5, 0.3, 0.1, 0.1], index=["A", "B", "C", "D"])
    capped = cap_weights(w, max_weight=0.25)
    assert capped.max() <= 0.25 + 1e-10, f"权重超限: {capped.max()}"
    assert abs(capped.sum() - w.sum()) < 1e-10, "总权重不一致"

    print("✅ tradability_filter 烟雾测试通过")
