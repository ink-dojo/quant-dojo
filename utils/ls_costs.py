"""
L/S 组合的交易摩擦调整工具 — 融券成本 / 双边交易成本 / 换手率。

背景 (2026-04-17 研究闭环发现):
  现有 `quintile_backtest` 报告的 long-short sharpe 是学术 gross 值,
  没扣融券成本 (A 股典型 8-10% 年化) 和双边交易成本。对 A 股 factor
  sharpe 虚高 0.5+ 很常见, 把策略从"看似过门"推到"真实过门"就是这层。

核心函数:
  - `quintile_weights`        : 从 ranked factor 反推出逐日 Q1..Qn 权重
  - `leg_turnover`            : 计算单腿日换手 (one-way, 0..1)
  - `tradable_ls_pnl`         : 扣融券 + 双边 txn cost 后的 L/S 日收益

参考:
  - A 股 2024 融券利率 ~8-9% 年化 (中证金融融券费率, 中型券商)
  - 中国证券业协会公布 2023 融资融券利率 RMB 8.6% vs 3-5 bp 日
  - Asness, Frazzini, Pedersen (2020) "Fact, Fiction, and Value Investing"
    指出 L/S 论文 gross sharpe 需扣 2-4% 年化成本才接近 tradeable
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def quintile_weights(
    factor_wide: pd.DataFrame,
    n_groups: int = 5,
) -> list[pd.DataFrame]:
    """
    把 factor_wide 按日做 qcut, 返回 n_groups 个等权权重 DataFrame。

    每个 DataFrame 形状同 factor_wide (date × symbol),
    bucket 内股票权重 = 1/n_in_bucket (等权), 其他股票为 0。
    当日无法分组的行 (样本<n_groups*5 或 全 NaN) 填 0, 记该日换手为 0。

    参数:
        factor_wide : (date × symbol) 因子宽表, 越大越多头
        n_groups    : 分组数, 默认 5 (五分位)

    返回:
        weights_list : 长度为 n_groups 的列表, weights_list[0]=Q1, [-1]=Qn
    """
    n = factor_wide.shape[1]
    min_per_bucket = 5
    weights = [pd.DataFrame(0.0, index=factor_wide.index, columns=factor_wide.columns)
               for _ in range(n_groups)]

    for date in factor_wide.index:
        f_row = factor_wide.loc[date].dropna()
        if len(f_row) < n_groups * min_per_bucket:
            continue
        try:
            labels = pd.qcut(f_row, q=n_groups, labels=False, duplicates="drop")
        except ValueError:
            continue
        for g in range(n_groups):
            mask = labels == g
            if not mask.any():
                continue
            syms = f_row.index[mask]
            w = 1.0 / len(syms)
            weights[g].loc[date, syms] = w
    return weights


def leg_turnover(weight_wide: pd.DataFrame) -> pd.Series:
    """
    单腿日换手率 (one-way) = 0.5 * sum_i |w_t[i] - w_{t-1}[i]|。

    首日换手 = sum_i |w_0[i]| (建仓)。空仓日换手 = 0。
    """
    w = weight_wide.fillna(0)
    dw = w.diff().abs()
    dw.iloc[0] = w.iloc[0].abs()
    return 0.5 * dw.sum(axis=1)


def leg_return(
    weight_wide: pd.DataFrame,
    ret_wide: pd.DataFrame,
) -> pd.Series:
    """
    权重 × 次日收益, 对齐后每日求和。shift(1) 已由调用方在 ret_wide 上处理。

    注意:
      - weight_wide 索引应与 ret_wide 索引对齐到同一交易日
      - ret_wide 应是 "持有到次日" 的收益 (可用 price.pct_change() 直接传)
        但此时权重在 t 日决定, 收益在 t 日体现 (shift(-1) 前视) —
        调用方务必保证 weight 已 shift(1), 或 ret 已 shift(-1) 对齐
    """
    common_dates = weight_wide.index.intersection(ret_wide.index)
    common_syms = weight_wide.columns.intersection(ret_wide.columns)
    w = weight_wide.loc[common_dates, common_syms].fillna(0)
    r = ret_wide.loc[common_dates, common_syms].fillna(0)
    return (w * r).sum(axis=1)


def tradable_ls_pnl(
    ret_long: pd.Series,
    ret_short: pd.Series,
    turn_long: pd.Series,
    turn_short: pd.Series,
    borrow_cost_annual: float = 0.08,
    txn_cost_per_side: float = 0.0015,
    days_per_year: int = 252,
) -> pd.Series:
    """
    真实可交易的 L/S 日收益 = 多 - 空 - 融券日成本 - 两腿换手成本。

    公式:
      净收益_t = (ret_long_t - ret_short_t)
                - txn_cost * (turn_long_t + turn_short_t)
                - borrow_daily

    参数:
        ret_long, ret_short   : 两腿日 gross 收益 (Series, 同 index)
        turn_long, turn_short : 两腿日 one-way 换手
        borrow_cost_annual    : 融券年化成本, 默认 8% (A 股典型)
        txn_cost_per_side     : 单边交易成本, 默认 0.15% (=15 bps)
        days_per_year         : 计日常化的年化天数, 默认 252

    返回:
        净 L/S 日收益 Series
    """
    idx = ret_long.index.intersection(ret_short.index)
    rl = ret_long.loc[idx].fillna(0)
    rs = ret_short.loc[idx].fillna(0)
    tl = turn_long.reindex(idx).fillna(0)
    ts = turn_short.reindex(idx).fillna(0)
    borrow_daily = borrow_cost_annual / days_per_year
    txn_drag = txn_cost_per_side * (tl + ts)
    return (rl - rs) - txn_drag - borrow_daily


if __name__ == "__main__":
    # 最小自测: 构造 60 日 × 40 股票数据, 跑 quintile_weights → leg_return → tradable_ls_pnl
    rng = np.random.default_rng(42)
    n_d, n_s = 60, 40
    dates = pd.bdate_range("2024-01-01", periods=n_d)
    syms = [f"S{i:03d}" for i in range(n_s)]
    # factor ~ lagged return (反转: 过去跌多的 → Q5 多头信号)
    price = pd.DataFrame(
        100 * np.exp(np.cumsum(rng.normal(0, 0.02, (n_d, n_s)), axis=0)),
        index=dates, columns=syms,
    )
    factor = -price.pct_change(20).shift(1)  # 反转: 过去 20 日跌多 = 强信号

    weights = quintile_weights(factor, n_groups=5)
    assert len(weights) == 5
    # Q1 和 Q5 权重不全为 0
    assert weights[0].sum().sum() > 0
    assert weights[-1].sum().sum() > 0

    tl = leg_turnover(weights[-1])
    ts = leg_turnover(weights[0])
    assert (tl >= 0).all() and (tl <= 1).all(), "换手应在 [0,1]"

    ret_1d = price.pct_change().shift(-1)  # 当日权重 × 次日收益 (防前视)
    rl = leg_return(weights[-1], ret_1d)
    rs = leg_return(weights[0], ret_1d)
    net = tradable_ls_pnl(rl, rs, tl, ts, borrow_cost_annual=0.08, txn_cost_per_side=0.0015)

    print(f"Q5 mean daily ret: {rl.mean():.6f}")
    print(f"Q1 mean daily ret: {rs.mean():.6f}")
    print(f"Gross LS mean daily: {(rl - rs).mean():.6f}")
    print(f"Turnover Q5 mean: {tl.mean():.4f}")
    print(f"Turnover Q1 mean: {ts.mean():.4f}")
    print(f"Net LS mean daily (after costs): {net.mean():.6f}")
    print(f"Borrow drag: {0.08/252:.6f}")
    print(f"Txn drag mean: {0.0015*(tl+ts).mean():.6f}")
    print("\n✅ ls_costs 自测通过")
