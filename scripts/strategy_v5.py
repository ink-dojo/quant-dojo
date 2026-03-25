"""
策略 v5 — 全因子库评估 + 最优组合

流程：
  1. 加载全量数据（price + high + low + PE + PB + turnover）
  2. 构建 11 个 alpha 因子
  3. IC/ICIR 筛选
  4. Fama-MacBeth 验证
  5. 最优因子组合回测（行业中性 + RSRS）
  6. Walk-forward
  7. 样本外
  8. Phase 5 门槛
"""
import sys, time, warnings, io, contextlib
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import annualized_return, annualized_volatility, sharpe_ratio, max_drawdown
from utils.factor_analysis import compute_ic_series, ic_summary
from utils.tradability_filter import apply_tradability_filter
from utils.market_regime import rsrs_regime_mask, vol_turnover_regime
from utils.alpha_factors import (
    reversal_1m, low_vol_20d, turnover_rev, ep_factor, bp_factor,
    shadow_line_upper, shadow_line_lower, str_salience, team_coin,
    cgo_factor,
)

IS_START, IS_END = "2015-01-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2025-12-31"
N_STOCKS = 100

print("=" * 65)
print("  策略 v5 — 全因子库 + 最优组合")
print("=" * 65)

# ── 1. 数据 ──────────────────────────────────────────────────
print("\n[1/8] 加载数据...")
t0 = time.time()
symbols = get_all_symbols()
price = load_price_wide(symbols, "2013-01-01", OOS_END, field="close")
high = load_price_wide(symbols, "2013-01-01", OOS_END, field="high")
low = load_price_wide(symbols, "2013-01-01", OOS_END, field="low")

hs300_full = get_index_history(symbol="sh000300", start="2013-01-01", end=OOS_END)
hs300 = hs300_full["close"]
common = price.index.intersection(hs300.index)
price, high, low, hs300 = price.loc[common], high.loc[common], low.loc[common], hs300.loc[common]

valid = price.columns[price.notna().sum() > 500]
price, high, low = price[valid], high[valid], low[valid]

# PE/PB 从缓存读
_cache = Path(__file__).parent.parent / "data" / "cache"
pe = pd.read_parquet(_cache / "pe_ttm_wide.parquet").reindex(index=price.index, columns=valid)
pb = pd.read_parquet(_cache / "pb_wide.parquet").reindex(index=price.index, columns=valid)

# 换手率（用日收益绝对值 × 成交量代理）
turnover_proxy = price.pct_change().abs() * 100  # 简化代理

print(f"  股票: {len(valid)} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")

# 可交易性 + 择时
tradable = apply_tradability_filter(price)
rsrs = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])
vt_regime = vol_turnover_regime(hs300, hs300_full["volume"] if "volume" in hs300_full.columns else hs300 * 0 + 1)

# 行业数据
try:
    ind_df = pd.read_csv(str(Path(__file__).parent.parent / "data" / "raw" / "industry_baostock.csv"))
    ind_df["symbol"] = ind_df["code"].str.split(".").str[1]
    ind_map = dict(zip(ind_df["symbol"], ind_df["industry"]))
except Exception:
    ind_map = {}
print(f"  行业: {len(ind_map)} 只")

# ── 2. 构建因子 ──────────────────────────────────────────────
print("\n[2/8] 构建因子...")
market_ret = hs300.pct_change()
daily_ret = price.pct_change()

factors = {
    "reversal_1m": reversal_1m(price),
    "low_vol_20d": low_vol_20d(price),
    "turnover_rev": turnover_rev(price),
    "ep": ep_factor(pe).reindex_like(price),
    "bp": bp_factor(pb).reindex_like(price),
    "shadow_upper": shadow_line_upper(high, price),
    "shadow_lower": shadow_line_lower(price, low),
    "str_salience": str_salience(daily_ret, market_ret),
    "team_coin": team_coin(price),
}

# CGO 和 amplitude_momentum 太慢（需要逐行循环），用简化版
# 简化 CGO：60 日 VWAP 代理
vwap_60 = price.rolling(60).mean()
factors["cgo_simple"] = -(price / vwap_60 - 1)  # 浮盈取负

print(f"  因子数: {len(factors)}")

# ── 3. IC 分析 ───────────────────────────────────────────────
print("\n[3/8] 因子 IC 分析...")
fwd = price.pct_change(5).shift(-5)

ic_results = {}
print(f"\n{'因子':<20} {'IC均值':>8} {'ICIR':>8} {'IC>0%':>7} {'判断':>4}")
print("-" * 52)

for name, fac in factors.items():
    ic_s = compute_ic_series(fac.loc[IS_START:IS_END], fwd.loc[IS_START:IS_END],
                             method="spearman", min_stocks=50)
    with contextlib.redirect_stdout(io.StringIO()):
        s = ic_summary(ic_s, name=name)
    ic_mean = s["IC_mean"] if pd.notna(s["IC_mean"]) else 0
    icir = s.get("ICIR", 0) or 0
    ic_pos = s.get("pct_pos", 0.5) or 0.5
    verdict = "✅" if ic_mean > 0 and abs(icir) > 0.15 else "❌"
    print(f"{name:<20} {ic_mean:>8.4f} {icir:>8.4f} {ic_pos:>6.1%} {verdict:>4}")
    ic_results[name] = {"ic_mean": ic_mean, "icir": icir}

# ── 4. Fama-MacBeth ──────────────────────────────────────────
print("\n[4/8] Fama-MacBeth 回归...")
factor_names = list(factors.keys())
coef_records = []
for date in fwd.loc[IS_START:IS_END].index[::5]:
    y = fwd.loc[date]
    if isinstance(y, pd.DataFrame):
        y = y.iloc[0]
    y = y.dropna()
    X = pd.DataFrame({fn: factors[fn].loc[date] if date in factors[fn].index else pd.Series(dtype=float)
                       for fn in factor_names})
    cs = y.index.intersection(X.dropna().index)
    if len(cs) < 100:
        continue
    y_c, X_c = y[cs], X.loc[cs].dropna()
    cs2 = y_c.index.intersection(X_c.index)
    if len(cs2) < 100:
        continue
    X_const = X_c.loc[cs2].copy()
    X_const["const"] = 1.0
    try:
        beta = np.linalg.lstsq(X_const.values, y_c[cs2].values, rcond=None)[0]
        rec = {fn: beta[i] for i, fn in enumerate(factor_names)}
        rec["date"] = date
        coef_records.append(rec)
    except Exception:
        pass

if coef_records:
    cdf = pd.DataFrame(coef_records).set_index("date")
    print(f"\n{'因子':<20} {'溢价均值':>10} {'t值':>8} {'显著':>4}")
    print("-" * 46)
    fm_sig = {}
    for fn in factor_names:
        m = cdf[fn].mean()
        t = m / (cdf[fn].std() / np.sqrt(len(cdf))) if cdf[fn].std() > 0 else 0
        sig = abs(t) > 1.65  # 放宽到 10% 显著性
        fm_sig[fn] = {"t": t, "sig": sig}
        print(f"{fn:<20} {m:>10.6f} {t:>8.2f} {'✅' if sig else '❌':>4}")

# ── 5. 因子筛选 + 组合 ──────────────────────────────────────
print("\n[5/8] 因子筛选...")

# 选择标准：IC > 0 且 ICIR > 0.15
selected = {}
for name in factors:
    ic = ic_results[name]
    if ic["ic_mean"] > 0 and ic["icir"] > 0.15:
        weight = abs(ic["icir"])
        # FM 显著的加权 bonus
        if coef_records and name in fm_sig and fm_sig[name]["sig"]:
            weight *= 1.5
        selected[name] = weight

print(f"  入选因子: {list(selected.keys())}")
print(f"  权重: {', '.join(f'{k}={v:.3f}' for k, v in selected.items())}")

# ── 6. 回测 ──────────────────────────────────────────────────
print("\n[6/8] 回测...")

def zscore_cross(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

def run_backtest(price_wide, factor_dict, weights, ind_map, n_stocks=100,
                 cost=0.003, mask=None, regime_mask=None):
    dr = price_wide.pct_change()
    tw = sum(weights.values())
    nw = {k: v / tw for k, v in weights.items()}

    composite = None
    for name, w in nw.items():
        if name not in factor_dict:
            continue
        z = zscore_cross(factor_dict[name])
        composite = z * w if composite is None else composite.add(z * w, fill_value=0)
    if composite is None:
        return pd.Series(dtype=float)
    if mask is not None:
        composite = composite.where(mask.reindex_like(composite))

    sym_ind = {s: ind_map.get(s, "unknown") for s in composite.columns}
    rebal_dates = price_wide.resample("MS").first().index
    rebal_dates = [d for d in rebal_dates if d in composite.index]

    rets, prev = [], set()
    for i, date in enumerate(rebal_dates):
        nxt = rebal_dates[i+1] if i+1 < len(rebal_dates) else price_wide.index[-1]

        if regime_mask is not None and date in regime_mask.index and not regime_mask.loc[date]:
            zero = pd.Series(0.0, index=dr.loc[date:nxt].index[1:])
            if prev and len(zero) > 0:
                zero.iloc[0] -= cost
            prev = set()
            rets.append(zero)
            continue

        scores = composite.loc[date].dropna()
        if len(scores) < n_stocks:
            continue

        # 行业中性选股
        if ind_map:
            scored = pd.DataFrame({"score": scores, "ind": [sym_ind.get(s, "unk") for s in scores.index]})
            ind_cnt = scored.groupby("ind").size()
            total = len(scored)
            quota = (ind_cnt / total * n_stocks).round().astype(int).clip(lower=1)
            picks = []
            for ind, q in quota.items():
                top = scored[scored["ind"] == ind].sort_values("score", ascending=False).head(q)
                picks.extend(top.index.tolist())
        else:
            picks = scores.sort_values(ascending=False).head(n_stocks).index.tolist()

        if not picks:
            continue

        pr = dr.loc[date:nxt, picks]
        if len(pr) > 1:
            pr = pr.iloc[1:]
        port = pr.mean(axis=1)
        new = set(picks)
        turnover = 1 - len(new & prev) / max(len(prev), 1) if prev else 1.0
        if len(port) > 0:
            port.iloc[0] -= cost * turnover
        prev = new
        rets.append(port)

    return pd.concat(rets).sort_index() if rets else pd.Series(dtype=float)

def pm(label, ret, bench=None):
    ci = ret.index.intersection(bench.index) if bench is not None else ret.index
    r = ret.loc[ci]
    ann = annualized_return(r)
    vol = annualized_volatility(r)
    sr = sharpe_ratio(r)
    mdd = max_drawdown(r)
    excess = annualized_return(r - bench.loc[ci]) if bench is not None else 0
    print(f"  {label}:")
    print(f"    年化: {ann:>+.2%} | 波动: {vol:>.2%} | 夏普: {sr:>.4f} | 回撤: {mdd:>.2%} | 超额: {excess:>+.2%}")
    return {"ann": ann, "sr": sr, "mdd": mdd}

bench_is = hs300.loc[IS_START:IS_END].pct_change().dropna()

# v4 baseline
w_v4 = {"reversal_1m": 0.31, "low_vol_20d": 0.34, "turnover_rev": 0.31, "ep": 0.22, "bp": 0.28}
strat_v4 = run_backtest(price.loc[:IS_END], factors, w_v4, ind_map, N_STOCKS,
                        mask=tradable, regime_mask=rsrs)
strat_v4 = strat_v4.loc[IS_START:]

# v5: 全因子最优组合
strat_v5 = run_backtest(price.loc[:IS_END], factors, selected, ind_map, N_STOCKS,
                        mask=tradable, regime_mask=rsrs)
strat_v5 = strat_v5.loc[IS_START:]

print("\n  === 样本内 2015-2024 ===")
pm("v4 (5因子)", strat_v4, bench_is)
m5 = pm("v5 (全因子库最优)", strat_v5, bench_is)
pm("沪深300", bench_is)

# 样本外
print("\n  === 样本外 2025 ===")
strat_v5_oos = run_backtest(price.loc[:OOS_END], factors, selected, ind_map, N_STOCKS,
                            mask=tradable, regime_mask=rsrs)
strat_v5_oos = strat_v5_oos.loc[OOS_START:]
bench_oos = hs300.loc[OOS_START:OOS_END].pct_change().dropna()
if len(strat_v5_oos) > 20:
    pm("v5 样本外", strat_v5_oos, bench_oos)
    pm("沪深300 样本外", bench_oos)

# ── 7. Walk-Forward ──────────────────────────────────────────
print("\n[7/8] Walk-Forward...")
from utils.walk_forward import walk_forward_test

def wf_fn(ps, fd, ts, te, tss, tse):
    local_fwd = ps.pct_change(5).shift(-5)
    local_ic = {}
    for fn, fac in factors.items():
        f_s = fac.reindex_like(ps).loc[ts:te]
        fw_s = local_fwd.loc[ts:te]
        ic_s = compute_ic_series(f_s, fw_s, method="spearman", min_stocks=50)
        if len(ic_s) > 10:
            m, sd = ic_s.mean(), ic_s.std()
            if m > 0 and sd > 0 and m/sd > 0.15:
                local_ic[fn] = abs(m/sd)
    if not local_ic:
        return pd.Series(dtype=float)
    local_mask = apply_tradability_filter(ps)
    r = run_backtest(ps, factors, local_ic, ind_map, N_STOCKS, mask=local_mask, regime_mask=rsrs)
    return r.loc[tss:tse] if len(r) > 0 else pd.Series(dtype=float)

try:
    wf = walk_forward_test(wf_fn, price.loc["2013-01-01":IS_END], {}, train_years=3, test_months=6)
    valid_wf = wf[wf["sharpe"].notna()]
    print(f"  窗口: {len(wf)} | 有效: {len(valid_wf)}")
    if len(valid_wf) > 0:
        print(f"  夏普均值: {valid_wf['sharpe'].mean():>.4f}")
        print(f"  收益均值: {valid_wf['total_return'].mean():>+.2%}")
        print(f"  胜率: {(valid_wf['total_return'] > 0).mean():.0%}")
        print(f"  回撤均值: {valid_wf['max_drawdown'].mean():>.2%}")
except Exception as e:
    print(f"  WF 失败: {e}")

# ── 8. 门槛 ──────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  Phase 5 门槛 (v5)")
print("=" * 65)
for name, val, ok in [
    ("年化收益 > 15%", f"{m5['ann']:>+.2%}", m5['ann'] > 0.15),
    ("夏普 > 0.8", f"{m5['sr']:>.4f}", m5['sr'] > 0.8),
    ("回撤 < 30%", f"{abs(m5['mdd']):>.2%}", abs(m5['mdd']) < 0.30),
]:
    print(f"  {'✅' if ok else '❌'} {name:<18} 实际: {val}")
print("=" * 65)
