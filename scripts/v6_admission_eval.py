"""
v6 策略准入评估 — lag1 诚实基线 vs 乐观模式

v6 因子集（FM 双验证通过）：
  team_coin(30%), low_vol_20d(25%), cgo_simple(20%),
  enhanced_mom_60(15%), bp(10%)

择时：RSRS + LLT + 高阶矩 多数投票（≥2/3 看多才持仓）

用法：
  python scripts/v6_admission_eval.py                  # 默认 honest_baseline
  python scripts/v6_admission_eval.py --mode optimistic
  python scripts/v6_admission_eval.py --n-stocks 50 --cost 0.002
"""
import argparse
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, calmar_ratio,
)
from utils.factor_analysis import compute_ic_series, ic_summary
from utils.tradability_filter import apply_tradability_filter, cap_weights
from utils.market_regime import (
    rsrs_regime_mask, llt_timing, higher_moment_timing,
)
from utils.stop_loss import per_stock_stop
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)

# ══════════════════════════════════════════════════════════════
# 常量
# ══════════════════════════════════════════════════════════════
WARMUP_START = "2013-01-01"
IS_START = "2015-01-01"
IS_END = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END = "2025-12-31"

# v6 因子权重（基于 IS 期间 ICIR，FM 显著性加权后归一化）
V6_WEIGHTS = {
    "team_coin": 0.30,
    "low_vol_20d": 0.25,
    "cgo_simple": 0.20,
    "enhanced_mom_60": 0.15,
    "bp": 0.10,
}

# 准入门槛
ADMISSION_THRESHOLDS = {
    "annual_return": 0.15,
    "sharpe_ratio": 0.80,
    "max_drawdown": 0.30,   # 绝对值
    "backtest_years": 3.0,
}


# ══════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════
def load_data(oos_end: str = OOS_END):
    """加载价格、指数、PB 数据"""
    print("[1/6] 加载数据...")
    t0 = time.time()

    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, oos_end, field="close")

    hs300_full = get_index_history(
        symbol="sh000300", start=WARMUP_START, end=oos_end
    )
    hs300 = hs300_full["close"]

    # 对齐交易日
    common = price.index.intersection(hs300.index)
    price = price.loc[common]
    hs300_full = hs300_full.loc[common]
    hs300 = hs300.loc[common]

    # 去掉交易日太少的股票
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]

    # PB 从缓存读
    cache_dir = Path(__file__).parent.parent / "data" / "cache"
    pb = pd.read_parquet(cache_dir / "pb_wide.parquet")
    pb = pb.reindex(index=price.index, columns=valid)

    stock_count = len(valid)
    print(f"  股票: {stock_count} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")
    return price, hs300_full, hs300, pb, stock_count


# ══════════════════════════════════════════════════════════════
# 因子构建
# ══════════════════════════════════════════════════════════════
def build_v6_factors(price: pd.DataFrame, pb: pd.DataFrame) -> dict:
    """构建 v6 的 5 个因子"""
    print("[2/6] 构建 v6 因子...")
    factors = {
        "team_coin": _team_coin(price),
        "low_vol_20d": _low_vol_20d(price),
        "cgo_simple": -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp": bp_factor(pb).reindex_like(price),
    }
    # 数据量检查
    for name, fac in factors.items():
        valid_pct = fac.notna().mean().mean()
        print(f"  {name:<20} 有效率: {valid_pct:.1%}")
    return factors


# ══════════════════════════════════════════════════════════════
# 择时：多数投票
# ══════════════════════════════════════════════════════════════
def build_majority_vote_regime(hs300_full: pd.DataFrame,
                               hs300_close: pd.Series) -> pd.Series:
    """
    三指标多数投票择时：RSRS + LLT + 高阶矩。
    ≥2/3 看多 → True，否则 False。
    """
    print("[3/6] 择时信号（多数投票）...")

    rsrs = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])
    llt = llt_timing(hs300_close)
    hm = higher_moment_timing(hs300_close, order=5)

    # 对齐
    common = rsrs.index.intersection(llt.index).intersection(hm.index)
    rsrs, llt, hm = rsrs.loc[common], llt.loc[common], hm.loc[common]

    # 多数投票：≥2 看多
    vote = rsrs.astype(int) + llt.astype(int) + hm.astype(int)
    majority = vote >= 2
    majority.name = "majority_bullish"

    bull_pct = majority.mean()
    print(f"  RSRS 看多: {rsrs.mean():.0%} | LLT: {llt.mean():.0%} | "
          f"高阶矩: {hm.mean():.0%}")
    print(f"  多数投票看多: {bull_pct:.0%} | 看空: {1-bull_pct:.0%}")

    return majority


# ══════════════════════════════════════════════════════════════
# 回测核心
# ══════════════════════════════════════════════════════════════
def zscore_cross(df: pd.DataFrame) -> pd.DataFrame:
    """截面 z-score 标准化"""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)


def run_backtest(price_wide, factor_dict, weights, n_stocks=30,
                 cost=0.003, mask=None, max_weight=0.1,
                 regime_mask=None, regime_scale=0.0,
                 lag1=True, stop_loss_threshold=None,
                 rebalance_freq="monthly"):
    """
    多因子回测（支持月频/双周换仓）。

    参数:
        price_wide: 价格宽表
        factor_dict: {因子名: 因子 DataFrame}
        weights: {因子名: 权重}
        n_stocks: 持仓数
        cost: 每次换仓双边成本
        mask: 可交易性 bool mask
        max_weight: 单票最大权重
        regime_mask: 市场状态 mask（True=看多）
        regime_scale: 看空时的仓位比例（0.0=清仓，0.5=半仓，1.0=满仓）
        lag1: 是否延迟 1 天使用信号（诚实基线）
        stop_loss_threshold: 个股止损阈值（如 -0.10），None 表示不启用
        rebalance_freq: 换仓频率，"monthly"（默认）或 "biweekly"

    返回:
        pd.Series: 日收益率
    """
    dr = price_wide.pct_change()

    # 归一化权重
    total_w = sum(weights.values())
    norm_w = {k: v / total_w for k, v in weights.items()}

    # 合成因子
    composite = None
    for name, w in norm_w.items():
        if name not in factor_dict:
            continue
        z = zscore_cross(factor_dict[name])
        if composite is None:
            composite = z * w
        else:
            composite = composite.add(z * w, fill_value=0)

    if composite is None:
        return pd.Series(dtype=float)

    # 可交易性过滤
    if mask is not None:
        composite = composite.where(mask.reindex_like(composite))

    # lag1：信号延迟一天，避免当日偷看
    if lag1:
        composite = composite.shift(1)
        if regime_mask is not None:
            regime_mask = regime_mask.shift(1).fillna(True)

    # 换仓日期（月频 or 双周）
    _freq_map = {"monthly": "MS", "biweekly": "2W-MON"}
    _resample_key = _freq_map.get(rebalance_freq, "MS")
    rebal_dates = price_wide.resample(_resample_key).first().index
    rebal_dates = [d for d in rebal_dates if d in composite.index]

    portfolio_returns = []
    prev_picks = set()

    for i, date in enumerate(rebal_dates):
        # 择时过滤
        bearish = (regime_mask is not None
                   and date in regime_mask.index
                   and not regime_mask.loc[date])

        if i + 1 < len(rebal_dates):
            next_date = rebal_dates[i + 1]
        else:
            next_date = price_wide.index[-1]

        if bearish and regime_scale == 0.0:
            # 完全清仓：持现金
            zero_ret = pd.Series(0.0, index=dr.loc[date:next_date].index[1:])
            if prev_picks and len(zero_ret) > 0:
                zero_ret.iloc[0] -= cost  # 清仓成本
            prev_picks = set()
            portfolio_returns.append(zero_ret)
            continue

        # 确定实际持仓数：看空时按 regime_scale 缩减
        actual_n = n_stocks if not bearish else max(1, int(n_stocks * regime_scale))

        scores = composite.loc[date].dropna()
        if len(scores) < actual_n:
            continue

        picks = scores.sort_values(ascending=False).head(actual_n).index.tolist()

        # 等权 + cap
        raw_w = pd.Series(1.0 / len(picks), index=picks)
        capped_w = cap_weights(raw_w, max_weight=max_weight)

        if i + 1 < len(rebal_dates):
            next_date = rebal_dates[i + 1]
        else:
            next_date = price_wide.index[-1]

        period_ret = dr.loc[date:next_date, picks]
        if len(period_ret) > 1:
            period_ret = period_ret.iloc[1:]

        # 个股止损：触发后该股票当期内收益置零
        if stop_loss_threshold is not None and len(period_ret) > 0:
            period_ret = per_stock_stop(period_ret, threshold=stop_loss_threshold)

        port_daily = period_ret.mul(capped_w, axis=1).sum(axis=1)

        # 换仓成本（用 actual_n 作分母，反映实际持仓规模）
        new_picks = set(picks)
        if prev_picks:
            turnover = 1 - len(new_picks & prev_picks) / max(actual_n, len(prev_picks))
        else:
            turnover = 1.0
        if len(port_daily) > 0:
            port_daily.iloc[0] -= cost * turnover

        prev_picks = new_picks
        portfolio_returns.append(port_daily)

    if not portfolio_returns:
        return pd.Series(dtype=float)
    return pd.concat(portfolio_returns).sort_index()


# ══════════════════════════════════════════════════════════════
# 市场状态自适应回测
# ══════════════════════════════════════════════════════════════
def run_backtest_adaptive(
    price_wide,
    factor_dict,
    regime_weights: dict,
    regime_series: "pd.Series",
    n_stocks: int = 30,
    cost: float = 0.003,
    mask=None,
    max_weight: float = 0.1,
    lag1: bool = True,
):
    """
    市场状态自适应回测：每个换仓日根据当前 regime 切换因子权重。

    参数:
        price_wide    : 价格宽表
        factor_dict   : {因子名: 因子 DataFrame}
        regime_weights: {"bull": {因子名: 权重}, "flat": {...}, "bear": {...}}
        regime_series : pd.Series[str]，值为 "bull"/"flat"/"bear"，日频
        n_stocks      : 持仓数
        cost          : 换仓双边成本
        mask          : 可交易性 bool mask
        max_weight    : 单票上限
        lag1          : 是否延迟 1 日使用信号

    返回:
        pd.Series: 日收益率
    """
    dr = price_wide.pct_change()

    # 预先为每种 regime 计算合成因子
    composites = {}
    for state, weights in regime_weights.items():
        total_w = sum(weights.values())
        norm_w = {k: v / total_w for k, v in weights.items()}
        comp = None
        for name, w in norm_w.items():
            if name not in factor_dict:
                continue
            z = zscore_cross(factor_dict[name])
            comp = z * w if comp is None else comp.add(z * w, fill_value=0)
        if comp is not None:
            if mask is not None:
                comp = comp.where(mask.reindex_like(comp))
            if lag1:
                comp = comp.shift(1)
            composites[state] = comp

    if lag1:
        regime_series = regime_series.shift(1).ffill()

    rebal_dates = price_wide.resample("MS").first().index
    rebal_dates = [d for d in rebal_dates if d in price_wide.index]

    portfolio_returns = []
    prev_picks = set()

    for i, date in enumerate(rebal_dates):
        # 选当前 regime 的合成因子
        state = regime_series.loc[date] if date in regime_series.index else "flat"
        if state not in composites:
            state = "flat"
        if state not in composites:
            continue

        composite = composites[state]
        if date not in composite.index:
            continue

        scores = composite.loc[date].dropna()
        if len(scores) < n_stocks:
            continue

        picks = scores.sort_values(ascending=False).head(n_stocks).index.tolist()
        raw_w = pd.Series(1.0 / len(picks), index=picks)
        capped_w = cap_weights(raw_w, max_weight=max_weight)

        next_date = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else price_wide.index[-1]
        period_ret = dr.loc[date:next_date, picks]
        if len(period_ret) > 1:
            period_ret = period_ret.iloc[1:]

        port_daily = period_ret.mul(capped_w, axis=1).sum(axis=1)

        new_picks = set(picks)
        turnover = 1 - len(new_picks & prev_picks) / n_stocks if prev_picks else 1.0
        if len(port_daily) > 0:
            port_daily.iloc[0] -= cost * turnover

        prev_picks = new_picks
        portfolio_returns.append(port_daily)

    if not portfolio_returns:
        return pd.Series(dtype=float)
    return pd.concat(portfolio_returns).sort_index()


# ══════════════════════════════════════════════════════════════
# IC 快报
# ══════════════════════════════════════════════════════════════
def print_ic_report(factors, price, start, end):
    """打印因子 IC 快报"""
    import io, contextlib
    fwd = price.pct_change(5).shift(-5)
    print(f"\n{'因子':<20} {'IC均值':>8} {'ICIR':>8} {'IC>0%':>7}")
    print("-" * 47)
    for name, fac in factors.items():
        ic_s = compute_ic_series(
            fac.loc[start:end], fwd.loc[start:end],
            method="spearman", min_stocks=50,
        )
        with contextlib.redirect_stdout(io.StringIO()):
            s = ic_summary(ic_s, name=name)
        ic_mean = s["IC_mean"] if pd.notna(s.get("IC_mean")) else 0
        icir = s.get("ICIR", 0) or 0
        ic_pos = s.get("pct_pos", 0.5) or 0.5
        print(f"  {name:<18} {ic_mean:>8.4f} {icir:>8.4f} {ic_pos:>6.1%}")


# ══════════════════════════════════════════════════════════════
# 绩效打印
# ══════════════════════════════════════════════════════════════
def calc_metrics(ret):
    """计算绩效指标并返回 dict"""
    return {
        "ann": annualized_return(ret),
        "vol": annualized_volatility(ret),
        "sr": sharpe_ratio(ret),
        "mdd": max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr": win_rate(ret),
        "days": len(ret),
    }


def print_metrics(label, ret, bench_ret=None):
    """打印绩效"""
    m = calc_metrics(ret)
    print(f"\n  {label}:")
    print(f"    年化: {m['ann']:>+.2%} | 波动: {m['vol']:>.2%} | "
          f"夏普: {m['sr']:>.4f} | 回撤: {m['mdd']:>.2%}")
    print(f"    胜率: {m['wr']:>.2%} | 卡玛: {m['calmar']:>.2f} | "
          f"交易日: {m['days']}")
    if bench_ret is not None:
        ci = ret.index.intersection(bench_ret.index)
        excess = annualized_return(ret.loc[ci] - bench_ret.loc[ci])
        print(f"    年化超额: {excess:>+.2%}")
    return m


# ══════════════════════════════════════════════════════════════
# 准入门槛
# ══════════════════════════════════════════════════════════════
def print_admission_table(m_is, m_oos=None, mode="honest_baseline"):
    """打印准入门槛对比表"""
    print("\n" + "=" * 65)
    print(f"  v6 准入门槛评审 (mode={mode})")
    print("=" * 65)

    def gate(label, val, threshold, higher_is_better=True):
        if higher_is_better:
            ok = val > threshold
            fmt_thresh = f"> {threshold:.0%}" if threshold < 1 else f"> {threshold}"
        else:
            ok = val < threshold
            fmt_thresh = f"< {threshold:.0%}" if threshold < 1 else f"< {threshold}"
        icon = "✅" if ok else "❌"
        return icon, ok

    checks_is = [
        ("年化收益", m_is["ann"], ADMISSION_THRESHOLDS["annual_return"], True),
        ("夏普比率", m_is["sr"], ADMISSION_THRESHOLDS["sharpe_ratio"], True),
        ("最大回撤", abs(m_is["mdd"]), ADMISSION_THRESHOLDS["max_drawdown"], False),
        ("回测跨度", m_is["days"] / 252, ADMISSION_THRESHOLDS["backtest_years"], True),
    ]

    print(f"\n  {'指标':<12} {'样本内':>10} {'门槛':>10} {'结果':>4}", end="")
    if m_oos:
        print(f" {'样本外':>10} {'结果':>4}")
    else:
        print()

    print("  " + "-" * 55)
    all_pass = True
    for label, val, thresh, higher in checks_is:
        icon, ok = gate(label, val, thresh, higher)
        if not ok:
            all_pass = False

        if higher:
            fmt_val = f"{val:>.2%}" if thresh < 1 else f"{val:>.1f}"
            fmt_thresh = f"> {thresh:.0%}" if thresh < 1 else f"> {thresh:.0f}"
        else:
            fmt_val = f"{val:>.2%}"
            fmt_thresh = f"< {thresh:.0%}"

        line = f"  {label:<12} {fmt_val:>10} {fmt_thresh:>10} {icon:>4}"

        if m_oos:
            # 样本外对应值
            oos_map = {"年化收益": m_oos["ann"], "夏普比率": m_oos["sr"],
                       "最大回撤": abs(m_oos["mdd"]),
                       "回测跨度": m_oos["days"] / 252}
            oos_val = oos_map[label]
            oos_icon, _ = gate(label, oos_val, thresh, higher)
            if higher:
                oos_fmt = f"{oos_val:>.2%}" if thresh < 1 else f"{oos_val:>.1f}"
            else:
                oos_fmt = f"{oos_val:>.2%}"
            line += f" {oos_fmt:>10} {oos_icon:>4}"

        print(line)

    print("  " + "-" * 55)
    status = "PASS" if all_pass else "FAIL"
    print(f"  样本内准入状态: {'✅' if all_pass else '❌'} {status}")
    print("=" * 65)
    return all_pass


# ══════════════════════════════════════════════════════════════
# 止损对照表
# ══════════════════════════════════════════════════════════════
def print_stop_loss_comparison(m_base_is, m_sl_is, m_base_oos, m_sl_oos,
                               threshold):
    """打印 baseline vs 止损 的对比表"""
    print(f"\n{'=' * 70}")
    print(f"  Baseline vs 止损({threshold:.0%}) 对比")
    print(f"{'=' * 70}")

    rows = [
        ("年化收益", "ann", ".2%"),
        ("波动率",   "vol", ".2%"),
        ("夏普比率", "sr",  ".4f"),
        ("最大回撤", "mdd", ".2%"),
        ("卡玛比率", "calmar", ".2f"),
        ("胜率",     "wr",  ".2%"),
    ]

    # 表头
    header = f"  {'指标':<12}"
    header += f" {'基线(IS)':>10} {'止损(IS)':>10} {'Δ':>10}"
    if m_base_oos and m_sl_oos:
        header += f" {'基线(OOS)':>10} {'止损(OOS)':>10} {'Δ':>10}"
    print(header)
    print("  " + "-" * (len(header) - 2))

    for label, key, fmt in rows:
        base_v = m_base_is[key]
        sl_v = m_sl_is[key]
        delta = sl_v - base_v

        val_spec = f">10{fmt}"     # e.g. ">10.2%"
        delta_spec = f">+10{fmt}"  # e.g. ">+10.2%"

        line = f"  {label:<12}"
        line += f" {base_v:{val_spec}} {sl_v:{val_spec}} {delta:{delta_spec}}"

        if m_base_oos and m_sl_oos:
            bo = m_base_oos[key]
            so = m_sl_oos[key]
            do = so - bo
            line += f"   {bo:{val_spec}} {so:{val_spec}} {do:{delta_spec}}"

        print(line)

    print("  " + "-" * (len(header) - 2))
    print(f"{'=' * 70}")


# ══════════════════════════════════════════════════════════════
# Walk-Forward
# ══════════════════════════════════════════════════════════════
def run_walk_forward(price, factors, regime_mask, tradable_mask,
                     n_stocks, cost, lag1, stop_loss_threshold=None):
    """滚动样本外验证，返回 WF 摘要 dict（用于 markdown 输出）"""
    print("\n[5/6] Walk-Forward 验证...")
    from utils.walk_forward import walk_forward_test

    def wf_fn(price_slice, _fdata, train_start, train_end, test_start, test_end):
        # 在训练期内重算因子和 IC 权重
        local_fwd = price_slice.pct_change(5).shift(-5)
        local_weights = {}
        local_factors = {
            "team_coin": _team_coin(price_slice),
            "low_vol_20d": _low_vol_20d(price_slice),
            "cgo_simple": -(price_slice / price_slice.rolling(60).mean() - 1),
            "enhanced_mom_60": enhanced_momentum(price_slice, window=60),
        }
        # bp 需要 PB 数据，WF 中用 4 因子子集
        for fn, fac in local_factors.items():
            f_s = fac.loc[train_start:train_end]
            fw_s = local_fwd.loc[train_start:train_end]
            ic_s = compute_ic_series(f_s, fw_s, method="spearman", min_stocks=50)
            if len(ic_s) > 10:
                m, sd = ic_s.mean(), ic_s.std()
                if m > 0 and sd > 0 and m / sd > 0.15:
                    local_weights[fn] = abs(m / sd)

        if not local_weights:
            return pd.Series(dtype=float)

        local_mask = apply_tradability_filter(price_slice)
        ret = run_backtest(
            price_slice, local_factors, local_weights, n_stocks,
            cost=cost, mask=local_mask, regime_mask=regime_mask,
            lag1=lag1, stop_loss_threshold=stop_loss_threshold,
        )
        return ret.loc[test_start:test_end] if len(ret) > 0 else pd.Series(dtype=float)

    wf_summary = None
    try:
        wf = walk_forward_test(
            wf_fn, price.loc[WARMUP_START:IS_END], {},
            train_years=3, test_months=6,
        )
        valid = wf[wf["sharpe"].notna()]
        print(f"  窗口: {len(wf)} | 有效: {len(valid)}")
        if len(valid) > 0:
            wf_summary = {
                "windows": len(wf),
                "valid": len(valid),
                "sharpe_mean": valid["sharpe"].mean(),
                "sharpe_median": valid["sharpe"].median(),
                "return_mean": valid["total_return"].mean(),
                "win_rate": (valid["total_return"] > 0).mean(),
                "mdd_mean": valid["max_drawdown"].mean(),
            }
            print(f"  夏普均值: {wf_summary['sharpe_mean']:>.4f} | "
                  f"中位数: {wf_summary['sharpe_median']:>.4f}")
            print(f"  收益均值: {wf_summary['return_mean']:>+.2%} | "
                  f"胜率: {wf_summary['win_rate']:.0%}")
            print(f"  回撤均值: {wf_summary['mdd_mean']:>.2%}")
    except Exception as e:
        print(f"  Walk-Forward 失败: {e}")

    return wf_summary


# ══════════════════════════════════════════════════════════════
# Markdown 报告输出
# ══════════════════════════════════════════════════════════════
def _fmt_metrics_row(label, m):
    """格式化一行指标"""
    return (f"| {label} | {m['ann']:+.2%} | {m['vol']:.2%} | "
            f"{m['sr']:.4f} | {m['mdd']:.2%} | {m['calmar']:.2f} | "
            f"{m['wr']:.2%} | {m['days']} |")


def generate_markdown_report(*, mode, n_stocks, cost, stop_loss_threshold,
                             m_is, m_oos, passed, wf_summary,
                             m_sl_is=None, m_sl_oos=None,
                             stock_count=None, rebalance_freq="monthly"):
    """生成完整的准入评估 markdown 报告"""
    from datetime import date
    lines = []
    sl_str = f" | 止损={stop_loss_threshold:.0%}" if stop_loss_threshold else ""
    lag1 = mode == "honest_baseline"
    freq_label = "双周" if rebalance_freq == "biweekly" else "月频"

    lines.append(f"# v6 准入评估报告")
    lines.append(f"")
    lines.append(f"- **日期**: {date.today()}")
    lines.append(f"- **模式**: {mode} (lag1={lag1}) | **换仓频率**: {freq_label}({rebalance_freq})")
    lines.append(f"- **持仓数**: {n_stocks} | **成本**: {cost:.1%}{sl_str}")
    lines.append(f"- **IS**: {IS_START} ~ {IS_END} | **OOS**: {OOS_START} ~ {OOS_END}")
    if stock_count:
        lines.append(f"- **股票数**: {stock_count}（数据快照，不同环境可能不同）")
    lines.append(f"")

    # IS/OOS 指标表
    lines.append(f"## IS / OOS 绩效")
    lines.append(f"")
    lines.append("| 区间 | 年化 | 波动 | 夏普 | 回撤 | 卡玛 | 胜率 | 交易日 |")
    lines.append("| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |")
    lines.append(_fmt_metrics_row("样本内", m_is))
    if m_oos:
        lines.append(_fmt_metrics_row("样本外", m_oos))
    lines.append(f"")

    # 准入门槛
    lines.append(f"## 准入门槛")
    lines.append(f"")
    lines.append("| 指标 | 样本内 | 门槛 | 结果 |")
    lines.append("| --- | ---: | ---: | :---: |")

    gate_checks = [
        ("年化收益", m_is["ann"], ADMISSION_THRESHOLDS["annual_return"], True, ".2%", "> 15%"),
        ("夏普比率", m_is["sr"], ADMISSION_THRESHOLDS["sharpe_ratio"], True, ".4f", "> 0.80"),
        ("最大回撤", abs(m_is["mdd"]), ADMISSION_THRESHOLDS["max_drawdown"], False, ".2%", "< 30%"),
        ("回测跨度", m_is["days"] / 252, ADMISSION_THRESHOLDS["backtest_years"], True, ".1f", "> 3"),
    ]
    for label, val, thresh, higher, fmt, fmt_thresh in gate_checks:
        ok = (val > thresh) if higher else (val < thresh)
        icon = "PASS" if ok else "FAIL"
        fmt_val = f"{val:{fmt}}"
        lines.append(f"| {label} | {fmt_val} | {fmt_thresh} | {icon} |")

    lines.append(f"")
    lines.append(f"**准入状态**: {'PASS' if passed else 'FAIL'}")
    lines.append(f"")

    # Walk-Forward
    lines.append(f"## Walk-Forward 验证")
    lines.append(f"")
    lines.append(f"> 注意：WF 始终使用 baseline 配置（无止损），与 IS/OOS baseline 保持一致。")
    lines.append(f"> WF 使用 4 因子子集（无 bp），权重按窗口内 IC 动态计算。")
    lines.append(f"")
    if wf_summary:
        lines.append(f"| 指标 | 值 |")
        lines.append(f"| --- | ---: |")
        lines.append(f"| 窗口数 | {wf_summary['windows']} |")
        lines.append(f"| 有效窗口 | {wf_summary['valid']} |")
        lines.append(f"| 夏普均值 | {wf_summary['sharpe_mean']:.4f} |")
        lines.append(f"| 夏普中位数 | {wf_summary['sharpe_median']:.4f} |")
        lines.append(f"| 收益均值 | {wf_summary['return_mean']:+.2%} |")
        lines.append(f"| 胜率 | {wf_summary['win_rate']:.0%} |")
        lines.append(f"| 回撤均值 | {wf_summary['mdd_mean']:.2%} |")
    else:
        lines.append(f"Walk-Forward 数据不足或执行失败。")
    lines.append(f"")

    # 止损对比
    if m_sl_is:
        lines.append(f"## 止损对照 (baseline vs {stop_loss_threshold:.0%})")
        lines.append(f"")
        lines.append("| 指标 | 基线(IS) | 止损(IS) | Δ |")
        lines.append("| --- | ---: | ---: | ---: |")
        sl_rows = [
            ("年化收益", "ann", ".2%"),
            ("波动率",   "vol", ".2%"),
            ("夏普比率", "sr",  ".4f"),
            ("最大回撤", "mdd", ".2%"),
            ("卡玛比率", "calmar", ".2f"),
            ("胜率",     "wr",  ".2%"),
        ]
        for label, key, fmt in sl_rows:
            bv, sv = m_is[key], m_sl_is[key]
            d = sv - bv
            d_spec = f"+{fmt}"
            lines.append(f"| {label} | {bv:{fmt}} | {sv:{fmt}} | {d:{d_spec}} |")

        if m_sl_oos:
            lines.append(f"")
            lines.append("| 指标 | 基线(OOS) | 止损(OOS) | Δ |")
            lines.append("| --- | ---: | ---: | ---: |")
            for label, key, fmt in sl_rows:
                bv, sv = m_oos[key], m_sl_oos[key]
                d = sv - bv
                d_spec = f"+{fmt}"
                lines.append(f"| {label} | {bv:{fmt}} | {sv:{fmt}} | {d:{d_spec}} |")
        lines.append(f"")

    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════
def main(mode="honest_baseline", n_stocks=30, cost=0.003,
         stop_loss_threshold=None, output_path=None,
         rebalance_freq="monthly"):
    """v6 准入评估主流程"""
    lag1 = mode == "honest_baseline"

    print("=" * 65)
    print(f"  v6 策略准入评估")
    sl_str = f" | 止损={stop_loss_threshold:.0%}" if stop_loss_threshold is not None else ""
    freq_str = f" | 换仓={rebalance_freq}" if rebalance_freq != "monthly" else ""
    print(f"  模式: {mode} | lag1={lag1} | N={n_stocks} | 成本={cost:.1%}{sl_str}{freq_str}")
    print("=" * 65)

    # 1. 数据
    price, hs300_full, hs300, pb, stock_count = load_data()

    # 2. 因子
    factors = build_v6_factors(price, pb)

    # 3. 择时
    regime_mask = build_majority_vote_regime(hs300_full, hs300)

    # 4. 可交易性
    tradable = apply_tradability_filter(price)
    print(f"  可交易率: {tradable.mean().mean():.1%}")

    # IC 快报
    print_ic_report(factors, price, IS_START, IS_END)

    # 回测公共参数
    bt_kwargs = dict(
        factor_dict=factors, weights=V6_WEIGHTS, n_stocks=n_stocks,
        cost=cost, mask=tradable, regime_mask=regime_mask, lag1=lag1,
        rebalance_freq=rebalance_freq,
    )

    # 5. 样本内回测
    print(f"\n[4/6] 样本内回测 ({IS_START[:4]}-{IS_END[:4]})...")
    strat_is = run_backtest(price.loc[:IS_END], **bt_kwargs)
    strat_is = strat_is.loc[IS_START:]
    bench_is = hs300.loc[IS_START:IS_END].pct_change().dropna()
    m_is = print_metrics("v6 样本内", strat_is, bench_is)
    print_metrics("沪深300 样本内", bench_is)

    # 6. 样本外回测
    print(f"\n  === 样本外 {OOS_START[:4]} ===")
    strat_oos = run_backtest(price.loc[:OOS_END], **bt_kwargs)
    strat_oos = strat_oos.loc[OOS_START:]
    bench_oos = hs300.loc[OOS_START:OOS_END].pct_change().dropna()

    m_oos = None
    if len(strat_oos) > 20:
        m_oos = print_metrics("v6 样本外", strat_oos, bench_oos)
        print_metrics("沪深300 样本外", bench_oos)
    else:
        print("  样本外数据不足，跳过")

    # Walk-Forward（baseline 不传止损，与 IS/OOS baseline 保持一致）
    wf_summary = run_walk_forward(price, factors, regime_mask, tradable,
                                  n_stocks, cost, lag1,
                                  stop_loss_threshold=None)

    # 准入门槛
    passed = print_admission_table(m_is, m_oos, mode)

    # 双模式对比（如果是 honest_baseline，额外跑 optimistic 做参照）
    if lag1:
        print(f"\n  === 参照：optimistic（无 lag）===")
        strat_opt = run_backtest(
            price.loc[:IS_END], **{**bt_kwargs, "lag1": False},
        )
        strat_opt = strat_opt.loc[IS_START:]
        m_opt = print_metrics("v6 optimistic 样本内", strat_opt, bench_is)
        print(f"\n  lag1 vs no-lag 差距:")
        print(f"    年化: {m_is['ann'] - m_opt['ann']:>+.2%}")
        print(f"    夏普: {m_is['sr'] - m_opt['sr']:>+.4f}")
        print(f"    回撤: {abs(m_is['mdd']) - abs(m_opt['mdd']):>+.2%}")

    # 止损对照模式
    m_sl_is = None
    m_sl_oos = None
    if stop_loss_threshold is not None:
        print(f"\n{'=' * 65}")
        print(f"  止损对照：baseline vs 止损 ({stop_loss_threshold:.0%})")
        print(f"{'=' * 65}")

        # 样本内 — 带止损
        strat_sl_is = run_backtest(
            price.loc[:IS_END],
            **{**bt_kwargs, "stop_loss_threshold": stop_loss_threshold},
        )
        strat_sl_is = strat_sl_is.loc[IS_START:]
        m_sl_is = print_metrics(f"v6 止损({stop_loss_threshold:.0%}) 样本内",
                                strat_sl_is, bench_is)

        # 样本外 — 带止损
        strat_sl_oos = run_backtest(
            price.loc[:OOS_END],
            **{**bt_kwargs, "stop_loss_threshold": stop_loss_threshold},
        )
        strat_sl_oos = strat_sl_oos.loc[OOS_START:]
        if len(strat_sl_oos) > 20:
            m_sl_oos = print_metrics(f"v6 止损({stop_loss_threshold:.0%}) 样本外",
                                     strat_sl_oos, bench_oos)

        # 对比表
        print_stop_loss_comparison(m_is, m_sl_is, m_oos, m_sl_oos,
                                   stop_loss_threshold)

    # 写 markdown 报告
    if output_path is not None:
        from datetime import date
        if output_path == "auto":
            output_path = (Path(__file__).parent.parent
                           / "journal"
                           / f"v6_admission_eval_{date.today()}.md")
        else:
            output_path = Path(output_path)

        md = generate_markdown_report(
            mode=mode, n_stocks=n_stocks, cost=cost,
            stop_loss_threshold=stop_loss_threshold,
            m_is=m_is, m_oos=m_oos, passed=passed,
            wf_summary=wf_summary,
            m_sl_is=m_sl_is, m_sl_oos=m_sl_oos,
            stock_count=stock_count,
            rebalance_freq=rebalance_freq,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(md, encoding="utf-8")
        print(f"\n  📄 报告已写入: {output_path}")

    print("\n[6/6] 完成。")
    return passed


def parse_args():
    parser = argparse.ArgumentParser(description="v6 策略准入评估")
    parser.add_argument(
        "--mode", choices=["honest_baseline", "optimistic"],
        default="honest_baseline",
        help="评估模式：honest_baseline(lag1, 默认) 或 optimistic(无lag)",
    )
    parser.add_argument(
        "--n-stocks", type=int, default=30,
        help="持仓数（默认 30）",
    )
    parser.add_argument(
        "--cost", type=float, default=0.003,
        help="双边交易成本（默认 0.003 = 0.3%%）",
    )
    parser.add_argument(
        "--stop-loss", type=float, nargs="?", const=-0.10, default=None,
        dest="stop_loss",
        help="个股止损阈值（默认 -0.10 即 -10%%）。不带值使用默认 -0.10，不加此 flag 则不启用",
    )
    parser.add_argument(
        "--output", nargs="?", const="auto", default=None,
        help="输出 markdown 报告路径（默认 journal/v6_admission_eval_{date}.md）",
    )
    parser.add_argument(
        "--rebalance-freq", choices=["monthly", "biweekly"],
        default="monthly", dest="rebalance_freq",
        help="换仓频率：monthly（默认）或 biweekly（双周）",
    )
    parser.add_argument(
        "--biweekly", action="store_const", const="biweekly",
        dest="rebalance_freq",
        help="双周换仓模式（等价于 --rebalance-freq biweekly）",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    main(mode=args.mode, n_stocks=args.n_stocks, cost=args.cost,
         stop_loss_threshold=args.stop_loss, output_path=args.output,
         rebalance_freq=args.rebalance_freq)
