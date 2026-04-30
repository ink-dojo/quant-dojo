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
    cell_verdict,
    compute_event_abn_returns,
    framework_strict_decision,
    load_event_parquets,
    quintile_spread,
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
# 2. cross-tab — cell_verdict + framework_strict_decision 已下沉到 utils.event_study
# ─────────────────────────────────────────────────────────────


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

    # 4.7 LHB 方向死活判定 — 严格按 framework Live-Tier 1 全切片门
    print("\n" + "=" * 100)
    print("LHB 方向死活判定 (framework Live-Tier 1 严格门)")
    print("=" * 100)
    # framework 严格判定**仅对 tradeable variants** (B/C). A_all 含涨跌停板, 是
    # 不可执行的上界, 入选 framework_pass 等于把"仅在涨停板里的 alpha"包装成
    # 真候选, 误读危险. 只把 B + C 喂给严格判定.
    decision = framework_strict_decision(
        {"B_no_limit": out_b, "C_extreme_no_limit": out_c},
        horizons=HORIZONS,
        oos_slice_label="T3_2024_2026",
        is_slice_labels=("T1_2015_2019", "T2_2020_2023"),
    )
    print(f"\n  OOS (T3) PASS cell 数: {len(decision['oos_pass_cells'])} (loose 判定, 仅参考)")
    for w in decision["oos_pass_cells"][:5]:
        print(f"    [loose] {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
              f"net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,}")
    print(f"\n  Framework PASS (T3 PASS + IS slice 不 FAIL 或失败窗 < 0.3% NAV): "
          f"{len(decision['framework_pass'])}")
    if decision["framework_pass"]:
        print("\n  ✅ 有 framework PASS 候选, 继续 Phase 3 写 spec:")
        for w in decision["framework_pass"]:
            print(f"    {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                  f"T3 net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,} "
                  f"worst slice drag {w['worst_drag_nav']*100:.3f}% NAV/yr")
    else:
        print("\n  ❌ 无 framework PASS 候选 (T3 PASS 都被 T1/T2 FAIL 拖累超预算).")
        print("  **杀 LHB 方向**, 转 A 路下一个候选 (回购公告 / 减持冷静期 / 调研突变).")
        if decision["framework_rejected"]:
            print("\n  Top 3 rejected (按 T3 net 排) — 离 framework PASS 最近的:")
            for w in decision["framework_rejected"][:3]:
                print(f"    {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                      f"T3 net {w['oos_net']*100:+.2f}% / "
                      f"failed slices {[f'{s}:{n*100:+.2f}%' for s, n in w['fail_slices_net_ann']]} / "
                      f"worst drag {w['worst_drag_nav']*100:.3f}% NAV/yr")

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
        # 旧字段 alias 兼容曾经读 any_t3_pass 的 caller
        "decision_legacy": {"any_t3_pass": bool(decision["t3_pass_cells"]),
                            "winners": decision["t3_pass_cells"]},
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
