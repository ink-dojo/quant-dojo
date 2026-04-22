"""
Asset Growth 异常 IC 评估 — pre-reg 锁定参数。

锁定:
    universe = 全 A 主板（剔除 688/30x 创业/科创 + 停牌），financial panel 能算 AG
    window   = 2018-01-01 ~ 2025-12-31 (analysis)
    fwd_days = 1, 5, 10, 20
    method   = spearman Rank IC
    min_stocks_per_day = 300

预期：
    IC 为负（AG 高 → 下期收益低），fwd=20d |IC| > 0.02 且 t > 3 → PASS

Kill:
    fwd=1d 和 fwd=20d 都 |t| < 2 → KILL
"""
from __future__ import annotations
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import pandas as pd
from tqdm import tqdm

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research.factors.asset_growth.factor import compute_ag_panel, broadcast_to_daily
from utils.factor_analysis import compute_ic_series, ic_summary


PRICE_PATH = ROOT / "data/processed/price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
BS_DIR = ROOT / "data/raw/tushare/financial"
ANALYSIS_START = "2018-01-01"
ANALYSIS_END = "2025-12-31"
FWD_LIST = [1, 5, 10, 20]


def read_one_bs(path: Path) -> tuple[str, pd.DataFrame] | None:
    try:
        df = pd.read_parquet(path, columns=["ts_code", "ann_date", "end_date", "report_type", "total_assets"])
        if df.empty:
            return None
        # symbol = 去掉 .SZ/.SH 后缀
        sym = df["ts_code"].iloc[0].split(".")[0]
        return sym, df
    except Exception:
        return None


def load_balance_sheets() -> dict[str, pd.DataFrame]:
    files = sorted(BS_DIR.glob("balancesheet_*.parquet"))
    print(f"[1/5] loading {len(files)} balance sheets (parallel)...")
    bs = {}
    with ThreadPoolExecutor(max_workers=16) as ex:
        for result in tqdm(ex.map(read_one_bs, files), total=len(files), ncols=80):
            if result is None:
                continue
            sym, df = result
            bs[sym] = df
    print(f"    loaded {len(bs)} symbols")
    return bs


def apply_universe_filter(close: pd.DataFrame) -> pd.DataFrame:
    keep_cols = [c for c in close.columns if not c.startswith(("688", "300", "301"))]
    close = close[keep_cols]
    nan_ratio = close.isna().mean()
    return close.loc[:, nan_ratio < 0.5]


def run():
    print(f"[0/5] loading prices")
    close = pd.read_parquet(PRICE_PATH)
    close.index = pd.to_datetime(close.index)
    close = close.loc[ANALYSIS_START:ANALYSIS_END]
    close = apply_universe_filter(close)
    print(f"    price panel: {close.shape}")

    bs = load_balance_sheets()

    print("[2/5] computing AG (yoy) from annual reports")
    ag_wide = compute_ag_panel(bs)
    print(f"    AG wide: {ag_wide.shape}")
    # align columns
    common = [c for c in close.columns if c in ag_wide.columns]
    ag_wide = ag_wide[common]
    close = close[common]
    print(f"    aligned symbols: {len(common)}")

    print("[3/5] broadcasting AG to daily (T+1 信号)")
    ag_daily = broadcast_to_daily(ag_wide, close.index)
    cov = ag_daily.notna().sum(axis=1)
    print(f"    coverage: median {cov.median():.0f} stocks/day, last {cov.iloc[-1]:.0f}")

    print("[4/5] IC evaluation")
    daily_ret = close.pct_change()
    results = []
    for fwd in FWD_LIST:
        fwd_ret = daily_ret.shift(-fwd).rolling(fwd).sum()
        ic = compute_ic_series(ag_daily, fwd_ret, method="spearman", min_stocks=300)
        print(f"\n--- fwd={fwd}d ---")
        summary = ic_summary(ic, name=f"AG fwd={fwd}", fwd_days=fwd, verbose=True)
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

    print("\n[5/5] verdict")
    fwd20 = res_df.query("fwd == 20").iloc[0]
    fwd1 = res_df.query("fwd == 1").iloc[0]
    passed = abs(fwd20["ic_mean"]) >= 0.02 and abs(fwd20["t_stat"]) >= 3.0
    verdict = "PASS" if passed else "KILL"
    print(f"=== VERDICT (fwd=20d): {verdict} ===")
    print(f"    IC mean {fwd20['ic_mean']:+.4f} (gate: |IC| ≥ 0.02)")
    print(f"    t-stat  {fwd20['t_stat']:+.2f} (gate: |t| ≥ 3.0)")
    print(f"    expected direction: negative (high AG → low return)")
    return res_df, verdict


if __name__ == "__main__":
    run()
