"""
真实数据策略评估 v2 — 修复 NaN 预热问题 + 去掉 momentum + IC 加权

输出：
  1. 每个因子的 IC/ICIR（真实数据）
  2. 样本内回测（2015-2024）— v1 原始等权 vs v2 IC加权去momentum
  3. 样本外回测（2025）
  4. Walk-Forward 稳定性
  5. Phase 5 门槛评审
"""
import sys, os, time, warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import io, contextlib
import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate,
)
from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest
from utils.tradability_filter import apply_tradability_filter, cap_weights

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
INSAMPLE_START = "2015-01-01"
INSAMPLE_END = "2024-12-31"
OOS_START = "2025-01-01"
OOS_END = "2025-12-31"
N_STOCKS = 30
COST_PER_REBAL = 0.003  # 双边 0.3%

print("=" * 60)
print("  多因子策略评估 v2 — 真实 A 股数据")
print("=" * 60)

# ══════════════════════════════════════════════════════════════
# 1. 加载数据（从 2013 开始，给 momentum 留足预热期）
# ══════════════════════════════════════════════════════════════
print("\n[1/6] 加载数据...")
t0 = time.time()
symbols = get_all_symbols()
price_full = load_price_wide(symbols, "2013-01-01", OOS_END, field="close")
hs300 = get_index_history(symbol="sh000300", start="2013-01-01", end=OOS_END)["close"]
common = price_full.index.intersection(hs300.index)
price_full = price_full.loc[common]
hs300 = hs300.loc[common]

# 去掉交易日数太少的股票（至少 500 天有价格）
valid_cols = price_full.columns[price_full.notna().sum() > 500]
price_full = price_full[valid_cols]

print(f"  股票: {price_full.shape[1]} 只 | 交易日: {price_full.shape[0]} | 耗时: {time.time()-t0:.1f}s")

# 构建可交易性 mask（ST / 上市天数 / 低价 / 流动性）
tradable_mask = apply_tradability_filter(price_full)
tradable_pct = tradable_mask.mean().mean()
print(f"  可交易率: {tradable_pct:.1%} | 被过滤: {1-tradable_pct:.1%}")

# ══════════════════════════════════════════════════════════════
# 2. 因子构建 + IC 分析
# ══════════════════════════════════════════════════════════════
print("\n[2/6] 因子 IC 分析...")

daily_ret = price_full.pct_change()
fwd_ret_5d = price_full.pct_change(5).shift(-5)

# 构建因子（全时段，让 lookback 在 2013 预热）
factors = {
    "momentum_12_1": price_full.pct_change(252).shift(21),
    "reversal_1m": -price_full.pct_change(21),
    "low_vol_20d": -daily_ret.rolling(20).std(),
    "turnover_rev": -daily_ret.abs().rolling(20).mean(),
}

# 只用样本内数据算 IC（复用 utils/factor_analysis 工具函数）
ic_results = {}
print(f"\n{'因子':<20} {'IC均值':>8} {'ICIR':>8} {'IC>0%':>7} {'判断':>6}")
print("-" * 55)

for name, fac in factors.items():
    fac_is = fac.loc[INSAMPLE_START:INSAMPLE_END]
    fwd_is = fwd_ret_5d.loc[INSAMPLE_START:INSAMPLE_END]

    ic_s = compute_ic_series(fac_is, fwd_is, method="spearman", min_stocks=50)
    # 使用 ic_summary 计算统计量，抑制其打印输出以保持原表格格式
    with contextlib.redirect_stdout(io.StringIO()):
        summary = ic_summary(ic_s, name=name)

    ic_mean = summary["IC_mean"]
    icir = summary["ICIR"] if pd.notna(summary["ICIR"]) else 0
    ic_pos = summary["pct_pos"]

    if pd.notna(ic_mean):
        verdict = "✅" if abs(icir) > 0.2 and ic_mean > 0 else "❌"
        print(f"{name:<20} {ic_mean:>8.4f} {icir:>8.4f} {ic_pos:>6.1%} {verdict:>6}")
        ic_results[name] = {"ic_mean": ic_mean, "icir": icir, "ic_pos_pct": ic_pos}
    else:
        print(f"{name:<20} {'N/A':>8} {'N/A':>8} {'N/A':>7} {'❌':>6}")
        ic_results[name] = {"ic_mean": 0, "icir": 0, "ic_pos_pct": 0}

# 分层回测：展示各因子的五分位组收益
print(f"\n{'因子':<20} {'Q1':>8} {'Q2':>8} {'Q3':>8} {'Q4':>8} {'Q5':>8} {'多空':>8}")
print("-" * 74)

for name, fac in factors.items():
    fac_is = fac.loc[INSAMPLE_START:INSAMPLE_END]
    fwd_is = fwd_ret_5d.loc[INSAMPLE_START:INSAMPLE_END]
    group_ret, ls_ret = quintile_backtest(fac_is, fwd_is, n_groups=5)
    group_ann = group_ret.mean() * 252
    ls_ann = ls_ret.dropna().mean() * 252
    print(f"{name:<20} {group_ann['Q1']:>+7.2%} {group_ann['Q2']:>+7.2%} "
          f"{group_ann['Q3']:>+7.2%} {group_ann['Q4']:>+7.2%} {group_ann['Q5']:>+7.2%} "
          f"{ls_ann:>+7.2%}")

# ══════════════════════════════════════════════════════════════
# 3. 工具函数 + 回测函数
# ══════════════════════════════════════════════════════════════

def build_factors(price_wide):
    """从价格宽表构建四个候选因子"""
    dr = price_wide.pct_change()
    return {
        "momentum_12_1": price_wide.pct_change(252).shift(21),
        "reversal_1m": -price_wide.pct_change(21),
        "low_vol_20d": -dr.rolling(20).std(),
        "turnover_rev": -dr.abs().rolling(20).mean(),
    }

def derive_ic_weights(price_wide, factor_dict, start, end, icir_threshold=0.2):
    """
    在指定区间内计算各因子 IC，返回 IC 加权权重（仅保留 ICIR > threshold 的正 IC 因子）。

    参数:
        price_wide: 价格宽表
        factor_dict: {因子名: 因子 DataFrame}
        start, end: 计算区间
        icir_threshold: ICIR 入选门槛

    返回:
        dict: {因子名: 权重}，可能为空
    """
    fwd = price_wide.pct_change(5).shift(-5)
    weights = {}
    for name, fac in factor_dict.items():
        fac_s = fac.loc[start:end]
        fwd_s = fwd.loc[start:end]
        ic_s = compute_ic_series(fac_s, fwd_s, method="spearman", min_stocks=50)
        if len(ic_s) < 10:
            continue
        ic_mean = ic_s.mean()
        ic_std = ic_s.std()
        icir = ic_mean / ic_std if ic_std > 0 else 0
        if ic_mean > 0 and abs(icir) > icir_threshold:
            weights[name] = abs(icir)
    return weights

def zscore_cross(df):
    """截面 z-score 标准化"""
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

def run_backtest(price_wide, factor_dict, weights, n_stocks=30, cost=0.003,
                 mask=None, max_weight=0.1, regime_mask=None):
    """
    多因子回测

    参数:
        price_wide: 价格宽表
        factor_dict: {因子名: 因子 DataFrame}
        weights: {因子名: 权重}（权重会归一化）
        n_stocks: 持仓数
        cost: 每次换仓双边成本
        mask: 可交易性 bool mask（True=可交易），为 None 时不过滤
        max_weight: 单票最大权重，默认 0.1 (10%)
        regime_mask: 市场状态 mask（pd.Series[bool]，True=看多可交易），为 None 时不过滤

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
        z = zscore_cross(factor_dict[name])
        if composite is None:
            composite = z * w
        else:
            composite = composite.add(z * w, fill_value=0)

    # 用可交易性 mask 过滤：不可交易的股票分数设为 NaN
    if mask is not None:
        aligned_mask = mask.reindex_like(composite)
        composite = composite.where(aligned_mask)

    # 月频换仓
    rebal_dates = price_wide.resample("MS").first().index
    rebal_dates = [d for d in rebal_dates if d in composite.index]

    portfolio_returns = []
    prev_picks = set()

    for i, date in enumerate(rebal_dates):
        # 市场状态过滤：看空时不持仓（返回 0 收益）
        if regime_mask is not None and date in regime_mask.index and not regime_mask.loc[date]:
            if i + 1 < len(rebal_dates):
                next_date = rebal_dates[i + 1]
            else:
                next_date = price_wide.index[-1]
            zero_ret = pd.Series(0.0, index=dr.loc[date:next_date].index[1:])
            if prev_picks:
                # 清仓成本
                if len(zero_ret) > 0:
                    zero_ret.iloc[0] -= cost
            prev_picks = set()
            portfolio_returns.append(zero_ret)
            continue

        scores = composite.loc[date].dropna()
        if len(scores) < n_stocks:
            continue  # 有效得分股票不够，跳过这个月

        picks = scores.sort_values(ascending=False).head(n_stocks).index.tolist()

        # 构建等权权重并 cap
        raw_w = pd.Series(1.0 / len(picks), index=picks)
        capped_w = cap_weights(raw_w, max_weight=max_weight)

        if i + 1 < len(rebal_dates):
            next_date = rebal_dates[i + 1]
        else:
            next_date = price_wide.index[-1]

        period_ret = dr.loc[date:next_date, picks]
        if len(period_ret) > 1:
            period_ret = period_ret.iloc[1:]  # 跳过换仓日

        # 用 capped 权重计算加权日收益
        port_daily = period_ret.mul(capped_w, axis=1).sum(axis=1)

        # 换仓成本：按换手比例扣
        new_picks = set(picks)
        if prev_picks:
            turnover = 1 - len(new_picks & prev_picks) / n_stocks
        else:
            turnover = 1.0  # 首次建仓
        if len(port_daily) > 0:
            port_daily.iloc[0] -= cost * turnover

        prev_picks = new_picks
        portfolio_returns.append(port_daily)

    if not portfolio_returns:
        return pd.Series(dtype=float)
    return pd.concat(portfolio_returns).sort_index()

# ══════════════════════════════════════════════════════════════
# 4. 样本内回测
# ══════════════════════════════════════════════════════════════
print("\n[3/6] 样本内回测 (2015-2024)...")

# 因子数据切到全时段（含预热期）
factor_data = {k: v for k, v in factors.items()}

# v1: 原始等权全因子
w_v1 = {k: 1.0 for k in factors}
strat_v1 = run_backtest(price_full.loc[:INSAMPLE_END], factor_data, w_v1, N_STOCKS, mask=tradable_mask)
strat_v1 = strat_v1.loc[INSAMPLE_START:]

# v2: IC 加权，去掉 momentum
good_factors = {k: v for k, v in ic_results.items() if v["ic_mean"] > 0 and v["icir"] > 0.2}
w_v2 = {k: abs(v["icir"]) for k, v in good_factors.items()}
print(f"  v2 使用因子: {list(w_v2.keys())}")
print(f"  v2 权重: {', '.join(f'{k}={v:.3f}' for k, v in w_v2.items())}")

strat_v2 = run_backtest(price_full.loc[:INSAMPLE_END], factor_data, w_v2, N_STOCKS, mask=tradable_mask)

# v3: v2 + RSRS 市场状态过滤
from utils.market_regime import rsrs_regime_mask
from utils.data_loader import get_index_history as _get_idx
_hs300_hl = _get_idx(symbol="sh000300", start="2013-01-01", end=OOS_END)
rsrs_mask = rsrs_regime_mask(_hs300_hl["high"], _hs300_hl["low"])
bull_pct = rsrs_mask.loc[INSAMPLE_START:INSAMPLE_END].mean()
print(f"  v3 = v2 + RSRS 市场过滤（看多 {bull_pct:.0%}，看空 {1-bull_pct:.0%}）")

strat_v3 = run_backtest(price_full.loc[:INSAMPLE_END], factor_data, w_v2, N_STOCKS,
                        mask=tradable_mask, regime_mask=rsrs_mask)
strat_v2 = strat_v2.loc[INSAMPLE_START:]
strat_v3 = strat_v3.loc[INSAMPLE_START:]

# Benchmark
bench = hs300.loc[INSAMPLE_START:INSAMPLE_END].pct_change().dropna()

def print_metrics(label, ret, bench_ret=None):
    """打印绩效指标"""
    common_idx = ret.index.intersection(bench_ret.index) if bench_ret is not None else ret.index
    r = ret.loc[common_idx]
    print(f"\n  {label}:")
    print(f"    年化收益: {annualized_return(r):>+.2%}")
    print(f"    年化波动: {annualized_volatility(r):>.2%}")
    print(f"    夏普比率: {sharpe_ratio(r):>.4f}")
    print(f"    最大回撤: {max_drawdown(r):>.2%}")
    print(f"    胜率:     {win_rate(r):>.2%}")
    if bench_ret is not None:
        b = bench_ret.loc[common_idx]
        excess = r - b
        print(f"    年化超额: {annualized_return(excess):>+.2%}")

print_metrics("v1 等权全因子（含 momentum）", strat_v1, bench)
print_metrics("v2 IC加权（去 momentum）", strat_v2, bench)
print_metrics("v3 v2 + RSRS 市场过滤", strat_v3, bench)
print_metrics("v2 IC加权（去 momentum）", strat_v2, bench)
print_metrics("沪深300", bench)

# ══════════════════════════════════════════════════════════════
# 5. 样本外回测 (2025)
# ══════════════════════════════════════════════════════════════
print(f"\n[4/6] 样本外回测 (2025)...")

strat_v2_oos = run_backtest(price_full.loc[:OOS_END], factor_data, w_v2, N_STOCKS, mask=tradable_mask)
strat_v2_oos = strat_v2_oos.loc[OOS_START:]
bench_oos = hs300.loc[OOS_START:OOS_END].pct_change().dropna()

if len(strat_v2_oos) > 20:
    print_metrics("v2 样本外", strat_v2_oos, bench_oos)
    print_metrics("沪深300 样本外", bench_oos)
else:
    print("  样本外数据不足，跳过")

# ══════════════════════════════════════════════════════════════
# 6. Walk-Forward
# ══════════════════════════════════════════════════════════════
print(f"\n[5/6] Walk-Forward 验证...")

from utils.walk_forward import walk_forward_test

def wf_strategy(price_slice, fdata, train_start, train_end, test_start, test_end):
    """真正的 walk-forward：每个窗口独立重新计算因子和 IC 权重"""
    # 用 price_slice 全段构建因子（含 lookback 预热期）
    local_factors = build_factors(price_slice)
    # 只在训练期内算 IC 权重
    local_w = derive_ic_weights(price_slice, local_factors, train_start, train_end)
    if not local_w:
        return pd.Series(dtype=float)  # 训练期内无有效因子
    # 构建可交易 mask
    local_mask = apply_tradability_filter(price_slice)
    # 回测整段（含训练期数据供因子计算），截取测试期收益
    ret = run_backtest(price_slice, local_factors, local_w, N_STOCKS,
                       mask=local_mask, regime_mask=rsrs_mask)
    ret = ret.loc[test_start:test_end]
    return ret if len(ret) > 0 else pd.Series(dtype=float)

try:
    price_is = price_full.loc["2013-01-01":INSAMPLE_END]
    wf = walk_forward_test(
        strategy_fn=wf_strategy,
        price_wide=price_is,
        factor_data={},
        train_years=3,
        test_months=6,
    )
    valid = wf[wf["sharpe"].notna()]
    print(f"  窗口: {len(wf)} | 有效: {len(valid)}")
    if len(valid) > 0:
        print(f"  夏普均值: {valid['sharpe'].mean():>.4f}")
        print(f"  夏普中位: {valid['sharpe'].median():>.4f}")
        print(f"  收益均值: {valid['total_return'].mean():>+.2%}")
        print(f"  收益胜率: {(valid['total_return'] > 0).mean():.0%}")
        print(f"  回撤均值: {valid['max_drawdown'].mean():>.2%}")
except Exception as e:
    print(f"  Walk-Forward 失败: {e}")

# ══════════════════════════════════════════════════════════════
# 7. Phase 5 门槛
# ══════════════════════════════════════════════════════════════
print("\n" + "=" * 60)
print("  Phase 5 门槛评审 (v3 策略 = IC加权 + RSRS过滤)")
print("=" * 60)

ann = annualized_return(strat_v3)
sr = sharpe_ratio(strat_v3)
mdd = max_drawdown(strat_v3)

checks = [
    ("年化收益 > 15%", f"{ann:>+.2%}", ann > 0.15),
    ("夏普比率 > 0.8", f"{sr:>.4f}", sr > 0.8),
    ("最大回撤 < 30%", f"{abs(mdd):>.2%}", abs(mdd) < 0.30),
    ("回测跨度 > 3年", f"{len(strat_v3)/252:.1f}年", len(strat_v3)/252 > 3),
]

for name, val, passed in checks:
    icon = "✅" if passed else "❌"
    print(f"  {icon} {name:<20} 实际: {val}")

all_pass = all(p for _, _, p in checks)
print(f"\n  {'✅ 全部通过' if all_pass else '❌ 尚未达标'}")
print("=" * 60)
