"""
市场状态过滤器 — RSRS 择时指标

基于中金证券研报《量化择时系列（1）：金融工程视角下的技术择时艺术》。
参考实现：hugo2046/QuantsPlaybook/SignalMaker/qrs.py

核心逻辑：
  1. 对最近 N 天的 high ~ low 做回归，取斜率 beta
  2. beta 做 M 天 z-score 标准化
  3. 乘以 corr^n 惩罚项（corr 低时信号打折）
  4. 信号 > upper_threshold → 看多，< lower_threshold → 看空

用法：
  from utils.market_regime import compute_rsrs_signal, rsrs_regime_mask

  # 方式 1：直接算信号值
  signal = compute_rsrs_signal(index_high, index_low)

  # 方式 2：生成 bool mask（True=可交易/看多）
  mask = rsrs_regime_mask(index_high, index_low, upper=0.7, lower=-0.7)
"""
import numpy as np
import pandas as pd


def _sliding_window(arr: np.ndarray, window: int) -> np.ndarray:
    """生成滑动窗口视图"""
    shape = (arr.shape[0] - window + 1, window) + arr.shape[1:]
    strides = (arr.strides[0],) + arr.strides
    return np.lib.stride_tricks.as_strided(arr, shape=shape, strides=strides)


def compute_rsrs_signal(
    high: pd.Series,
    low: pd.Series,
    regression_window: int = 18,
    zscore_window: int = 600,
    corr_power: int = 2,
) -> pd.Series:
    """
    计算 RSRS 择时信号（z-score 标准化 + corr 惩罚）。

    参数:
        high: 指数/股票最高价序列（日频，DatetimeIndex）
        low: 指数/股票最低价序列
        regression_window: 回归窗口 N（默认 18 天）
        zscore_window: z-score 标准化窗口 M（默认 600 天）
        corr_power: corr 惩罚幂次（默认 2）

    返回:
        pd.Series: RSRS 信号值，正值看多/负值看空
    """
    h = high.values.astype(float)
    l = low.values.astype(float)

    n = len(h)
    if n < regression_window + zscore_window:
        return pd.Series(dtype=float, index=high.index)

    # 逐窗口计算 beta 和 corr
    betas = np.full(n, np.nan)
    corrs = np.full(n, np.nan)

    for i in range(regression_window - 1, n):
        lo = l[i - regression_window + 1: i + 1]
        hi = h[i - regression_window + 1: i + 1]

        lo_std = np.std(lo)
        hi_std = np.std(hi)
        if lo_std == 0 or hi_std == 0:
            continue

        corr = np.corrcoef(lo, hi)[0, 1]
        beta = hi_std / lo_std * corr

        betas[i] = beta
        corrs[i] = corr

    # z-score 标准化 beta
    beta_series = pd.Series(betas, index=high.index)
    beta_mean = beta_series.rolling(zscore_window, min_periods=zscore_window).mean()
    beta_std = beta_series.rolling(zscore_window, min_periods=zscore_window).std()
    zscore = (beta_series - beta_mean) / beta_std

    # 惩罚项
    corr_series = pd.Series(corrs, index=high.index)
    regulation = corr_series ** corr_power

    signal = zscore * regulation
    signal.name = "rsrs_signal"
    return signal


def rsrs_regime_mask(
    high: pd.Series,
    low: pd.Series,
    upper: float = 0.7,
    lower: float = -0.7,
    regression_window: int = 18,
    zscore_window: int = 600,
) -> pd.Series:
    """
    生成 RSRS 市场状态 mask。

    参数:
        high, low: 指数最高价/最低价
        upper: 看多阈值（信号向上穿越后持续看多）
        lower: 看空阈值（信号向下穿越后持续看空）
        regression_window, zscore_window: RSRS 参数

    返回:
        pd.Series[bool]: True=看多/可交易, False=看空/应规避
    """
    signal = compute_rsrs_signal(high, low, regression_window, zscore_window)

    # 状态机：穿越 upper 后看多，穿越 lower 后看空
    mask = pd.Series(True, index=signal.index)
    state = True  # 初始看多

    for i in range(len(signal)):
        if pd.isna(signal.iloc[i]):
            mask.iloc[i] = state
            continue
        if signal.iloc[i] > upper:
            state = True
        elif signal.iloc[i] < lower:
            state = False
        mask.iloc[i] = state

    mask.name = "rsrs_bullish"
    return mask


def vol_turnover_regime(
    close: pd.Series,
    volume: pd.Series,
    window: int = 200,
    upper: float = None,
    lower: float = None,
) -> pd.Series:
    """
    波动率/换手率牛熊指标。

    核心思路：std(ret,200) / mean(volume,200)
    高值 = 恐慌（高波动+低参与）= 熊市
    低值 = 贪婪（低波动+高参与）= 牛市

    参考：QuantsPlaybook/C-择时类/CSVC框架及熊牛指标

    参数:
        close: 指数收盘价
        volume: 指数成交量
        window: 滚动窗口（默认 200 天）
        upper/lower: 阈值（默认用中位数分界）

    返回:
        pd.Series[bool]: True=看多, False=看空
    """
    ret = close.pct_change()
    vol = ret.rolling(window, min_periods=window).std()
    avg_volume = volume.rolling(window, min_periods=window).mean()

    kernel = vol / avg_volume.replace(0, np.nan)

    if upper is None or lower is None:
        # 用中位数作为分界
        median_val = kernel.median()
        upper = median_val if upper is None else upper
        lower = median_val if lower is None else lower

    # kernel 低 = 牛（低波动/高参与），kernel 高 = 熊
    mask = kernel < lower
    mask.name = "vol_turn_bullish"
    return mask


def composite_regime(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
) -> pd.Series:
    """
    复合市场状态：RSRS + 波动率/换手率，两者都看多才看多。

    返回:
        pd.Series[bool]: True=看多
    """
    rsrs = rsrs_regime_mask(high, low)
    vt = vol_turnover_regime(close, volume)
    # 对齐
    common = rsrs.index.intersection(vt.index)
    result = rsrs.loc[common] & vt.loc[common]
    result.name = "composite_bullish"
    return result


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).parent.parent))
    from utils.data_loader import get_index_history

    hs300 = get_index_history(symbol="sh000300", start="2015-01-01", end="2024-12-31")
    signal = compute_rsrs_signal(hs300["high"], hs300["low"])
    mask = rsrs_regime_mask(hs300["high"], hs300["low"])

    valid = signal.dropna()
    bull_pct = mask.loc[valid.index].mean()
    print(f"RSRS 信号: {len(valid)} 天有效")
    print(f"  均值: {valid.mean():.4f}")
    print(f"  看多比例: {bull_pct:.1%}")
    print(f"  看空比例: {1-bull_pct:.1%}")
    print("✅ market_regime import ok")
