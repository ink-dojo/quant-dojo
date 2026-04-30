"""
A 路第 3 候选: 限售解禁 (share_float) event study.

假设: 大宗解禁 ann_date 后短期 supply pressure → 负 abn return, T+5~T+15 反弹.
signal: float_ratio (解禁股占总股本%), 大 = supply 大 = 预期短期负 → 反转方向.

数据:
- data/raw/tushare/share_float/{symbol}.parquet (3633 per-stock 文件)
- 字段: ts_code, ann_date, float_date, float_share, float_ratio, holder_name, share_type
- 同 (ann_date, ts_code) 多 holder 行: float_ratio 之和 (总解禁压力)

Lookahead: ann_date 公告日 (盘后), CONSERVATIVE skip overnight gap.
Cost: 双边 1.0% (n_legs=2 long-short).

Variants A/B/C + framework decision 由 utils.event_alpha_pipeline 跑.

执行: python research/event_alpha/share_float_event_study.py
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

SHARE_FLOAT_DIR = ROOT / "data" / "raw" / "tushare" / "share_float"
OUT_DIR = ROOT / "research" / "event_alpha"
RESULTS_PATH = OUT_DIR / "share_float_event_study_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025
HORIZONS = [1, 5, 10, 15]  # 加 T+15 看冷静期反弹
LIMIT_THRESHOLD = 0.095

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. 加载 share_float (per-stock parquets, 不能用 load_event_parquets)
# ─────────────────────────────────────────────────────────────

def load_share_float_events() -> pd.DataFrame:
    """加载所有 share_float 文件, 同 (ann_date, ts_code) 多 holder 取 float_ratio 之和.

    返回: ann_date (datetime), symbol (6位), ts_code, float_ratio (%总股本)
    """
    files = sorted(SHARE_FLOAT_DIR.glob("*.parquet"))
    print(f"  [share_float] 扫 {len(files)} per-stock 文件...")
    frames = []
    for f in files:
        df = pd.read_parquet(f, columns=["ts_code", "ann_date", "float_share",
                                         "float_ratio", "share_type"])
        if not df.empty:
            frames.append(df)
    raw = pd.concat(frames, ignore_index=True)
    print(f"  [share_float] 合并 raw rows: {len(raw):,}")
    raw = raw.dropna(subset=["ann_date", "float_ratio"]).drop_duplicates()
    raw["ann_date"] = pd.to_datetime(raw["ann_date"], format="%Y%m%d", errors="coerce")
    raw = raw.dropna(subset=["ann_date"])
    raw["symbol"] = raw["ts_code"].astype(str).str.split(".").str[0]

    # 同 (ann_date, symbol) 多 holder 多 record → 取 float_ratio 之和 = 总解禁压力
    agg = (raw.groupby(["ann_date", "symbol", "ts_code"])
           .agg(float_ratio=("float_ratio", "sum"))
           .reset_index())
    print(f"  [share_float] aggregate (ann_date, symbol) rows: {len(agg):,}, "
          f"日期 {agg['ann_date'].min().date()} ~ {agg['ann_date'].max().date()}")
    print(f"  float_ratio 分位 (% 总股本): "
          f"P10={agg['float_ratio'].quantile(0.1):.3f}, "
          f"P50={agg['float_ratio'].quantile(0.5):.3f}, "
          f"P90={agg['float_ratio'].quantile(0.9):.3f}")
    return agg


# ─────────────────────────────────────────────────────────────
# 2. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 100)
    print("限售解禁 event study (Issue #58, A 路第 3 候选)")
    print("=" * 100)

    # 2.1 events
    print("\n[Step 1] 加载 share_float events")
    events = load_share_float_events()

    # 2.2 价格面板
    print("\n[Step 2] 价格面板 (load_adj_price_wide)")
    universe = sorted(events["symbol"].unique().tolist())
    start_date = (events["ann_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (events["ann_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")
    if prices.empty:
        raise RuntimeError("价格面板为空")

    # 2.3 涨跌停 filter
    print("\n[Step 3] T+1 涨跌停 filter")
    events["t1_limit"] = t1_limit_mask(
        events, prices, date_col="ann_date", symbol_col="symbol",
        cat_col=None, threshold=LIMIT_THRESHOLD,
    )
    n_total = len(events)
    n_limit = events["t1_limit"].sum()
    print(f"  total {n_total:,}, T+1 涨跌停 {n_limit:,} ({n_limit/n_total:.1%})")

    # 2.4 event window
    print("\n[Step 4] event window 计算 (vectorized)")
    long_df = compute_event_abn_returns(
        events, prices,
        date_col="ann_date", symbol_col="symbol",
        extra_cols=["float_ratio", "t1_limit"],
        pre_days=PRE_DAYS, post_days=POST_DAYS,
    )
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    # 2.5 全样本 spread (Q1-Qn 反转方向: 高 float_ratio 应负 abn → Q1=低解禁多头/Qn=高解禁空头, spread 实际是 Qn-Q1, 但 quintile_spread 默认 Qn-Q1, 所以反转因子用 Q1_minus_Qn... 算了, 我们看 magnitude, 不看方向, magnitude 大就是 alpha)
    print("\n[Step 5] 全样本 spread (Qn-Q1 默认; 若反转, spread 应负)")
    full = quintile_spread(
        long_df, signal_col="float_ratio", horizons=HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=True,
    )
    for h, m in full.items():
        if m["spread_gross"] is None: continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}% t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    # 2.6 3-variant pipeline (orchestrator)
    pipeline = run_3variant_pipeline(
        long_df,
        signal_col="float_ratio",
        limit_col="t1_limit",
        horizons=HORIZONS,
        time_slices=TIME_SLICES,
        subgroup_col=None,
        cost_per_side=COST_PER_SIDE, n_legs=2,
        candidate_name="限售解禁",
        next_candidate="A 路第 4 候选 (调研突变)",
    )

    # 2.7 落盘
    payload = {
        "config": {
            "n_quintiles": N_QUINTILES, "horizons": HORIZONS,
            "cost_per_side": COST_PER_SIDE, "n_legs": 2,
            "limit_threshold": LIMIT_THRESHOLD,
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
