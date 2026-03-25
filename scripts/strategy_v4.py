"""
策略 v4 — 行业中性选股 + 扩股到 100 只 + RSRS 过滤

改进（相对 v3）：
  1. 行业中性：每个行业内按因子得分选 Top N，避免行业集中
  2. 持股从 30 扩到 100（降低个股风险）
  3. 基本面因子（EP/BP）通过 CSV 列直接读取（不走慢的 load_factor_wide）
  4. Fama-MacBeth 截面回归验证因子显著性
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
from utils.market_regime import rsrs_regime_mask

IS_START, IS_END = "2015-01-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2025-12-31"
N_STOCKS = 100

print("=" * 65)
print("  策略 v4 — 行业中性 + 基本面 + 100 只 + RSRS")
print("=" * 65)

# ── 1. 数据 ──────────────────────────────────────────────────
print("\n[1/6] 加载数据...")
t0 = time.time()
symbols = get_all_symbols()
price = load_price_wide(symbols, "2013-01-01", OOS_END, field="close")

hs300_full = get_index_history(symbol="sh000300", start="2013-01-01", end=OOS_END)
hs300 = hs300_full["close"]
common = price.index.intersection(hs300.index)
price, hs300 = price.loc[common], hs300.loc[common]
valid = price.columns[price.notna().sum() > 500]
price = price[valid]

# PE/PB 从预缓存的宽表读取（由 scripts/cache_valuation.py 生成）
_cache_dir = Path(__file__).parent.parent / "data" / "cache"
pe = pd.read_parquet(_cache_dir / "pe_ttm_wide.parquet")
pb = pd.read_parquet(_cache_dir / "pb_wide.parquet")
# 对齐到 price 的日期和股票
pe = pe.reindex(index=price.index, columns=valid).loc[common]
pb = pb.reindex(index=price.index, columns=valid).loc[common]

print(f"  股票: {len(valid)} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")

tradable = apply_tradability_filter(price)
rsrs = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])

# 行业数据
ind_df = pd.read_csv("/Users/karan/Documents/GitHub/quant-dojo/data/raw/industry_baostock.csv")
# code 格式 sh.600000 → 600000
ind_df["symbol"] = ind_df["code"].str.split(".").str[1]
ind_map = dict(zip(ind_df["symbol"], ind_df["industry"]))
print(f"  行业分类: {len(ind_map)} 只, {ind_df['industry'].nunique()} 个行业")

# ── 2. 因子构建 ──────────────────────────────────────────────
print("\n[2/6] 构建因子...")
daily_ret = price.pct_change()

factors = {}
factors["reversal_1m"] = -price.pct_change(21)
factors["low_vol_20d"] = -daily_ret.rolling(20).std()
factors["turnover_rev"] = -daily_ret.abs().rolling(20).mean()

# 基本面因子
ep = (1.0 / pe.where(pe > 0)).reindex_like(price)
bp = (1.0 / pb.where(pb > 0)).reindex_like(price)
factors["ep"] = ep
factors["bp"] = bp

print(f"  因子: {list(factors.keys())}")
print(f"  EP 覆盖率: {ep.loc[IS_START:IS_END].notna().mean().mean():.1%}")
print(f"  BP 覆盖率: {bp.loc[IS_START:IS_END].notna().mean().mean():.1%}")

# ── 3. IC 分析 ───────────────────────────────────────────────
print("\n[3/6] 因子 IC...")
fwd = price.pct_change(5).shift(-5)

ic_results = {}
print(f"\n{'因子':<20} {'IC均值':>8} {'ICIR':>8} {'判断':>6}")
print("-" * 45)
for name, fac in factors.items():
    ic_s = compute_ic_series(fac.loc[IS_START:IS_END], fwd.loc[IS_START:IS_END],
                             method="spearman", min_stocks=50)
    with contextlib.redirect_stdout(io.StringIO()):
        s = ic_summary(ic_s, name=name)
    ic_mean, icir = s["IC_mean"], s.get("ICIR", 0) or 0
    verdict = "✅" if pd.notna(ic_mean) and ic_mean > 0 and abs(icir) > 0.2 else "❌"
    print(f"{name:<20} {ic_mean:>8.4f} {icir:>8.4f} {verdict:>6}")
    ic_results[name] = {"ic_mean": ic_mean if pd.notna(ic_mean) else 0, "icir": icir}

# ── 4. Fama-MacBeth ──────────────────────────────────────────
print("\n[4/6] Fama-MacBeth 回归...")
factor_names = list(factors.keys())
coef_records = []
for date in fwd.loc[IS_START:IS_END].index[::5]:
    y = fwd.loc[date]
    if isinstance(y, pd.DataFrame):
        y = y.iloc[0]
    y = y.dropna()
    X = pd.DataFrame({fn: factors[fn].loc[date] for fn in factor_names if date in factors[fn].index})
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
    print(f"\n{'因子':<20} {'溢价均值':>10} {'t值':>8} {'显著':>6}")
    print("-" * 48)
    for fn in factor_names:
        m = cdf[fn].mean()
        t = m / (cdf[fn].std() / np.sqrt(len(cdf))) if cdf[fn].std() > 0 else 0
        print(f"{fn:<20} {m:>10.6f} {t:>8.2f} {'✅' if abs(t) > 2 else '❌':>6}")

# ── 5. 回测 ──────────────────────────────────────────────────
print("\n[5/6] 回测...")

def zscore_cross(df):
    return df.sub(df.mean(axis=1), axis=0).div(df.std(axis=1), axis=0)

def run_industry_neutral_backtest(price_wide, factor_dict, weights, ind_map,
                                  n_stocks=100, cost=0.003, mask=None, regime_mask=None):
    """行业中性选股回测：每个行业内按合成得分选 Top N"""
    dr = price_wide.pct_change()
    tw = sum(weights.values())
    nw = {k: v / tw for k, v in weights.items()}

    # 合成因子
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

    # 构建 symbol → industry 映射
    sym_ind = {s: ind_map.get(s, "unknown") for s in composite.columns}

    rebal_dates = price_wide.resample("MS").first().index
    rebal_dates = [d for d in rebal_dates if d in composite.index]

    rets, prev_picks = [], set()

    for i, date in enumerate(rebal_dates):
        nxt = rebal_dates[i + 1] if i + 1 < len(rebal_dates) else price_wide.index[-1]

        # RSRS 过滤
        if regime_mask is not None and date in regime_mask.index and not regime_mask.loc[date]:
            zero = pd.Series(0.0, index=dr.loc[date:nxt].index[1:])
            if prev_picks and len(zero) > 0:
                zero.iloc[0] -= cost
            prev_picks = set()
            rets.append(zero)
            continue

        scores = composite.loc[date].dropna()
        if len(scores) < n_stocks:
            continue

        # 行业中性选股：每个行业选 top K，按行业股票数量等比分配名额
        scored = pd.DataFrame({"score": scores, "industry": [sym_ind.get(s, "unknown") for s in scores.index]})
        ind_counts = scored.groupby("industry").size()
        total_scored = len(scored)
        # 每个行业的名额 = 行业股票数 / 总数 × n_stocks（四舍五入，保证总数 ≈ n_stocks）
        ind_quota = (ind_counts / total_scored * n_stocks).round().astype(int).clip(lower=1)

        picks = []
        for ind, quota in ind_quota.items():
            ind_stocks = scored[scored["industry"] == ind].sort_values("score", ascending=False)
            picks.extend(ind_stocks.head(quota).index.tolist())

        if len(picks) == 0:
            continue

        pr = dr.loc[date:nxt, picks]
        if len(pr) > 1:
            pr = pr.iloc[1:]
        port = pr.mean(axis=1)

        new_picks = set(picks)
        turnover = 1 - len(new_picks & prev_picks) / max(len(prev_picks), 1) if prev_picks else 1.0
        if len(port) > 0:
            port.iloc[0] -= cost * turnover
        prev_picks = new_picks
        rets.append(port)

    return pd.concat(rets).sort_index() if rets else pd.Series(dtype=float)

def print_metrics(label, ret, bench=None):
    ci = ret.index.intersection(bench.index) if bench is not None else ret.index
    r = ret.loc[ci]
    print(f"\n  {label}:")
    print(f"    年化收益: {annualized_return(r):>+.2%}")
    print(f"    年化波动: {annualized_volatility(r):>.2%}")
    print(f"    夏普比率: {sharpe_ratio(r):>.4f}")
    print(f"    最大回撤: {max_drawdown(r):>.2%}")
    if bench is not None:
        b = bench.loc[ci]
        print(f"    年化超额: {annualized_return(r - b):>+.2%}")

# 选有效因子
good = {k: abs(v["icir"]) for k, v in ic_results.items() if v["ic_mean"] > 0 and v["icir"] > 0.2}
print(f"  v4 因子: {list(good.keys())}")
print(f"  v4 权重: {', '.join(f'{k}={v:.3f}' for k, v in good.items())}")

bench_is = hs300.loc[IS_START:IS_END].pct_change().dropna()

# v3 baseline（无行业中性，30 只）
w_v3 = {"reversal_1m": 0.31, "low_vol_20d": 0.33, "turnover_rev": 0.30}
strat_v3 = run_industry_neutral_backtest(
    price.loc[:IS_END], factors, w_v3, {},  # 空 ind_map = 不做行业中性
    n_stocks=30, mask=tradable, regime_mask=rsrs,
)
strat_v3 = strat_v3.loc[IS_START:]

# v4（行业中性 + 基本面 + 100 只）
strat_v4 = run_industry_neutral_backtest(
    price.loc[:IS_END], factors, good, ind_map,
    n_stocks=N_STOCKS, mask=tradable, regime_mask=rsrs,
)
strat_v4 = strat_v4.loc[IS_START:]

print_metrics("v3 (3因子, 30只, 无行业中性)", strat_v3, bench_is)
print_metrics("v4 (行业中性+基本面, 100只)", strat_v4, bench_is)
print_metrics("沪深300", bench_is)

# 样本外
print("\n  === 样本外 ===")
strat_v4_oos = run_industry_neutral_backtest(
    price.loc[:OOS_END], factors, good, ind_map,
    n_stocks=N_STOCKS, mask=tradable, regime_mask=rsrs,
)
strat_v4_oos = strat_v4_oos.loc[OOS_START:]
bench_oos = hs300.loc[OOS_START:OOS_END].pct_change().dropna()
if len(strat_v4_oos) > 20:
    print_metrics("v4 样本外", strat_v4_oos, bench_oos)
    print_metrics("沪深300 样本外", bench_oos)

# ── 6. 门槛 ──────────────────────────────────────────────────
print("\n" + "=" * 65)
print("  Phase 5 门槛 (v4)")
print("=" * 65)
ann = annualized_return(strat_v4)
sr = sharpe_ratio(strat_v4)
mdd = max_drawdown(strat_v4)
for name, val, ok in [
    ("年化收益 > 15%", f"{ann:>+.2%}", ann > 0.15),
    ("夏普 > 0.8", f"{sr:>.4f}", sr > 0.8),
    ("回撤 < 30%", f"{abs(mdd):>.2%}", abs(mdd) < 0.30),
]:
    print(f"  {'✅' if ok else '❌'} {name:<18} 实际: {val}")
print("=" * 65)
