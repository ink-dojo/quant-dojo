"""
A 路第二候选: 回购公告 (预案) event study (rev 2 — 抽 pipeline + 修 unit bug + vectorize).

假设: 公司宣布回购预案后, 后续 N 日累计 abn return 显著正?
signal: amount_to_mv = 计划回购金额 / 流通市值 (统一到万元)

数据:
- data/raw/tushare/repurchase.parquet (95k 行 2015-2026)
- proc 状态 8 类: 预案 26.5k / 股东大会通过 12k / 实施 32k / 完成 24k / 提议 0.9k / 停止 0.09k / 未通过 0.03k / 失效 0.012k
- 本 study 只用 proc='预案'

Lookahead: ann_date 假设盘后披露, T+1 close 后入. CONSERVATIVE.
Cost: 双边 1.0% (n_legs=2 long-short).

Variants A/B/C + framework decision 全部由 utils.event_alpha_pipeline 跑.

执行: python research/event_alpha/repurchase_event_study.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
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

REPURCHASE_PARQUET = ROOT / "data" / "raw" / "tushare" / "repurchase.parquet"
DAILY_BASIC_DIR = ROOT / "data" / "raw" / "tushare" / "daily_basic"
OUT_DIR = ROOT / "research" / "event_alpha"
RESULTS_PATH = OUT_DIR / "repurchase_event_study_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025
HORIZONS = [1, 5, 10]
LIMIT_THRESHOLD = 0.095

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. 加载 repurchase + circ_mv (vectorized)
# ─────────────────────────────────────────────────────────────

def load_repurchase_announcements() -> pd.DataFrame:
    """加载 proc='预案', 同 (ann_date, ts_code) 取 amount 最大."""
    df = pd.read_parquet(REPURCHASE_PARQUET)
    proposals = df[df["proc"] == "预案"].copy()
    proposals["ann_date"] = pd.to_datetime(proposals["ann_date"], format="%Y%m%d", errors="coerce")
    proposals = proposals.dropna(subset=["ann_date", "amount"])
    proposals = proposals[proposals["amount"] > 0]
    proposals["symbol"] = proposals["ts_code"].astype(str).str.split(".").str[0]
    proposals = (proposals.sort_values("amount", ascending=False)
                 .drop_duplicates(subset=["ann_date", "symbol"], keep="first")
                 .reset_index(drop=True))
    print(f"  [回购] 预案 events: {len(proposals):,}, "
          f"日期 {proposals['ann_date'].min().date()} ~ {proposals['ann_date'].max().date()}, "
          f"symbols: {proposals['symbol'].nunique():,}")
    return proposals[["ann_date", "symbol", "ts_code", "amount"]]


def load_circ_mv_vectorized(events: pd.DataFrame) -> pd.Series:
    """对每事件查 asof ≤ ann_date 的 circ_mv (单位万元), vectorized fancy-index.

    Replaces iterrows + s.asof per-row anti-pattern (Phase 1/2 已学过 2 次).
    返回 pd.Series, 与 events 同 index. 缺失为 NaN.
    """
    syms = events["symbol"].unique()
    print(f"  [circ_mv] vectorized 查 {len(syms):,} symbols...")
    series_dict: dict[str, pd.Series] = {}
    for sym in syms:
        path = DAILY_BASIC_DIR / f"{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["trade_date", "circ_mv"])
        if df.empty:
            continue
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        series_dict[sym] = df.set_index("trade_date")["circ_mv"]
    if not series_dict:
        return pd.Series(np.nan, index=events.index, dtype=float)

    mv_wide = pd.DataFrame(series_dict).sort_index()
    dates_arr = mv_wide.index.values  # sorted datetime64[ns]
    sym_to_col = {s: i for i, s in enumerate(mv_wide.columns)}
    mat = mv_wide.values  # (n_dates, n_syms), NaN where missing

    ann = pd.to_datetime(events["ann_date"]).values.astype("datetime64[ns]")
    date_idx = np.searchsorted(dates_arr, ann, side="right") - 1
    sym_idx_raw = events["symbol"].map(sym_to_col)
    sym_idx = sym_idx_raw.fillna(-1).astype(int).values
    valid = (date_idx >= 0) & (sym_idx >= 0)

    out = np.full(len(events), np.nan, dtype=float)
    if valid.any():
        out[valid] = mat[date_idx[valid], sym_idx[valid]]
    n_have = np.isfinite(out).sum()
    print(f"  [circ_mv] 命中 {n_have:,}/{len(events):,} ({n_have/len(events):.1%})")
    return pd.Series(out, index=events.index, dtype=float)


# ─────────────────────────────────────────────────────────────
# 2. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 100)
    print("回购预案 event study (Issue #57, A 路第 2 候选, rev 2)")
    print("=" * 100)

    # 2.1 events
    print("\n[Step 1] 加载预案 events")
    events = load_repurchase_announcements()

    # 2.2 circ_mv → signal (修 unit bug: amount 元 / circ_mv 万元 → 都转万元)
    print("\n[Step 2] 加载 circ_mv 算 amount_to_mv signal")
    events["circ_mv"] = load_circ_mv_vectorized(events)
    events = events.dropna(subset=["circ_mv"]).copy()
    # rev 2 修: amount 单位 元, circ_mv 单位 万元. 转成 amount_万元 / circ_mv_万元
    # = 真实 ratio (回购金额占流通市值的比例). rev 1 没转, ratio 大 10000x,
    # 不影响 quintile 排序但 journal 描述 "0~1 范围" 是错的.
    events["amount_to_mv"] = (events["amount"] / 1e4) / events["circ_mv"]
    print(f"  events with valid signal: {len(events):,}")
    print(f"  amount_to_mv 真实分位 (回购金额占流通市值比例):")
    print(f"    P10={events['amount_to_mv'].quantile(0.1):.4%}, "
          f"P50={events['amount_to_mv'].quantile(0.5):.4%}, "
          f"P90={events['amount_to_mv'].quantile(0.9):.4%}")

    # 2.3 价格面板
    print("\n[Step 3] 价格面板")
    universe = sorted(events["symbol"].unique().tolist())
    start_date = (events["ann_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (events["ann_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")
    if prices.empty:
        raise RuntimeError("价格面板为空")

    # 2.4 涨跌停 filter
    print("\n[Step 4] T+1 涨跌停 filter")
    events["t1_limit"] = t1_limit_mask(
        events, prices, date_col="ann_date", symbol_col="symbol",
        cat_col=None, threshold=LIMIT_THRESHOLD,
    )
    n_total = len(events)
    n_limit = events["t1_limit"].sum()
    print(f"  total {n_total:,}, T+1 涨跌停 {n_limit:,} ({n_limit/n_total:.1%})")

    # 2.5 event window
    print("\n[Step 5] event window 计算 (vectorized)")
    long_df = compute_event_abn_returns(
        events, prices,
        date_col="ann_date", symbol_col="symbol",
        extra_cols=["amount_to_mv", "t1_limit"],
        pre_days=PRE_DAYS, post_days=POST_DAYS,
    )
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    # 2.6 全样本 spread
    print("\n[Step 6] 全样本 spread (CONSERVATIVE)")
    full = quintile_spread(
        long_df, signal_col="amount_to_mv", horizons=HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=True,
    )
    for h, m in full.items():
        if m["spread_gross"] is None: continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}% t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    # 2.7 3-variant cross-tab + framework decision (orchestrator)
    pipeline = run_3variant_pipeline(
        long_df,
        signal_col="amount_to_mv",
        limit_col="t1_limit",
        horizons=HORIZONS,
        time_slices=TIME_SLICES,
        subgroup_col=None,
        cost_per_side=COST_PER_SIDE, n_legs=2,
        candidate_name="回购预案",
        next_candidate="A 路第 3 候选 (减持冷静期)",
    )

    # 2.8 落盘
    payload = {
        "config": {
            "n_quintiles": N_QUINTILES, "horizons": HORIZONS,
            "cost_per_side": COST_PER_SIDE, "n_legs": 2,
            "limit_threshold": LIMIT_THRESHOLD,
            "skip_overnight_gap": True, "rev": 2,
            "amount_to_mv_unit_fix": "amount(元)/1e4 then divide circ_mv(万元) → 真实 ratio",
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
