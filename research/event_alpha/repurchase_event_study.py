"""
A 路第二候选: 回购公告 (预案) event study + cross-tab + framework decision.

假设: 公司宣布回购预案后, 后续 N 日累计 abn return 显著正?
signal: amount_to_circ_mv = 计划回购金额 / 流通市值

数据:
- data/raw/tushare/repurchase.parquet (95k 行 2015-2026)
- proc 状态: 预案 26.5k / 股东大会通过 12k / 实施 32k / 完成 24k / 停止 / 未通过 / 失效
- 本 study 只用 proc='预案' (announcement 是 alpha 的来源点)

Lookahead 处理:
- 用 ann_date (公告日), 假设盘后披露 → 最早 entry T+1 close
- skip_overnight_gap=True (utils.event_study.quintile_spread 的 conservative 默认)

Cost: 双边 1.0% (n_legs=2 long-short), Live-Tier 1 标准

Variants:
- A_all: 全部预案事件 (含 T+1 涨跌停, 上界)
- B_no_limit: 排 T+1 涨跌停 (tradeable)
- C_extreme_no_limit: 排涨跌停 + |amount_to_circ_mv| top 10%

执行: python research/event_alpha/repurchase_event_study.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from utils.event_study import (  # noqa: E402
    cell_verdict,
    compute_event_abn_returns,
    framework_strict_decision,
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
# 1. 加载 repurchase + circ_mv
# ─────────────────────────────────────────────────────────────

def load_repurchase_announcements() -> pd.DataFrame:
    """加载 proc='预案' 的回购公告, 同 (ann_date, ts_code) 多条取 amount 最大.

    返回 DataFrame, 列: ann_date (datetime), symbol (6位), ts_code, amount.
    """
    df = pd.read_parquet(REPURCHASE_PARQUET)
    proposals = df[df["proc"] == "预案"].copy()
    proposals["ann_date"] = pd.to_datetime(proposals["ann_date"], format="%Y%m%d", errors="coerce")
    proposals = proposals.dropna(subset=["ann_date", "amount"])
    proposals = proposals[proposals["amount"] > 0]
    proposals["symbol"] = proposals["ts_code"].astype(str).str.split(".").str[0]
    # 同 (ann_date, symbol) 多条 → 取 amount 最大
    proposals = (proposals.sort_values("amount", ascending=False)
                 .drop_duplicates(subset=["ann_date", "symbol"], keep="first")
                 .reset_index(drop=True))
    print(f"  [回购] 预案 events: {len(proposals):,}, "
          f"日期 {proposals['ann_date'].min().date()} ~ {proposals['ann_date'].max().date()}, "
          f"unique symbols: {proposals['symbol'].nunique():,}")
    return proposals[["ann_date", "symbol", "ts_code", "amount"]]


def load_circ_mv_for_events(events: pd.DataFrame) -> pd.Series:
    """对每个 (ann_date, symbol) 查 daily_basic.circ_mv, 返回 Series (与 events 同 index).

    缺失返回 NaN. 单股 daily_basic parquet 没有的就跳过.
    """
    print(f"  [circ_mv] 查 {events['symbol'].nunique():,} 个 symbol 的市值...")
    mv_by_sym: dict[str, pd.Series] = {}
    for sym in events["symbol"].unique():
        path = DAILY_BASIC_DIR / f"{sym}.parquet"
        if not path.exists():
            continue
        df = pd.read_parquet(path, columns=["trade_date", "circ_mv"])
        if df.empty: continue
        df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
        mv_by_sym[sym] = df.set_index("trade_date")["circ_mv"].sort_index()

    out = pd.Series(index=events.index, dtype=float)
    for i, row in events.iterrows():
        s = mv_by_sym.get(row["symbol"])
        if s is None: continue
        # asof 查 ≤ ann_date 的最近一条 (回购公告日 circ_mv 通常前一交易日的)
        try:
            v = s.asof(row["ann_date"])
            out.iloc[i] = v if not pd.isna(v) else float("nan")
        except (KeyError, TypeError):
            continue
    n_have = out.notna().sum()
    print(f"  [circ_mv] 命中 {n_have:,}/{len(events):,} ({n_have/len(events):.1%})")
    return out


# ─────────────────────────────────────────────────────────────
# 2. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 100)
    print("回购预案 event study (Issue #57, A 路第 2 候选)")
    print("=" * 100)

    # 2.1 加载预案
    print("\n[Step 1] 加载预案 events")
    events = load_repurchase_announcements()

    # 2.2 加 circ_mv → signal = amount / circ_mv
    print("\n[Step 2] 加载 circ_mv 算 signal")
    events["circ_mv"] = load_circ_mv_for_events(events)
    events = events.dropna(subset=["circ_mv"]).copy()
    events["amount_to_mv"] = events["amount"] / events["circ_mv"]
    print(f"  events with valid signal: {len(events):,}")
    print(f"  amount_to_mv 分位: {events['amount_to_mv'].quantile([0.1, 0.5, 0.9]).to_dict()}")
    # circ_mv 单位 万元, amount 单位 元 → ratio 已经是 0~1 范围

    # 2.3 价格面板
    print("\n[Step 3] 价格面板 (load_adj_price_wide)")
    universe = sorted(events["symbol"].unique().tolist())
    start_date = (events["ann_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (events["ann_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")
    if prices.empty:
        raise RuntimeError("价格面板为空")

    # 2.4 涨跌停 filter (无 reason_cat 列, 全部都过滤)
    print("\n[Step 4] T+1 涨跌停 filter")
    events["t1_limit"] = t1_limit_mask(
        events, prices, date_col="ann_date", symbol_col="symbol",
        cat_col=None, threshold=LIMIT_THRESHOLD,
    )
    n_total = len(events)
    n_limit = events["t1_limit"].sum()
    print(f"  total {n_total:,}, T+1 涨跌停 {n_limit:,} ({n_limit/n_total:.1%}) 将被过滤")

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

    # 2.6 全样本 spread (CONSERVATIVE)
    print("\n[Step 6a] 全样本 spread — CONSERVATIVE (skip overnight gap)")
    full = quintile_spread(
        long_df, signal_col="amount_to_mv", horizons=HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=True,
    )
    for h, m in full.items():
        if m["spread_gross"] is None:
            print(f"  T+{h}: insufficient")
            continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}% t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    # 2.7 cross-tab × 3 variants
    def _spread_for(df: pd.DataFrame, label: str) -> dict:
        out: dict[str, dict[int, dict]] = {"_all": {}}
        for slabel, s, e in TIME_SLICES:
            mask = ((df["event_date"] >= pd.Timestamp(s))
                    & (df["event_date"] <= pd.Timestamp(e)))
            sub = df[mask]
            sl = quintile_spread(sub, signal_col="amount_to_mv", horizons=HORIZONS,
                                 cost_per_side=COST_PER_SIDE, n_legs=2,
                                 skip_overnight_gap=True)
            out[slabel] = sl
        # 主表打印
        print(f"\n  ── {label} ──")
        print(f"  {'slice':<14} | {'T+1 net':>9} {'t':>5} | {'T+5 net':>9} {'t':>5} | "
              f"{'T+10 net':>9} {'t':>5} | T+5 verdict")
        print("  " + "─" * 80)
        for slabel, _, _ in TIME_SLICES:
            cells = out[slabel]
            row = f"  {slabel:<14} |"
            for h in HORIZONS:
                m = cells[h]
                if m["spread_gross"] is None:
                    row += f" {'—':>9} {'—':>5} |"
                else:
                    row += f" {m['spread_net']*100:>+8.2f}% {m['t_stat']:>+5.1f} |"
            v5 = cells[5]
            row += f" {cell_verdict(v5['spread_net'], v5['t_stat'])}"
            print(row)
        return out

    print("\n[Step 7a] CROSS-TAB A: 全部事件 (上界)")
    out_a = {"all": _spread_for(long_df, "A_all")}

    print("\n[Step 7b] CROSS-TAB B: 排 T+1 涨跌停 (tradeable)")
    long_b = long_df[~long_df["t1_limit"]].copy()
    out_b = {"all": _spread_for(long_b, "B_no_limit")}

    print("\n[Step 7c] CROSS-TAB C: 排涨跌停 + |amount_to_mv| top 10%")
    ev_signal = long_b.groupby(["symbol", "event_date"])["amount_to_mv"].first()
    threshold = ev_signal.abs().quantile(0.9)
    extreme_keys = set(ev_signal[ev_signal.abs() >= threshold].index)
    long_c = long_b[long_b.set_index(["symbol", "event_date"]).index.isin(extreme_keys)].copy()
    print(f"  filtered to top 10% extreme: {long_c.groupby(['symbol','event_date']).ngroups:,} events")
    out_c = {"all": _spread_for(long_c, "C_extreme_no_limit")}

    # 2.8 framework decision (只对 tradeable B/C)
    print("\n" + "=" * 100)
    print("回购预案方向死活判定 (framework Live-Tier 1 严格门, 只看 B/C tradeable)")
    print("=" * 100)
    decision = framework_strict_decision(
        {"B_no_limit": out_b, "C_extreme_no_limit": out_c},
        horizons=HORIZONS,
        oos_slice_label="T3_2024_2026",
        is_slice_labels=("T1_2015_2019", "T2_2020_2023"),
    )
    print(f"\n  OOS (T3) PASS cells: {len(decision['oos_pass_cells'])} (loose)")
    for w in decision["oos_pass_cells"][:5]:
        print(f"    [loose] {w['variant']:<22} {w['subgroup']:<10} T+{w['horizon']:<2}  "
              f"net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,}")
    print(f"\n  Framework PASS: {len(decision['framework_pass'])}")
    if decision["framework_pass"]:
        print("\n  ✅ 有 framework PASS, 继续 Phase 3 写 spec:")
        for w in decision["framework_pass"]:
            print(f"    {w['variant']:<22} {w['subgroup']:<10} T+{w['horizon']:<2}  "
                  f"T3 net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,} "
                  f"worst drag {w['worst_drag_nav']*100:.3f}% NAV/yr")
    else:
        print("\n  ❌ 无 framework PASS. **杀回购方向**, 转下一个候选 (减持冷静期).")
        if decision["framework_rejected"]:
            print("\n  Top 3 rejected (按 T3 net 排):")
            for w in decision["framework_rejected"][:3]:
                print(f"    {w['variant']:<22} {w['subgroup']:<10} T+{w['horizon']:<2}  "
                      f"T3 net {w['oos_net']*100:+.2f}% / "
                      f"failed slices {[(s, f'{n*100:+.2f}%') for s, n in w['fail_slices_net_ann']]} / "
                      f"worst drag {w['worst_drag_nav']*100:.3f}% NAV/yr")

    # 2.9 落盘
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
