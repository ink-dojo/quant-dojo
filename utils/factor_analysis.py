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


def ic_summary(ic_series: pd.Series, name: str = "Factor") -> dict:
    """
    打印并返回 IC 统计摘要

    关键指标:
        IC 均值   : 越大（绝对值）越好，一般 |IC| > 0.03 视为有效
        ICIR      : IC均值 / IC标准差，|ICIR| > 0.3 视为稳定
        IC>0 占比 : 对于正向因子 > 50% 为佳，对于反转因子 < 50%
        t 统计量  : |t| > 2 则 IC 统计显著
    """
    ic_clean = ic_series.dropna()
    mean_ic = ic_clean.mean()
    std_ic = ic_clean.std()
    icir = mean_ic / std_ic if std_ic > 0 else np.nan
    pct_pos = (ic_clean > 0).mean()
    t_stat = mean_ic / (std_ic / np.sqrt(len(ic_clean)))

    print(f"【{name}】IC 统计摘要")
    print(f"  IC 均值    : {mean_ic:.4f}")
    print(f"  IC 标准差  : {std_ic:.4f}")
    print(f"  ICIR       : {icir:.4f}")
    print(f"  IC>0 占比  : {pct_pos:.2%}")
    print(f"  t 统计量   : {t_stat:.4f}  (|t|>2 视为显著)")
    print()

    return {
        "name": name,
        "IC_mean": mean_ic,
        "IC_std": std_ic,
        "ICIR": icir,
        "pct_pos": pct_pos,
        "t_stat": t_stat,
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


# ─────────────────────────────────────────────
# IC 加权合成
# ─────────────────────────────────────────────

def ic_weighted_period_composite(
    factor_dict: dict,
    ic_series_dict: dict,
    rolling_window: int = 60,
) -> pd.DataFrame:
    """
    IC 加权合成同一因子的多个回看周期（滚动窗口内的 IC 均值绝对值作为权重）

    与 multi_factor.ic_weighted_composite 的区别：
    - 本函数合成同一因子的不同周期（如动量 5/10/20/60/120 日），需外部传入 IC 序列
    - multi_factor.ic_weighted_composite 合成不同因子，内部自行计算 IC

    参数:
        factor_dict    : {周期N: factor_wide, ...}
        ic_series_dict : {周期N: ic_series, ...}，各周期的 IC 时序
        rolling_window : 计算权重的滚动窗口（默认60日）

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
