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
from utils.event_study import (  # noqa: E402
    compute_event_abn_returns,
    load_event_parquets,
    quintile_spread,
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
# 1. 涨跌停 next-day mask
# ─────────────────────────────────────────────────────────────

def add_t1_limit_mask(events: pd.DataFrame, prices: pd.DataFrame,
                      threshold: float = LIMIT_THRESHOLD) -> pd.Series:
    """对每事件查 T+1 raw return. 返回 bool Series (与 events 对齐), True = T+1 涨跌停 → 应剔.

    nolimit subgroup (reason_cat='nolimit') 不应用此过滤 (本无板).
    """
    td_arr = prices.index.values
    n_dates = len(td_arr)
    col_idx = {c: i for i, c in enumerate(prices.columns)}
    p_vals = prices.values

    ev_dates = pd.to_datetime(events["trade_date"]).values.astype("datetime64[ns]")
    ev_syms = events["symbol"].values
    ev_cat = events["reason_cat"].values

    i0 = np.searchsorted(td_arr, ev_dates, side="left")
    sym_idx = np.array([col_idx.get(s, -1) for s in ev_syms])

    is_limit = np.zeros(len(events), dtype=bool)
    for i in range(len(events)):
        if ev_cat[i] == "nolimit":
            continue  # 无涨跌停板, 不过滤
        if sym_idx[i] < 0 or i0[i] >= n_dates - 1 or td_arr[i0[i]] != ev_dates[i]:
            continue
        p_t = p_vals[i0[i], sym_idx[i]]
        p_t1 = p_vals[i0[i] + 1, sym_idx[i]]
        if pd.isna(p_t) or pd.isna(p_t1) or p_t == 0:
            continue
        ret_t1 = p_t1 / p_t - 1
        if abs(ret_t1) >= threshold:
            is_limit[i] = True
    return pd.Series(is_limit, index=events.index, name="t1_limit")


# ─────────────────────────────────────────────────────────────
# 2. cross-tab
# ─────────────────────────────────────────────────────────────

def cell_verdict(net: float, t_stat: float) -> str:
    if net is None or t_stat is None or pd.isna(net) or pd.isna(t_stat):
        return "N/A"
    if net <= 0:
        return "FAIL"
    if net > 0.005 and abs(t_stat) > 2:
        return "PASS"
    return "MARGINAL"


def crosstab(long_df: pd.DataFrame, label: str) -> dict:
    """对 long_df 跑 5 subgroup × 3 slice × 3 horizon = 45 cells."""
    print(f"\n  ── {label} ──")
    out: dict[str, dict[str, dict[int, dict]]] = {}
    for sg in SUBGROUPS:
        sub_sg = long_df[long_df["reason_cat"] == sg]
        if len(sub_sg) == 0:
            continue
        out[sg] = {}
        for slabel, s, e in TIME_SLICES:
            mask = ((sub_sg["event_date"] >= pd.Timestamp(s))
                    & (sub_sg["event_date"] <= pd.Timestamp(e)))
            sub = sub_sg[mask]
            sl = quintile_spread(sub, signal_col="net_rate", horizons=HORIZONS,
                                 cost_per_side=COST_PER_SIDE, n_legs=2,
                                 skip_overnight_gap=True)
            out[sg][slabel] = sl
    # 打印
    print(f"  {'subgroup':<16} {'slice':<14} | {'T+1 net':>9} {'t':>5} | "
          f"{'T+5 net':>9} {'t':>5} | {'T+10 net':>9} {'t':>5} | verdict_T+5")
    print("  " + "─" * 95)
    for sg in SUBGROUPS:
        if sg not in out:
            continue
        for slabel, _, _ in TIME_SLICES:
            cells = out[sg][slabel]
            row = f"  {sg:<16} {slabel:<14} |"
            for h in HORIZONS:
                m = cells[h]
                if m["spread_gross"] is None:
                    row += f" {'—':>9} {'—':>5} |"
                else:
                    row += f" {m['spread_net']*100:>+8.2f}% {m['t_stat']:>+5.1f} |"
            v5 = cells[5]
            verdict = cell_verdict(v5["spread_net"], v5["t_stat"])
            row += f" {verdict}"
            print(row)
    return out


# ─────────────────────────────────────────────────────────────
# 3. magnitude filter variant
# ─────────────────────────────────────────────────────────────

def filter_extreme_net_rate(long_df: pd.DataFrame, top_pct: float = 0.10) -> pd.DataFrame:
    """只保留 net_rate 绝对值 top_pct 的事件."""
    ev_rate = long_df.groupby(["symbol", "event_date"])["net_rate"].first()
    threshold = ev_rate.abs().quantile(1 - top_pct)
    extreme_keys = set(ev_rate[ev_rate.abs() >= threshold].index)
    keep_mask = long_df.set_index(["symbol", "event_date"]).index.isin(extreme_keys)
    return long_df[keep_mask].copy()


# ─────────────────────────────────────────────────────────────
# 4. 主流程
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

    # 4.2 涨跌停 filter
    print("\n[Step 2] T+1 涨跌停 filter")
    main["t1_limit"] = add_t1_limit_mask(main, prices, threshold=LIMIT_THRESHOLD)
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

    # 4.4 cross-tab variant A: 全部事件 (含 T+1 涨跌停)
    print("\n[Step 4a] CROSS-TAB A: 全部事件 (no limit filter, baseline)")
    out_a = crosstab(long_df, "全部事件 (含 T+1 涨跌停, 不可交易上界)")

    # 4.5 cross-tab variant B: 排除 T+1 涨跌停
    print("\n[Step 4b] CROSS-TAB B: 排除 T+1 涨跌停 (tradeable 子集)")
    long_b = long_df[~long_df["t1_limit"]].copy()
    out_b = crosstab(long_b, "排除 T+1 涨跌停")

    # 4.6 cross-tab variant C: 排除涨跌停 + magnitude top 10%
    print("\n[Step 4c] CROSS-TAB C: 排除涨跌停 + |net_rate| top 10%")
    long_c = filter_extreme_net_rate(long_b, top_pct=0.10)
    print(f"  filtered to top 10% extreme: {long_c.groupby(['symbol','event_date']).ngroups:,} events")
    out_c = crosstab(long_c, "排除涨跌停 + |net_rate| top 10%")

    # 4.7 LHB 方向死活判定
    print("\n" + "=" * 100)
    print("LHB 方向死活判定: 任一 subgroup × T3 PASS → 继续 Phase 3; 否则杀")
    print("=" * 100)
    decision = {"any_t3_pass": False, "winners": []}
    for variant_name, out in [("A_all", out_a), ("B_no_limit", out_b), ("C_extreme_no_limit", out_c)]:
        for sg in SUBGROUPS:
            if sg not in out: continue
            cells_t3 = out[sg].get("T3_2024_2026", {})
            for h in HORIZONS:
                m = cells_t3.get(h, {})
                if m.get("spread_gross") is None: continue
                v = cell_verdict(m["spread_net"], m["t_stat"])
                if v == "PASS":
                    decision["any_t3_pass"] = True
                    decision["winners"].append({
                        "variant": variant_name, "subgroup": sg, "horizon": h,
                        "net_spread": m["spread_net"], "t_stat": m["t_stat"],
                        "n_events": m["n_events"],
                    })
    if decision["any_t3_pass"]:
        print("\n  ✅ T3 还有 PASS cell, 继续 Phase 3 写 spec:")
        for w in decision["winners"]:
            print(f"    {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                  f"net {w['net_spread']*100:+.2f}% t={w['t_stat']:+.2f} n={w['n_events']:,}")
    else:
        print("\n  ❌ T3 全 cell FAIL/MARGINAL, **杀 LHB 方向**, 转 A 路下一个候选 (回购公告)")

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
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
