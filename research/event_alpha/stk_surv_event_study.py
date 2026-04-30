"""
A 路第 4 候选 (last): 机构调研频次 (stk_surv) event study.

假设: 高调研家数 (fund_visitors 多) 股票后续 N 日 outperform —
机构集中调研 = 信息预演 → 后续买入压力.

数据:
- data/raw/tushare/stk_surv/stk_surv_{symbol}.parquet × 2810 per-stock
- 每行 = 一次调研记录: ts_code, surv_date, fund_visitors, rece_org, org_type
- aggregate to (surv_date, symbol) → n_surveys_today (= 当日机构调研次数)

Signal: surv_30d = 过去 30 日 sum(n_surveys), 衡量"近期调研热度"

Lookahead: surv_date 公告 (盘后), CONSERVATIVE skip overnight gap.
Cost: 双边 1.0% (n_legs=2 long-short).

执行: python research/event_alpha/stk_surv_event_study.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from utils.event_alpha_pipeline import run_3variant_pipeline  # noqa: E402
from utils.event_study import (  # noqa: E402
    compute_event_abn_returns,
    quintile_spread,
    t1_limit_mask,
)
from utils.local_data_loader import load_adj_price_wide  # noqa: E402

warnings.filterwarnings("ignore")

STK_SURV_DIR = ROOT / "data" / "raw" / "tushare" / "stk_surv"
OUT_DIR = ROOT / "research" / "event_alpha"
RESULTS_PATH = OUT_DIR / "stk_surv_event_study_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025
HORIZONS = [1, 5, 10, 20]
LIMIT_THRESHOLD = 0.095
SURV_ROLLING_DAYS = 30

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


def load_stk_surv_events() -> pd.DataFrame:
    """加载所有 stk_surv 文件, aggregate (surv_date, symbol) → n_surveys_today.

    返回: surv_date (datetime), symbol, ts_code, n_today, surv_30d (rolling sum)
    """
    files = sorted(STK_SURV_DIR.glob("stk_surv_*.parquet"))
    print(f"  [stk_surv] 扫 {len(files)} per-stock 文件...")
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=["ts_code", "surv_date"])
        if not df.empty:
            frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    print(f"  [stk_surv] 合并 raw rows: {len(raw):,}")
    raw["surv_date"] = pd.to_datetime(raw["surv_date"], format="%Y%m%d", errors="coerce")
    raw = raw.dropna(subset=["surv_date"])
    raw["symbol"] = raw["ts_code"].astype(str).str.split(".").str[0]

    # aggregate to (date, symbol) count
    agg = (raw.groupby(["surv_date", "symbol"])
           .agg(ts_code=("ts_code", "first"), n_today=("ts_code", "size"))
           .reset_index())
    print(f"  [stk_surv] (surv_date, symbol) 聚合 rows: {len(agg):,}, "
          f"日期 {agg['surv_date'].min().date()} ~ {agg['surv_date'].max().date()}")

    # rolling 30d sum per symbol
    print(f"  [stk_surv] 计算每股 rolling {SURV_ROLLING_DAYS}d sum...")
    agg = agg.sort_values(["symbol", "surv_date"]).reset_index(drop=True)
    # rolling by date: 用 set_index + groupby + rolling
    agg["surv_30d"] = (agg.set_index("surv_date")
                       .groupby("symbol")["n_today"]
                       .rolling(f"{SURV_ROLLING_DAYS}D").sum().values)
    print(f"  surv_30d 分位: P10={agg['surv_30d'].quantile(0.1):.0f}, "
          f"P50={agg['surv_30d'].quantile(0.5):.0f}, "
          f"P90={agg['surv_30d'].quantile(0.9):.0f}")
    return agg


def run() -> dict:
    print("=" * 100)
    print("机构调研 event study (Issue #58 last A 路 candidate)")
    print("=" * 100)

    print("\n[Step 1] 加载 stk_surv events")
    events = load_stk_surv_events()

    print("\n[Step 2] 价格面板")
    universe = sorted(events["symbol"].unique().tolist())
    start_date = (events["surv_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (events["surv_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")

    print("\n[Step 3] T+1 涨跌停 filter")
    events["t1_limit"] = t1_limit_mask(
        events, prices, date_col="surv_date", symbol_col="symbol",
        cat_col=None, threshold=LIMIT_THRESHOLD,
    )
    n_total = len(events)
    n_limit = events["t1_limit"].sum()
    print(f"  total {n_total:,}, T+1 涨跌停 {n_limit:,} ({n_limit/n_total:.1%})")

    print("\n[Step 4] event window 计算 (vectorized)")
    long_df = compute_event_abn_returns(
        events, prices,
        date_col="surv_date", symbol_col="symbol",
        extra_cols=["surv_30d", "t1_limit"],
        pre_days=PRE_DAYS, post_days=POST_DAYS,
    )
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    print("\n[Step 5] 全样本 spread (CONSERVATIVE)")
    full = quintile_spread(
        long_df, signal_col="surv_30d", horizons=HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=True,
    )
    for h, m in full.items():
        if m["spread_gross"] is None: continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}% t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    pipeline = run_3variant_pipeline(
        long_df,
        signal_col="surv_30d",
        limit_col="t1_limit",
        horizons=HORIZONS,
        time_slices=TIME_SLICES,
        subgroup_col=None,
        cost_per_side=COST_PER_SIDE, n_legs=2,
        candidate_name="机构调研",
        next_candidate="A 路 4 候选全死, 转方向 (C 质量改进 / D paper-trade infra)",
    )

    payload = {
        "config": {
            "n_quintiles": N_QUINTILES, "horizons": HORIZONS,
            "cost_per_side": COST_PER_SIDE, "n_legs": 2,
            "limit_threshold": LIMIT_THRESHOLD,
            "surv_rolling_days": SURV_ROLLING_DAYS,
            "skip_overnight_gap": True,
        },
        "n_events_total": int(n_events),
        "n_t1_limit_filtered": int(n_limit),
        "full_sample": full,
        **pipeline,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
