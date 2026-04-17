"""
因子分析工具模块
提供 IC 计算、分层回测、去极值、行业市值中性化等标准流程

所有函数均以宽表（date × symbol 的 DataFrame）为输入/输出。
"""
import numpy as np
import pandas as pd
from scipy import stats
from tqdm import tqdm


# ─────────────────────────────────────────────
# 数据预处理
# ─────────────────────────────────────────────

def winsorize(series: pd.Series, n_sigma: float = 3.0) -> pd.Series:
    """
    截面去极值（±n_sigma 截尾）

    参数:
        series  : 单截面因子值
        n_sigma : 截尾倍数，默认3σ
    """
    mean = series.mean()
    std = series.std()
    return series.clip(lower=mean - n_sigma * std, upper=mean + n_sigma * std)


def cross_section_rank(factor_wide: pd.DataFrame) -> pd.DataFrame:
    """对因子宽表按日期做截面排名（转为百分比排名）"""
    return factor_wide.rank(axis=1, pct=True)


# ─────────────────────────────────────────────
# IC 分析
# ─────────────────────────────────────────────

def compute_ic_series(
    factor_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    method: str = "spearman",
    min_stocks: int = 30,
) -> pd.Series:
    """
    计算每日截面 IC（信息系数）

    参数:
        factor_wide : 因子宽表 (date × symbol)
        ret_wide    : 收益率宽表 (date × symbol)
        method      : 'pearson'（IC）或 'spearman'（Rank IC），推荐用 spearman
        min_stocks  : 每日有效股票数最低门槛，低于则跳过

    返回:
        ic_series : pd.Series，index 为 trade_date
    """
    common_dates = factor_wide.index.intersection(ret_wide.index)
    common_stocks = factor_wide.columns.intersection(ret_wide.columns)

    fac = factor_wide.loc[common_dates, common_stocks]
    ret = ret_wide.loc[common_dates, common_stocks]

    ic_list = []
    for date in common_dates:
        f_vals = fac.loc[date].dropna()
        r_vals = ret.loc[date].dropna()
        common_idx = f_vals.index.intersection(r_vals.index)

        if len(common_idx) < min_stocks:
            ic_list.append(np.nan)
            continue

        f_cross = f_vals[common_idx]
        r_cross = r_vals[common_idx]

        if method == "pearson":
            corr, _ = stats.pearsonr(f_cross, r_cross)
        else:
            corr, _ = stats.spearmanr(f_cross, r_cross)

        ic_list.append(corr)

    return pd.Series(ic_list, index=common_dates, name=f"IC_{method}")


def _newey_west_se(x: np.ndarray, lag: int) -> float:
    """计算 Newey-West HAC 标准误（针对均值 mean(x)）。

    适用于 IC 序列：A 股 IC 常有 1-3 日正自相关，普通 t-stat 被高估。
    """
    n = len(x)
    if n < 2:
        return float("nan")
    mu = x.mean()
    e = x - mu
    gamma0 = float((e ** 2).mean())
    s2 = gamma0
    for h in range(1, min(lag, n - 1) + 1):
        gamma = float((e[h:] * e[:-h]).mean())
        w = 1.0 - h / (lag + 1.0)  # Bartlett 核
        s2 += 2.0 * w * gamma
    s2 = max(s2, 1e-12)
    return float(np.sqrt(s2 / n))


def ic_summary(
    ic_series: pd.Series,
    name: str = "Factor",
    nw_lag: int | None = None,
    fwd_days: int = 1,
    verbose: bool = True,
) -> dict:
    """
    打印并返回 IC 统计摘要

    关键指标:
        IC 均值       : 越大（绝对值）越好，一般 |IC| > 0.03 视为有效
        ICIR          : IC均值 / IC标准差，|ICIR| > 0.3 视为稳定
        IC>0 占比     : 对于正向因子 > 50% 为佳，对于反转因子 < 50%
        t 统计量      : 普通 t（不修正自相关）
        HAC t 统计量  : Newey-West 修正后的 t，A股 IC 自相关普遍存在，这个才是可信的那个

    **HAC lag 选择**（2026-04-17 修复）:
        - 前向收益窗口 fwd_days > 1 时，连续两天 IC 样本共享 fwd_days-1 天返回 →
          人为诱发 MA(fwd_days-1) 自相关。NW lag 必须 ≥ fwd_days-1。
        - nw_lag=None 时自动取 max(fwd_days-1, Andrews 1991 规则 floor(4*(n/100)^(2/9)))
        - 显式传入 nw_lag 覆盖自动；传入 fwd_days 让函数知道回报窗口长度。
    """
    ic_clean = ic_series.dropna()
    n = len(ic_clean)
    mean_ic = ic_clean.mean()
    std_ic = ic_clean.std()
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    pct_pos = (ic_clean > 0).mean()
    t_stat = mean_ic / (std_ic / np.sqrt(n)) if std_ic > 0 and n > 1 else np.nan

    # 自动选 NW lag：取 Andrews 1991 与 fwd_days-1 的较大者
    if nw_lag is None:
        andrews = int(np.floor(4 * (max(n, 1) / 100) ** (2 / 9))) if n > 0 else 1
        nw_lag = max(andrews, max(fwd_days - 1, 1))

    hac_se = _newey_west_se(ic_clean.values, lag=nw_lag) if n > nw_lag + 1 else float("nan")
    t_hac = mean_ic / hac_se if hac_se and hac_se == hac_se and hac_se > 0 else np.nan

    if verbose:
        print(f"【{name}】IC 统计摘要")
        print(f"  IC 均值       : {mean_ic:.4f}")
        print(f"  IC 标准差     : {std_ic:.4f}")
        print(f"  ICIR          : {icir:.4f}")
        print(f"  IC>0 占比     : {pct_pos:.2%}")
        print(f"  t 统计量      : {t_stat:.4f}")
        print(f"  HAC t (NW-{nw_lag}) : {t_hac:.4f}  (|t|>2 视为显著)")
        print()

    return {
        "name": name,
        "IC_mean": mean_ic,
        "IC_std": std_ic,
        "ICIR": icir,
        "pct_pos": pct_pos,
        "t_stat": t_stat,
        "t_stat_hac": t_hac,
        "nw_lag": nw_lag,
        "n": n,
    }


# ─────────────────────────────────────────────
# 分层回测
# ─────────────────────────────────────────────

def quintile_backtest(
    factor_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    n_groups: int = 5,
    long_short: str = "Q1_minus_Qn",
) -> tuple[pd.DataFrame, pd.Series]:
    """
    分层回测：按因子值等分为 n_groups 组，计算各组平均收益

    参数:
        factor_wide : 因子宽表 (date × symbol)
        ret_wide    : 收益率宽表 (date × symbol)
        n_groups    : 分组数，默认5（五分位）
        long_short  : 多空方向
            'Q1_minus_Qn' : Q1（因子最小）做多，Qn（因子最大）做空 → 反转因子
            'Qn_minus_Q1' : Qn 做多，Q1 做空 → 动量/正向因子

    返回:
        group_ret : DataFrame，行=日期，列=分组（Q1~Q5）
        ls_ret    : Series，多空组合日收益率
    """
    common_dates = factor_wide.index.intersection(ret_wide.index)
    common_stocks = factor_wide.columns.intersection(ret_wide.columns)

    fac = factor_wide.loc[common_dates, common_stocks]
    ret = ret_wide.loc[common_dates, common_stocks]

    group_rets_list = []

    for date in common_dates:
        f_vals = fac.loc[date].dropna()
        r_vals = ret.loc[date].dropna()
        common_idx = f_vals.index.intersection(r_vals.index)

        if len(common_idx) < n_groups * 5:
            group_rets_list.append([np.nan] * n_groups)
            continue

        f_cross = f_vals[common_idx]
        r_cross = r_vals[common_idx]

        labels = pd.qcut(f_cross, q=n_groups, labels=False, duplicates="drop")
        day_rets = [r_cross[labels == g].mean() for g in range(n_groups)]
        group_rets_list.append(day_rets)

    cols = [f"Q{i+1}" for i in range(n_groups)]
    group_ret = pd.DataFrame(group_rets_list, index=common_dates, columns=cols)

    if long_short == "Q1_minus_Qn":
        ls_ret = group_ret["Q1"] - group_ret[f"Q{n_groups}"]
    else:
        ls_ret = group_ret[f"Q{n_groups}"] - group_ret["Q1"]

    return group_ret, ls_ret


def factor_summary_table(
    factors: dict,
    ret_wide: pd.DataFrame,
    ic_method: str = "spearman",
) -> pd.DataFrame:
    """
    批量生成因子检验汇总表

    参数:
        factors  : {"因子名": factor_wide, ...}
        ret_wide : 收益率宽表

    返回:
        汇总 DataFrame
    """
    rows = []
    for name, fac in factors.items():
        ic_s = compute_ic_series(fac, ret_wide, method=ic_method)
        _, ls = quintile_backtest(fac, ret_wide)

        ic_c = ic_s.dropna()
        ls_c = ls.dropna()
        ann = ls_c.mean() * 252
        vol = ls_c.std() * np.sqrt(252)
        sr = ann / vol if vol > 0 else np.nan

        rows.append({
            "因子": name,
            f"IC均值({ic_method})": round(ic_c.mean(), 4),
            "ICIR": round(ic_c.mean() / ic_c.std(), 4) if ic_c.std() > 0 else np.nan,
            "IC>0占比": f"{(ic_c > 0).mean():.1%}",
            "多空年化": f"{ann:.2%}",
            "多空夏普": round(sr, 3),
        })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 因子中性化
# ─────────────────────────────────────────────

def neutralize_factor(
    factor_wide: pd.DataFrame,
    df_info: pd.DataFrame,
    n_sigma: float = 3.0,
) -> pd.DataFrame:
    """
    行业 + 市值中性化

    对每个截面日：
        1. 去极值（±n_sigma σ 截尾）
        2. 以行业哑变量 + 对数市值做 OLS，取残差

    参数:
        factor_wide : 因子宽表 (date × symbol)
        df_info     : 包含 trade_date, symbol, ind_code, mv_float 的长表
        n_sigma     : 去极值截尾倍数

    返回:
        neutral_wide : 中性化后的因子宽表
    """
    from numpy.linalg import lstsq

    info = df_info[["trade_date", "symbol", "ind_code", "mv_float"]].copy()
    info["log_mv"] = np.log(info["mv_float"].clip(lower=1))

    info_groups = info.groupby("trade_date")
    result_list = []

    for date in tqdm(factor_wide.index, desc="中性化", leave=False):
        f_row = factor_wide.loc[date].dropna()
        if f_row.empty:
            result_list.append(pd.Series(dtype=float, name=date))
            continue

        try:
            day_info = info_groups.get_group(date).set_index("symbol")
        except KeyError:
            result_list.append(pd.Series(dtype=float, name=date))
            continue

        common = f_row.index.intersection(day_info.index)
        if len(common) < 30:
            result_list.append(pd.Series(dtype=float, name=date))
            continue

        f_cross = winsorize(f_row[common], n_sigma=n_sigma)
        info_cross = day_info.loc[common]

        ind_dummies = pd.get_dummies(info_cross["ind_code"], drop_first=True).astype(float)
        X = pd.concat(
            [
                pd.Series(1, index=common, name="const"),
                info_cross["log_mv"],
                ind_dummies,
            ],
            axis=1,
        ).fillna(0).values

        y = f_cross.values
        try:
            coef, _, _, _ = lstsq(X, y, rcond=None)
            residual = y - X @ coef
        except Exception:
            residual = y

        result_list.append(pd.Series(residual, index=common, name=date))

    return pd.DataFrame(result_list)


def neutralize_factor_by_industry(
    factor_wide: pd.DataFrame,
    industry_df: pd.DataFrame,
    n_sigma: float = 3.0,
    min_stocks: int = 30,
    show_progress: bool = False,
) -> pd.DataFrame:
    """
    行业中性化（不含市值中性化）。

    对每个截面日：
        1. 去极值（±n_sigma σ 截尾）
        2. 对每个行业做组内去均值

    参数:
        factor_wide  : 因子宽表 (date × symbol)
        industry_df  : 长表，至少包含 symbol, industry_code
        n_sigma      : 去极值截尾倍数
        min_stocks   : 每日最小有效股票数

    返回:
        neutral_wide : 行业中性化后的因子宽表
    """
    required = {"symbol", "industry_code"}
    missing = required - set(industry_df.columns)
    if missing:
        raise ValueError(f"industry_df 缺少必要列: {sorted(missing)}")

    ind_map = (
        industry_df[["symbol", "industry_code"]]
        .dropna(subset=["symbol", "industry_code"])
        .drop_duplicates(subset="symbol", keep="last")
        .set_index("symbol")["industry_code"]
    )

    result_list = []
    iterator = factor_wide.index
    if show_progress:
        iterator = tqdm(iterator, desc="行业中性化", leave=False)

    for date in iterator:
        f_row = factor_wide.loc[date].dropna()
        if f_row.empty:
            result_list.append(pd.Series(dtype=float, name=date))
            continue

        common = f_row.index.intersection(ind_map.index)
        if len(common) < min_stocks:
            result_list.append(pd.Series(dtype=float, name=date))
            continue

        f_cross = winsorize(f_row[common], n_sigma=n_sigma)
        ind_cross = ind_map.loc[common]
        neutral = f_cross.groupby(ind_cross).transform(lambda s: s - s.mean())
        result_list.append(pd.Series(neutral, index=common, name=date))

    return pd.DataFrame(result_list)


# ─────────────────────────────────────────────
# 行业中性化（快速向量化版）
# ─────────────────────────────────────────────

def industry_neutralize_fast(
    factor_wide: pd.DataFrame,
    industry_series: pd.Series,
) -> pd.DataFrame:
    """
    行业中性化（快速版）：截面去均值（行业内 demean）。

    比 OLS 更快，效果接近：每只股票的因子值减去其所属行业的当日均值。
    单行业内股票数 < 2 时该行业保持原值（无法 demean）。

    参数:
        factor_wide      : 因子宽表（日期 × 股票），index 为 DatetimeIndex
        industry_series  : pd.Series，index=symbol，value=行业名

    返回:
        中性化后的因子宽表，形状与 factor_wide 相同
    """
    result = factor_wide.copy()
    ind_clean = industry_series.dropna()
    industries = ind_clean.unique()

    for ind in industries:
        # 取属于该行业、且在因子宽表中存在的列
        syms_in_ind = ind_clean[ind_clean == ind].index
        cols = [c for c in syms_in_ind if c in factor_wide.columns]
        if len(cols) < 2:
            # 只有 0 或 1 只股票，无法做行业内 demean，保持原值
            continue
        ind_data = factor_wide[cols]
        # axis=1：每个日期（行）计算该行业所有股票的均值，再逐列减去
        ind_mean = ind_data.mean(axis=1)
        result[cols] = ind_data.sub(ind_mean, axis=0)

    return result


def industry_neutralize(
    factor_wide: pd.DataFrame,
    industry_map: dict,
) -> pd.DataFrame:
    """
    行业中性化（OLS 回归残差法）。

    对每个截面日期 t：
        factor_t = alpha + sum(beta_k * I_k) + residual_t
        residual_t 即为中性化后的因子值

    注意：此函数逐日循环，数据量大时较慢。
    日常使用推荐更快的 industry_neutralize_fast。

    参数:
        factor_wide  : 因子宽表（日期 × 股票）
        industry_map : {symbol: industry_name}，行业分类字典

    返回:
        同形状 DataFrame，行业中性化后的因子值
    """
    import numpy as np
    from numpy.linalg import lstsq

    industry_series = pd.Series(industry_map)
    ind_list = sorted(set(industry_map.values()))

    result = factor_wide.copy() * np.nan

    for date in factor_wide.index:
        row = factor_wide.loc[date].dropna()
        if len(row) < 30:
            continue

        symbols = row.index.tolist()

        # 构建行业虚拟变量矩阵（带截距通过 lstsq fit_intercept=True 等效）
        X = np.zeros((len(symbols), len(ind_list)))
        for i, sym in enumerate(symbols):
            ind = industry_series.get(sym)
            if ind and ind in ind_list:
                j = ind_list.index(ind)
                X[i, j] = 1.0

        # 去掉全零列（该行业当日无股票）
        valid_cols = X.sum(0) > 0
        X = X[:, valid_cols]

        if X.shape[1] == 0:
            result.loc[date, symbols] = row.values
            continue

        # 加截距列
        X_with_intercept = np.hstack([np.ones((len(symbols), 1)), X])
        y = row.values

        try:
            coef, _, _, _ = lstsq(X_with_intercept, y, rcond=None)
            residuals = y - X_with_intercept @ coef
            result.loc[date, symbols] = residuals
        except Exception:
            result.loc[date, symbols] = row.values

    return result


# ─────────────────────────────────────────────
# IC 加权合成
# ─────────────────────────────────────────────

def ic_weighted_period_composite(
    factor_dict: dict,
    ic_series_dict: dict,
    rolling_window: int = 60,
    shift_days: int | None = None,
) -> pd.DataFrame:
    """
    IC 加权合成同一因子的多个回看周期（滚动窗口内的 IC 均值绝对值作为权重）

    **前视保护**（2026-04-17 修复）:
        IC(t) 用的是 t+1..t+N 的前向收益；直接用 rolling_ic.loc[t] 做
        当日因子组合 → 权重吸收了 t..t+N 的未来信息。必须在权重上 shift。

        shift_days 默认取 max(periods) + 1，确保 t 日的权重只用到
        t-(N+1) 及以前的 IC 值（对应 return 窗口 ≤ t-1 结束）。

    与 multi_factor.ic_weighted_composite 的区别：
    - 本函数合成同一因子的不同周期（如动量 5/10/20/60/120 日），需外部传入 IC 序列
    - multi_factor.ic_weighted_composite 合成不同因子，内部自行计算 IC

    参数:
        factor_dict    : {周期N: factor_wide, ...}  N 为前向收益天数
        ic_series_dict : {周期N: ic_series, ...}，各周期的 IC 时序
        rolling_window : 计算权重的滚动窗口（默认60日）
        shift_days     : 权重 shift 天数；None 则自动取 max(periods)+1

    返回:
        factor_ic_weighted : 加权合成后的因子宽表
    """
    periods = list(factor_dict.keys())

    ic_df = pd.DataFrame({n: ic_series_dict[n] for n in periods})
    rolling_ic = ic_df.rolling(rolling_window, min_periods=20).mean()

    def _weights(row):
        abs_ic = row.abs()
        total = abs_ic.sum()
        if total == 0 or np.isnan(total):
            return pd.Series([1 / len(periods)] * len(periods), index=row.index)
        return abs_ic / total

    weight_df = rolling_ic.apply(_weights, axis=1)

    # 前视保护：IC(t) 基于 t+1..t+N 前向收益；权重必须 shift 以避免泄漏
    if shift_days is None:
        try:
            shift_days = max(int(p) for p in periods) + 1
        except (TypeError, ValueError):
            shift_days = 0  # periods 不是数字，放弃自动 shift，交给调用者
            import warnings
            warnings.warn(
                "periods 不是数字，无法自动 shift 权重以避免前视；请显式传入 shift_days",
                RuntimeWarning,
            )
    if shift_days > 0:
        weight_df = weight_df.shift(shift_days)

    # 以第一个因子的形状为基准
    base_fac = factor_dict[periods[0]]
    result_vals = np.full((len(base_fac.index), len(base_fac.columns)), np.nan)

    for i, date in enumerate(base_fac.index):
        if date not in weight_df.index:
            continue
        w = weight_df.loc[date]
        weighted = np.zeros(base_fac.shape[1])
        weight_sum = np.zeros(base_fac.shape[1])
        for n in periods:
            fac_n = factor_dict[n]
            if date not in fac_n.index:
                continue
            vals = fac_n.loc[date].reindex(base_fac.columns).values
            mask = ~np.isnan(vals)
            weighted[mask] += w[n] * vals[mask]
            weight_sum[mask] += w[n]
        result_vals[i] = np.where(weight_sum > 0, weighted / weight_sum, np.nan)

    return pd.DataFrame(result_vals, index=base_fac.index, columns=base_fac.columns)


# ─────────────────────────────────────────────
# 因子衰减分析
# ─────────────────────────────────────────────

def factor_decay_analysis(
    factor_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
    max_lag: int = 20,
    smooth: bool = True,
) -> dict:
    """
    因子衰减半衰期分析。

    对每个 lag = 1..max_lag 计算 IC，拟合指数衰减曲线求半衰期。

    参数:
        factor_wide : 因子宽表（日期 × 股票）
        ret_wide    : 收益率宽表（日期 × 股票）
        max_lag     : 最大预测期（天），默认 20
        smooth      : True 时对 IC 曲线做滑动平均（窗口 3）再拟合，减少噪音

    返回:
        dict，包含以下字段：
            ic_by_lag              : {1: 0.03, 2: 0.025, ...}，每个 lag 的平均 IC
            half_life_days         : 半衰期（天），None 表示无法拟合
            decay_rate             : 指数衰减率 λ
            ic_0                   : 拟合的初始 IC 值
            recommended_rebalance_freq : 根据半衰期推荐的调仓频率
            fit_quality            : R² 拟合质量
    """
    from scipy.optimize import curve_fit

    lags = list(range(1, max_lag + 1))

    # Step 1：对每个 lag 计算平均 IC
    ic_by_lag = {}
    for lag in lags:
        fwd_ret = ret_wide.shift(-lag)
        ic_s = compute_ic_series(factor_wide, fwd_ret)
        ic_by_lag[lag] = ic_s.mean()

    ic_values = np.array([ic_by_lag[lag] for lag in lags])

    # Step 2：可选滑动平均平滑 IC 曲线（窗口 3）
    if smooth and len(ic_values) >= 3:
        ic_smoothed = (
            pd.Series(ic_values)
            .rolling(window=3, center=True, min_periods=1)
            .mean()
            .values
        )
    else:
        ic_smoothed = ic_values.copy()

    # Step 3：用绝对值拟合指数衰减 |IC(t)| = ic0 * exp(-λ * t)
    abs_ic = np.abs(ic_smoothed)
    lags_arr = np.array(lags, dtype=float)

    def _exp_decay(t, ic0, lam):
        return ic0 * np.exp(-lam * t)

    half_life_days = None
    decay_rate = None
    ic_0 = None
    fit_quality = None
    recommended_rebalance_freq = "monthly"  # 默认降级值

    try:
        # 初始猜测：ic0 为第一个 lag 的 |IC|，λ 为 0.1
        p0 = [abs_ic[0] if abs_ic[0] > 0 else 0.01, 0.1]
        popt, _ = curve_fit(
            _exp_decay,
            lags_arr,
            abs_ic,
            p0=p0,
            maxfev=5000,
            bounds=([0, 1e-6], [np.inf, np.inf]),
        )
        ic0_fit, lam_fit = popt

        # 计算 R²
        fitted = _exp_decay(lags_arr, ic0_fit, lam_fit)
        ss_res = np.sum((abs_ic - fitted) ** 2)
        ss_tot = np.sum((abs_ic - abs_ic.mean()) ** 2)
        r2 = 1 - ss_res / ss_tot if ss_tot > 0 else np.nan

        half_life_days = np.log(2) / lam_fit
        decay_rate = float(lam_fit)
        ic_0 = float(ic0_fit)
        fit_quality = float(r2)

        # Step 5：根据半衰期推荐调仓频率
        if half_life_days < 5:
            recommended_rebalance_freq = "daily"
        elif half_life_days < 15:
            recommended_rebalance_freq = "weekly"
        elif half_life_days < 40:
            recommended_rebalance_freq = "monthly"
        else:
            recommended_rebalance_freq = "quarterly"

    except Exception:
        # curve_fit 失败：半衰期无法估计，保持默认降级值
        pass

    return {
        "ic_by_lag": ic_by_lag,
        "half_life_days": half_life_days,
        "decay_rate": decay_rate,
        "ic_0": ic_0,
        "recommended_rebalance_freq": recommended_rebalance_freq,
        "fit_quality": fit_quality,
    }


def batch_decay_analysis(
    factors_dict: dict,
    ret_wide: pd.DataFrame,
    max_lag: int = 20,
) -> pd.DataFrame:
    """
    批量因子衰减分析汇总表。

    对多个因子同时调用 factor_decay_analysis，返回对比 DataFrame。

    参数:
        factors_dict : {"因子名": factor_wide, ...}
        ret_wide     : 收益率宽表（日期 × 股票）
        max_lag      : 最大预测期（天），传入各子调用

    返回:
        汇总 DataFrame，每行一个因子，列为：
            因子、半衰期(天)、衰减率λ、初始IC、推荐调仓频率、拟合R²
    """
    rows = []
    for name, fac in factors_dict.items():
        result = factor_decay_analysis(fac, ret_wide, max_lag=max_lag, smooth=True)
        rows.append({
            "因子": name,
            "半衰期(天)": (
                round(result["half_life_days"], 2)
                if result["half_life_days"] is not None
                else None
            ),
            "衰减率λ": (
                round(result["decay_rate"], 4)
                if result["decay_rate"] is not None
                else None
            ),
            "初始IC": (
                round(result["ic_0"], 4)
                if result["ic_0"] is not None
                else None
            ),
            "推荐调仓频率": result["recommended_rebalance_freq"],
            "拟合R²": (
                round(result["fit_quality"], 4)
                if result["fit_quality"] is not None
                else None
            ),
        })
    return pd.DataFrame(rows)


# ─────────────────────────────────────────────
# 因子相关性分析
# ─────────────────────────────────────────────

def factor_correlation_matrix(
    factor_df: pd.DataFrame,
) -> tuple[pd.DataFrame, list[tuple]]:
    """
    计算因子间相关性矩阵，并标记高相关因子对。

    参数:
        factor_df : 宽表 DataFrame，列为因子名，行为 (date, symbol) 或纯 symbol
                    每列代表一个因子的值

    返回:
        (corr_matrix_df, high_corr_pairs)
        - corr_matrix_df : 因子 × 因子 的 Pearson 相关系数矩阵
        - high_corr_pairs : 高相关因子对列表，每个元素为
          (factor_a, factor_b, corr_value)，筛选条件 |corr| > 0.7
          只包含上三角（避免重复），不含对角线
    """
    corr_matrix = factor_df.corr()

    # 提取上三角中 |corr| > 0.7 的因子对
    high_corr_pairs = []
    factors = corr_matrix.columns.tolist()
    n = len(factors)
    for i in range(n):
        for j in range(i + 1, n):
            corr_val = corr_matrix.iloc[i, j]
            if abs(corr_val) > 0.7:
                high_corr_pairs.append((factors[i], factors[j], round(corr_val, 4)))

    return corr_matrix, high_corr_pairs


def plot_factor_correlation(
    corr_df: pd.DataFrame,
    output_path: str = None,
) -> None:
    """
    绘制因子相关性热力图。

    参数:
        corr_df     : 因子 × 因子 的相关系数矩阵（来自 factor_correlation_matrix）
        output_path : 保存路径（如 'corr_heatmap.png'）；为 None 则直接 plt.show()
    """
    import matplotlib.pyplot as plt

    try:
        import seaborn as sns
        has_seaborn = True
    except ImportError:
        has_seaborn = False

    fig, ax = plt.subplots(figsize=(max(8, len(corr_df.columns)), max(6, len(corr_df.columns) * 0.8)))

    if has_seaborn:
        sns.heatmap(
            corr_df,
            annot=True,
            fmt=".2f",
            cmap="RdBu_r",
            center=0,
            vmin=-1,
            vmax=1,
            square=True,
            linewidths=0.5,
            ax=ax,
        )
    else:
        # 无 seaborn 时用 matplotlib 的 imshow 降级
        im = ax.imshow(corr_df.values, cmap="RdBu_r", vmin=-1, vmax=1, aspect="auto")
        ax.set_xticks(range(len(corr_df.columns)))
        ax.set_yticks(range(len(corr_df.index)))
        ax.set_xticklabels(corr_df.columns, rotation=45, ha="right")
        ax.set_yticklabels(corr_df.index)
        # 标注数值
        for i in range(len(corr_df.index)):
            for j in range(len(corr_df.columns)):
                ax.text(j, i, f"{corr_df.iloc[i, j]:.2f}",
                        ha="center", va="center", fontsize=8)
        fig.colorbar(im, ax=ax, shrink=0.8)

    ax.set_title("因子相关性矩阵")
    plt.tight_layout()

    if output_path:
        fig.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"热力图已保存至 {output_path}")
        plt.close(fig)
    else:
        plt.show()


# ─────────────────────────────────────────────
# 入口验证
# ─────────────────────────────────────────────

if __name__ == "__main__":
    np.random.seed(42)
    n_dates, n_stocks = 120, 50
    dates = pd.date_range("2024-01-01", periods=n_dates, freq="B")
    stocks = [f"S{i:03d}" for i in range(n_stocks)]

    # 构造一个与收益率有相关性、且存在衰减的因子
    base_signal = pd.DataFrame(
        np.random.randn(n_dates, n_stocks), index=dates, columns=stocks
    )
    noise = pd.DataFrame(
        np.random.randn(n_dates, n_stocks) * 2, index=dates, columns=stocks
    )
    ret_wide = base_signal.shift(1) * 0.02 + noise * 0.01
    factor_wide = base_signal + np.random.randn(n_dates, n_stocks) * 0.5

    print("=== 单因子衰减分析 ===")
    result = factor_decay_analysis(factor_wide, ret_wide, max_lag=10, smooth=True)
    print(f"IC by lag (lag1~5): { {k: round(v, 4) for k, v in list(result['ic_by_lag'].items())[:5]} }")
    print(f"半衰期       : {result['half_life_days']}")
    print(f"衰减率 λ     : {result['decay_rate']}")
    print(f"初始 IC      : {result['ic_0']}")
    print(f"推荐调仓频率 : {result['recommended_rebalance_freq']}")
    print(f"拟合 R²      : {result['fit_quality']}")

    print("\n=== 批量因子衰减分析 ===")
    factors_dict = {
        "momentum": base_signal + np.random.randn(n_dates, n_stocks) * 0.3,
        "reversal": -base_signal + np.random.randn(n_dates, n_stocks) * 0.5,
        "noise_factor": pd.DataFrame(
            np.random.randn(n_dates, n_stocks), index=dates, columns=stocks
        ),
    }
    summary = batch_decay_analysis(factors_dict, ret_wide, max_lag=10)
    print(summary.to_string(index=False))
    print("\n✅ factor_decay_analysis 验证通过")

    # === 因子相关性矩阵 ===
    print("\n=== 因子相关性矩阵 ===")
    # 构造多因子宽表（列=因子名，行=样本）
    multi_factor_df = pd.DataFrame({
        "momentum": np.random.randn(200),
        "reversal": np.random.randn(200),
        "vol": np.random.randn(200),
        "correlated_mom": np.random.randn(200) * 0.3,
    })
    # 让 correlated_mom 与 momentum 高度相关
    multi_factor_df["correlated_mom"] += multi_factor_df["momentum"] * 0.9

    corr_mat, high_pairs = factor_correlation_matrix(multi_factor_df)
    print("相关系数矩阵:")
    print(corr_mat.round(3))
    print(f"高相关因子对 (|corr| > 0.7): {high_pairs}")
    assert isinstance(corr_mat, pd.DataFrame), "corr_matrix 应为 DataFrame"
    assert len(high_pairs) > 0, "应检测到至少一对高相关因子"
    print("✅ factor_correlation_matrix 验证通过")
