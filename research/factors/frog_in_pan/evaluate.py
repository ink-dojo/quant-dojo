"""
Frog-in-the-Pan 因子 IC 评估 — pre-reg 锁定参数。

锁定参数（不调）:
    lookback = 250, skip = 21
    universe = 全 A 主板（剔除 ST/新股/停牌）
    window = 2018-01-01 ~ 2025-12-31（含 warmup）
    analysis = 2019-01-01 ~ 2025-12-31
    fwd_days = 1, 5, 10, 20
    method = spearman (Rank IC)
    min_stocks_per_day = 500

通过/拒绝标准：
    - IC 均值 ≥ 0.02（fwd=1）且 t-stat ≥ 3 → 继续
    - 否则 Kill
"""
from __future__ import annotations
import sys
from pathlib import Path
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research.factors.frog_in_pan.factor import compute_fip
from utils.factor_analysis import compute_ic_series, ic_summary
from utils.listing_metadata import universe_at_date


PRICE_PATH = ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
ANALYSIS_START = "2019-01-01"
ANALYSIS_END = "2025-12-31"
WARMUP_START = "2017-06-01"
FWD_LIST = [1, 5, 10, 20]


def load_prices() -> pd.DataFrame:
    close = pd.read_parquet(PRICE_PATH)
    close.index = pd.to_datetime(close.index)
    return close.loc[WARMUP_START:ANALYSIS_END]


def apply_universe_filter(close: pd.DataFrame) -> pd.DataFrame:
    """剔除上市不满 1 年 + ST + 停牌(超 10 天无量)。"""
    keep_cols = []
    for sym in close.columns:
        # 主板过滤：排除 688xxx (科创板) 和 30xxxx (创业板)
        if sym.startswith(("688", "300", "301")):
            continue
        keep_cols.append(sym)
    close = close[keep_cols]
    # 停牌：连续 NaN > 10 视为停牌期，整列若 > 50% NaN 剔除
    nan_ratio = close.isna().mean()
    close = close.loc[:, nan_ratio < 0.5]
    return close


def run():
    print(f"[1/4] loading prices from {PRICE_PATH.name}")
    close = load_prices()
    print(f"    raw shape: {close.shape}")

    print("[2/4] applying universe filter (主板 + 停牌剔除)")
    close = apply_universe_filter(close)
    print(f"    after filter: {close.shape}")

    print("[3/4] computing Frog-in-the-Pan factor (lookback=250, skip=21)")
    fip = compute_fip(close, lookback=250, skip=21)
    valid_fip = fip.loc[ANALYSIS_START:].dropna(how="all")
    print(f"    analysis window: {valid_fip.index[0].date()} ~ {valid_fip.index[-1].date()}")
    print(f"    coverage: avg {valid_fip.notna().sum(axis=1).mean():.0f} stocks/day")

    print("[4/4] IC evaluation across fwd horizons")
    daily_ret = close.pct_change()
    results = []
    for fwd in FWD_LIST:
        fwd_ret = daily_ret.shift(-fwd).rolling(fwd).sum()
        fwd_ret = fwd_ret.loc[ANALYSIS_START:ANALYSIS_END]
        fip_win = fip.loc[ANALYSIS_START:ANALYSIS_END]
        ic = compute_ic_series(fip_win, fwd_ret, method="spearman", min_stocks=500)
        print(f"\n--- fwd={fwd}d ---")
        summary = ic_summary(ic, name=f"FiP fwd={fwd}", fwd_days=fwd, verbose=True)
        results.append({
            "fwd": fwd,
            "ic_mean": summary["IC_mean"],
            "icir": summary.get("ICIR"),
            "t_stat": summary.get("t_stat"),
            "t_hac": summary.get("t_stat_hac"),
            "pct_pos": summary.get("pct_pos"),
            "n_days": summary["n"],
        })

    res_df = pd.DataFrame(results)
    out_path = Path(__file__).parent / "ic_results.csv"
    res_df.to_csv(out_path, index=False)
    print(f"\nsaved → {out_path}")
    print(res_df.to_string(index=False))

    # Kill criterion
    fwd1 = res_df.query("fwd == 1").iloc[0]
    passed = abs(fwd1["ic_mean"]) >= 0.02 and abs(fwd1["t_stat"]) >= 3.0
    verdict = "PASS" if passed else "KILL"
    print(f"\n=== VERDICT (fwd=1): {verdict} ===")
    print(f"    IC mean {fwd1['ic_mean']:+.4f} (gate: |IC| ≥ 0.02)")
    print(f"    t-stat  {fwd1['t_stat']:+.2f} (gate: |t| ≥ 3.0)")
    return res_df, verdict


if __name__ == "__main__":
    run()
