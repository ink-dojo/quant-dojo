"""
LHB Phase 2: subgroup × time slice cross-tab + 涨跌停 next-day filter (Issue #56).

A 路决策点: 全样本 T+5 net +7.8% 但 T3 (2024-26) 已 FAIL. 这个脚本看
reason subgroup 在 T3 是否仍有 alpha, 决定 LHB 方向死活.

cross-tab:
  5 reason subgroup (multi_day / daily_up / daily_down / daily_turnover / nolimit)
  × 3 time slice (T1 2015-19 / T2 2020-23 / T3 2024-26)
  × 3 horizon (T+1 / T+5 / T+10)

  外加 magnitude filter (top 10% extreme net_rate events) variant + 涨跌停 filter.

涨跌停 next-day filter:
  Q5 大 net_rate 股票 T+1 大概率仍涨停, 实际不可入场. 过滤逻辑:
  对每事件, 查 prices[T+1] / prices[T] - 1, 若 >= 0.095 (主板 9.5%) → drop.
  这是 conservative 上界估计 (创业板/科创板 阈值更高 0.195, 暂统一用 0.095
  避免漏剔; nolimit 子集本来就没涨跌停板, 不过滤).

判定门 (cell-level):
  PASS     : net spread > 0.5% AND t > 2
  MARGINAL : 0 < net <= 0.5% OR (net > 0.5% AND t <= 2)
  FAIL     : net <= 0

LHB 方向死活:
  任一 (subgroup, T3) PASS → 继续 Phase 3 写 spec
  否则 → 杀 LHB 转下一个事件 (回购公告)

执行: python research/event_alpha/lhb_phase2_crosstab.py
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

from research.event_alpha.lhb_t1_event_study import (  # noqa: E402
    aggregate_per_event,
    EVENTS_DIR,
    OUT_DIR,
)
from utils.event_alpha_pipeline import run_3variant_pipeline  # noqa: E402
from utils.event_study import (  # noqa: E402
    compute_event_abn_returns,
    load_event_parquets,
    t1_limit_mask,
)
from utils.local_data_loader import load_adj_price_wide  # noqa: E402

warnings.filterwarnings("ignore")

RESULTS_PATH = OUT_DIR / "lhb_phase2_crosstab_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025
HORIZONS = [1, 5, 10]
SUBGROUPS = ["multi_day", "daily_up", "daily_down", "daily_turnover", "nolimit"]

# 涨跌停板阈值. 主板 ±10%, 实际盘中可能 9.99%, 用 0.095 留保守 buffer.
# nolimit 子集本来无板, 不过滤; 创业板/科创板 0.20 但 0.095 也会误剔, 这是
# 已知 trade-off — Phase 2 优先 conservative (宁可漏好事件不要假阳性).
LIMIT_THRESHOLD = 0.095

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. 涨跌停 next-day mask — 已下沉到 utils.event_study.t1_limit_mask (vectorized)
# ─────────────────────────────────────────────────────────────


# ─────────────────────────────────────────────────────────────
# 2. 主流程 — cross-tab + framework decision 由 utils.event_alpha_pipeline 跑
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 100)
    print("LHB Phase 2: subgroup × time slice cross-tab + 涨跌停过滤 (Issue #56)")
    print("=" * 100)

    # 4.1 events + price (复用 Phase 1 路径)
    print("\n[Step 1] 加载 events + 价格")
    raw = load_event_parquets(
        prefix="top_list", events_dir=EVENTS_DIR,
        columns=["trade_date", "ts_code", "reason", "net_amount", "net_rate"],
    )
    main = aggregate_per_event(raw)
    print(f"  events 主信号 rows: {len(main):,}")

    universe = sorted(main["symbol"].dropna().unique().tolist())
    start_date = (main["trade_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (main["trade_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")

    # 4.2 涨跌停 filter (vectorized 自 utils.event_study)
    print("\n[Step 2] T+1 涨跌停 filter")
    main["t1_limit"] = t1_limit_mask(main, prices, threshold=LIMIT_THRESHOLD)
    n_total = len(main)
    n_limit = main["t1_limit"].sum()
    print(f"  total {n_total:,} events, T+1 涨跌停 {n_limit:,} ({n_limit/n_total:.1%}) — 将被过滤")
    print(f"  按 reason 涨跌停占比:")
    for cat in SUBGROUPS:
        sub = main[main["reason_cat"] == cat]
        if len(sub) == 0: continue
        n_lim = sub["t1_limit"].sum()
        print(f"    {cat:<16}: {n_lim:>5}/{len(sub):>5} ({n_lim/len(sub):.1%})")

    # 4.3 abn return event window (一次, 给所有 cross-tab 共享)
    print("\n[Step 3] event window 计算 (vectorized)")
    main_ev = main.rename(columns={"trade_date": "event_date"})
    long_df = compute_event_abn_returns(
        main_ev, prices,
        date_col="event_date", symbol_col="symbol",
        extra_cols=["net_rate", "reason_cat", "t1_limit"],
        pre_days=PRE_DAYS, post_days=POST_DAYS,
    )
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    # 4.4 3-variant cross-tab + framework decision (orchestrator)
    pipeline = run_3variant_pipeline(
        long_df,
        signal_col="net_rate",
        limit_col="t1_limit",
        horizons=HORIZONS,
        time_slices=TIME_SLICES,
        subgroup_col="reason_cat",
        subgroups=SUBGROUPS,
        cost_per_side=COST_PER_SIDE, n_legs=2,
        candidate_name="LHB",
        next_candidate="A 路下一个候选 (回购公告 / 减持冷静期 / 调研突变)",
    )
    out_a = pipeline["variant_A_all"]
    out_b = pipeline["variant_B_no_limit"]
    out_c = pipeline["variant_C_extreme_no_limit"]
    decision = pipeline["decision"]

    # 4.8 落盘
    payload = {
        "config": {
            "n_quintiles": N_QUINTILES, "horizons": HORIZONS,
            "cost_per_side": COST_PER_SIDE, "n_legs": 2,
            "limit_threshold": LIMIT_THRESHOLD,
            "subgroups": SUBGROUPS,
        },
        "n_events_total": int(n_events),
        "n_t1_limit_filtered": int(n_limit),
        "variant_A_all": out_a,
        "variant_B_no_limit": out_b,
        "variant_C_extreme_no_limit": out_c,
        "decision": decision,
        # 旧字段 alias 兼容曾经读 any_t3_pass 的 caller (字段名 oos_pass_cells, alias 留)
        "decision_legacy": {"any_t3_pass": bool(decision["oos_pass_cells"]),
                            "winners": decision["oos_pass_cells"]},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
