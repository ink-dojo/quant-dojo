"""
绩效指标计算模块
所有函数接受 pd.Series（日收益率）作为输入
"""
import numpy as np
import pandas as pd


TRADING_DAYS = 252


def annualized_return(returns: pd.Series) -> float:
    """年化复合收益率（几何）。空序列或全亏完返回 0 / -1。"""
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    total = float((1 + r).prod())
    n_years = len(r) / TRADING_DAYS
    if n_years == 0:
        return 0.0
    if total <= 0:
        return -1.0
    return total ** (1 / n_years) - 1


def annualized_volatility(returns: pd.Series) -> float:
    """年化波动率 (ddof=1，GIPS 样本估计)。"""
    return float(returns.dropna().std(ddof=1)) * np.sqrt(TRADING_DAYS)


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.02) -> float:
    """
    夏普比率（arithmetic excess return / std，行业/GIPS 标准）。

    公式: mean(r_daily - rf_daily) / std(r_daily, ddof=1) * sqrt(252)

    注：过去版本用 annualized_return（几何） / annualized_volatility（算术）
    混合口径，数值偏低。现改为纯算术口径，与 Bloomberg / AFML / PSR 公式
    (probabilistic_sharpe 内部) 统一。
    """
    r = returns.dropna()
    if len(r) < 2:
        return 0.0
    std = float(r.std(ddof=1))
    if std == 0:
        return 0.0
    rf_daily = risk_free / TRADING_DAYS
    excess = r - rf_daily
    return float(excess.mean() / std * np.sqrt(TRADING_DAYS))


def max_drawdown(returns: pd.Series) -> float:
    """最大回撤。空/短序列返回 0，NaN 先剔除避免 cumprod 传播。"""
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    cumulative = (1 + r).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    val = drawdown.min()
    return float(val) if pd.notna(val) else 0.0


def calmar_ratio(returns: pd.Series) -> float:
    """卡玛比率 = 年化收益 / |最大回撤|"""
    mdd = abs(max_drawdown(returns))
    ann_ret = annualized_return(returns)
    return ann_ret / mdd if mdd != 0 else 0.0


def win_rate(returns: pd.Series) -> float:
    """胜率（日收益为正的比例）。先剔 NaN，避免 NaN 被记为 '非正'。"""
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    return float((r > 0).mean())


def profit_loss_ratio(returns: pd.Series) -> float:
    """
    盈亏比 = 平均盈利 / 平均亏损。

    边界:
      - 无亏损日 → +inf (全胜)
      - 无盈利日 → 0.0 (全亏)
      - 空序列 → 0.0
    """
    r = returns.dropna()
    if len(r) == 0:
        return 0.0
    win_mask = r > 0
    loss_mask = r < 0
    if not loss_mask.any():
        return float("inf") if win_mask.any() else 0.0
    if not win_mask.any():
        return 0.0
    wins = float(r[win_mask].mean())
    losses = abs(float(r[loss_mask].mean()))
    return wins / losses


def performance_summary(returns: pd.Series, name: str = "Strategy") -> pd.DataFrame:
    """
    输出完整绩效报告

    参数:
        returns: 日收益率 Series
        name: 策略名称

    返回:
        格式化的绩效表格
    """
    metrics = {
        "年化收益率": f"{annualized_return(returns):.2%}",
        "年化波动率": f"{annualized_volatility(returns):.2%}",
        "夏普比率": f"{sharpe_ratio(returns):.2f}",
        "最大回撤": f"{max_drawdown(returns):.2%}",
        "卡玛比率": f"{calmar_ratio(returns):.2f}",
        "胜率": f"{win_rate(returns):.2%}",
        "盈亏比": f"{profit_loss_ratio(returns):.2f}",
        "交易天数": len(returns),
    }
    return pd.DataFrame.from_dict(metrics, orient="index", columns=[name])


def information_ratio(strategy_returns: pd.Series,
                      benchmark_returns: pd.Series) -> float:
    """
    信息比率（IR）：策略相对基准的超额收益 / 超额收益波动率。

    IR = mean(超额收益) * sqrt(252) / std(超额收益)

    参数:
        strategy_returns: 策略日收益率 Series
        benchmark_returns: 基准日收益率 Series（如沪深300）

    返回:
        float, IR 值
    """
    # 对齐后 dropna，不把缺失日当作 0% 基准（否则在 benchmark 缺失日会虚增超额）
    aligned = pd.concat(
        [strategy_returns.rename("s"), benchmark_returns.rename("b")], axis=1
    ).dropna()
    if len(aligned) < 2:
        return 0.0
    excess = aligned["s"] - aligned["b"]
    std = excess.std(ddof=1)
    if std == 0:
        return 0.0
    return float(excess.mean() * np.sqrt(TRADING_DAYS) / std)


def _daily_sharpe_stats(returns: pd.Series):
    """返回 (日度夏普均值, 日度偏度, 日度峰度, 样本数) — 所有高阶统计都基于日度口径。"""
    r = returns.dropna()
    n = len(r)
    if n < 30:
        return None
    mu = r.mean()
    sigma = r.std(ddof=1)
    if sigma == 0:
        return None
    sr_daily = mu / sigma
    skew = float(((r - mu) ** 3).mean() / sigma ** 3)
    kurt = float(((r - mu) ** 4).mean() / sigma ** 4)
    return sr_daily, skew, kurt, n


def probabilistic_sharpe(
    returns: pd.Series,
    sr_benchmark: float = 0.0,
    risk_free: float = 0.02,
) -> float:
    """
    Probabilistic Sharpe Ratio (PSR)。

    PSR = Prob(SR_true > sr_benchmark)，基于观测 sharpe、样本量、偏度、峰度。
    Bailey & López de Prado (2012)。sr_benchmark 为年化口径，函数内换算到日度。

    返回:
        float in [0,1]。≥ 0.95 才算 &quot;统计显著优于 benchmark&quot;。
    """
    from scipy import stats

    stats_tuple = _daily_sharpe_stats(returns)
    if stats_tuple is None:
        return 0.0
    sr_daily, skew, kurt, n = stats_tuple
    sr_bench_daily = sr_benchmark / np.sqrt(TRADING_DAYS)
    denom = np.sqrt(
        max(1.0 - skew * sr_daily + 0.25 * (kurt - 1.0) * sr_daily ** 2, 1e-12)
    )
    z = (sr_daily - sr_bench_daily) * np.sqrt(n - 1) / denom
    return float(stats.norm.cdf(z))


def deflated_sharpe(
    returns: pd.Series,
    n_trials: int,
    trials_sharpe_std: float,
) -> float:
    """
    Deflated Sharpe Ratio (DSR)。

    当从 n_trials 个候选里挑 &quot;sharpe 最高&quot; 的那个，观察到的 sharpe 已经被选择偏差
    抬高。DSR 是 PSR(returns) 针对 &quot;benchmark = 期望最大 sharpe (预期纯噪声下)&quot; 的修正。

    参数:
        returns: 入选策略的日收益率 Series。
        n_trials: 候选数量（例如挖掘会话里的 11 个版本 → n_trials=11）。
        trials_sharpe_std: 候选池内年化 sharpe 的标准差（跨候选）。

    返回:
        float in [0,1]，解释同 PSR。
    """
    if n_trials < 2 or trials_sharpe_std <= 0:
        return probabilistic_sharpe(returns, sr_benchmark=0.0)

    euler_mascheroni = 0.5772156649
    # 预期最大夏普 (年化)：近似正态分布 max-order-statistic
    from scipy import stats

    expected_max_sr = trials_sharpe_std * (
        (1.0 - euler_mascheroni) * stats.norm.ppf(1.0 - 1.0 / n_trials)
        + euler_mascheroni * stats.norm.ppf(1.0 - 1.0 / (n_trials * np.e))
    )
    return probabilistic_sharpe(returns, sr_benchmark=expected_max_sr)


def bootstrap_sharpe_ci(
    returns: pd.Series,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> dict:
    """
    Bootstrap 置信区间（日收益 stationary block resample）。

    返回:
        dict with keys: sharpe, ci_low, ci_high, n_boot
    """
    r = returns.dropna().values
    n = len(r)
    if n < 60:
        return {"sharpe": sharpe_ratio(returns), "ci_low": np.nan, "ci_high": np.nan, "n_boot": 0}
    rng = np.random.default_rng(seed)
    # Stationary bootstrap with expected block length = sqrt(n) to preserve autocorr
    block_len = max(int(np.sqrt(n)), 5)
    sr_draws = np.empty(n_boot)
    for i in range(n_boot):
        idx = []
        while len(idx) < n:
            start = int(rng.integers(0, n))
            length = int(rng.geometric(1.0 / block_len))
            idx.extend(((np.arange(length) + start) % n).tolist())
        idx = np.asarray(idx[:n])
        sample = pd.Series(r[idx])
        sr_draws[i] = sharpe_ratio(sample)
    low = float(np.quantile(sr_draws, alpha / 2))
    high = float(np.quantile(sr_draws, 1 - alpha / 2))
    return {
        "sharpe": float(sharpe_ratio(returns)),
        "ci_low": low,
        "ci_high": high,
        "n_boot": int(n_boot),
    }


def min_track_record_length(
    returns: pd.Series,
    sr_target: float = 0.0,
    confidence: float = 0.95,
) -> float:
    """
    MinTRL: 达到统计显著优于 sr_target 所需的最短样本数（单位 = 交易日，不是日历日）。
    Bailey & López de Prado (2012) 公式 14.7；返回 Series 长度，需要折算到日历周期请
    除以 252/365。
    """
    from scipy import stats as _stats

    stats_tuple = _daily_sharpe_stats(returns)
    if stats_tuple is None:
        return float("nan")
    sr_daily, skew, kurt, n = stats_tuple
    sr_target_daily = sr_target / np.sqrt(TRADING_DAYS)
    if sr_daily <= sr_target_daily:
        return float("inf")
    z = _stats.norm.ppf(confidence)
    numer = 1.0 - skew * sr_daily + 0.25 * (kurt - 1.0) * sr_daily ** 2
    denom = (sr_daily - sr_target_daily) ** 2
    return float(1.0 + numer / denom * z ** 2)
