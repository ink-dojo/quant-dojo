"""
低波动因子模块
实现已实现波动率、Beta 因子及合成低波动因子

低波动异象：低波动/低Beta的股票往往获得更高的风险调整收益（与CAPM预测相反）。
因子值取负：低波动/低Beta对应大因子值，便于统一按"因子值越大越好"的框架分析。
"""
import numpy as np
import pandas as pd

from utils.factor_analysis import winsorize


def _cross_winsorize(df: pd.DataFrame, n_sigma: float = 3.0) -> pd.DataFrame:
    """逐行（按截面日）应用 ±n_sigma 截尾，防止极端值污染 z-score。"""
    return df.apply(lambda row: winsorize(row, n_sigma=n_sigma), axis=1)


def compute_realized_vol(ret_wide: pd.DataFrame, window: int = 20) -> pd.DataFrame:
    """
    计算滚动已实现波动率因子

    基于历史日收益率的滚动标准差，年化处理（* sqrt(252)）。
    因子值取负：低波动率 = 大因子值，符合"低波动溢价"假说。

    参数:
        ret_wide : 日收益率宽表 (date × symbol)，值为日收益率（如 0.01 表示 1%）
        window   : 滚动窗口天数，默认 20 日

    返回:
        vol_factor : 低波动率因子宽表 (date × symbol)，取值为负的年化波动率
    """
    # 滚动标准差 * sqrt(252) = 年化波动率
    ann_vol = ret_wide.rolling(window=window, min_periods=int(window * 0.8)).std() * np.sqrt(252)
    # 取负：低波动率对应大因子值
    return -ann_vol


def compute_beta(
    ret_wide: pd.DataFrame,
    market_ret: pd.Series,
    window: int = 60,
) -> pd.DataFrame:
    """
    计算滚动 Beta 因子（相对沪深300）

    使用滚动 OLS（numpy.polyfit 实现），估计每只股票相对市场的系统性风险暴露。
    因子值取负：低Beta = 大因子值，反映"低Beta异象"。

    参数:
        ret_wide   : 日收益率宽表 (date × symbol)
        market_ret : 市场收益率序列（如沪深300日收益率），index 为 trade_date
        window     : 滚动窗口天数，默认 60 日

    返回:
        beta_factor : 低Beta因子宽表 (date × symbol)，取值为负的Beta系数
    """
    # 对齐日期
    common_dates = ret_wide.index.intersection(market_ret.index)
    ret_aligned = ret_wide.loc[common_dates]
    mkt_aligned = market_ret.loc[common_dates]

    n_dates = len(common_dates)
    n_stocks = len(ret_aligned.columns)
    beta_vals = np.full((n_dates, n_stocks), np.nan)

    min_periods = int(window * 0.8)

    for i in range(n_dates):
        if i < min_periods:
            continue
        start = max(0, i - window + 1)
        mkt_window = mkt_aligned.iloc[start:i + 1].values  # shape: (T,)

        for j in range(n_stocks):
            stock_window = ret_aligned.iloc[start:i + 1, j].values
            # 去掉含 NaN 的行
            mask = ~(np.isnan(mkt_window) | np.isnan(stock_window))
            if mask.sum() < min_periods:
                continue
            # polyfit: y = beta * x + alpha，返回 [beta, alpha]
            coef = np.polyfit(mkt_window[mask], stock_window[mask], 1)
            beta_vals[i, j] = coef[0]  # beta 系数

    beta_df = pd.DataFrame(beta_vals, index=common_dates, columns=ret_aligned.columns)
    # 取负：低Beta对应大因子值
    return -beta_df


def compute_composite_low_vol(
    vol_factor: pd.DataFrame,
    beta_factor: pd.DataFrame,
    weights: tuple = (0.5, 0.5),
) -> pd.DataFrame:
    """
    合成低波动因子

    对每个截面日分别对波动率因子和Beta因子做 z-score 标准化，
    然后按指定权重加权求和。

    参数:
        vol_factor  : 已实现波动率因子宽表（来自 compute_realized_vol）
        beta_factor : Beta 因子宽表（来自 compute_beta）
        weights     : (w_vol, w_beta) 权重元组，默认各 0.5，需合计为 1

    返回:
        composite : 合成低波动因子宽表 (date × symbol)
    """
    assert abs(sum(weights) - 1.0) < 1e-6, "权重之和必须为 1"
    w_vol, w_beta = weights

    # 对齐日期和股票
    common_dates = vol_factor.index.intersection(beta_factor.index)
    common_stocks = vol_factor.columns.intersection(beta_factor.columns)

    vol_aligned = vol_factor.loc[common_dates, common_stocks]
    beta_aligned = beta_factor.loc[common_dates, common_stocks]

    def cross_zscore(df: pd.DataFrame) -> pd.DataFrame:
        """截面 z-score 标准化（逐行）"""
        mean = df.mean(axis=1)
        std = df.std(axis=1)
        return df.sub(mean, axis=0).div(std.replace(0, np.nan), axis=0)

    vol_z = cross_zscore(_cross_winsorize(vol_aligned))
    beta_z = cross_zscore(_cross_winsorize(beta_aligned))

    composite = vol_z * w_vol + beta_z * w_beta
    return composite


if __name__ == "__main__":
    # 最小验证：构造模拟数据，测试三个函数能否正常运行
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=120, freq="B")
    symbols = [f"S{i:03d}" for i in range(50)]

    # 模拟日收益率
    ret_mock = pd.DataFrame(
        np.random.randn(120, 50) * 0.02,
        index=dates,
        columns=symbols,
    )
    mkt_mock = pd.Series(np.random.randn(120) * 0.015, index=dates, name="market")

    vol_fac = compute_realized_vol(ret_mock, window=20)
    print(f"✅ compute_realized_vol | shape: {vol_fac.shape} | 非空: {vol_fac.notna().sum().sum()}")

    beta_fac = compute_beta(ret_mock, mkt_mock, window=60)
    print(f"✅ compute_beta         | shape: {beta_fac.shape} | 非空: {beta_fac.notna().sum().sum()}")

    composite = compute_composite_low_vol(vol_fac, beta_fac)
    print(f"✅ compute_composite_low_vol | shape: {composite.shape} | 非空: {composite.notna().sum().sum()}")

    print("\n✅ low_vol_factor 模块验证通过")
