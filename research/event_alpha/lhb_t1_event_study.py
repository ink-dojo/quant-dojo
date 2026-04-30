"""
龙虎榜 (top_list) event study — Issue #55, A 路第一步.

假设: net_rate (大单净买入 / 流通市值) 大的股票, 后续 N 日累计 abn return 显著正?

最简版:
- 不区分游资/机构 (后续 issue 加)
- 不要求连续上榜 (后续 issue 加)
- 不区分涨跌幅榜 (本 study 单独 subgroup 看)

数据:
- data/raw/tushare/events/top_list_*.parquet (2015-01-06 ~ 2026-04-17, 2521 天)
- 每文件 ~200 行 × 15 列, 同 (date, ts_code, reason) 行重复 3 份 (tushare quirk)
- net_rate = net_amount / float_values, % 单位

Lookahead 处理:
- top_list 当日盘后披露, 当日 (rel_day=0) 不可交易
- 最早 entry: T+1 close 后 (T+1 open 也算, 但本 study 用 close-to-close 近似)
- CONSERVATIVE 报告: rel_day [2..H+1] 累计 = T+1 close → T+H+1 close, 跳过
  T close → T+1 close 的 overnight gap (含披露后的 open gap, 不可收)
- NAIVE 报告: rel_day [1..H], 含 overnight gap (上界对比)

Cost: long-short 2 腿, 各 1 round trip, 总 = 4 × 0.25% = 1.0% (修自 rev 1 的 0.5%
under-count). 详见 utils.event_study.quintile_spread n_legs 参数.

时间切片 (RIAD Fold convention):
- T1: 2015-2019 (long history)
- T2: 2020-2023 (mid)
- T3: 2024-2026 (recent OOS)
- F: full sample

输出:
- research/event_alpha/lhb_event_study.png (累计 abn return curve, 全样本)
- research/event_alpha/lhb_event_study_results.json (gitignored)

执行: python research/event_alpha/lhb_t1_event_study.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from utils.event_study import (  # noqa: E402
    compute_event_abn_returns,
    load_event_parquets,
    quintile_spread,
)
from utils.local_data_loader import load_adj_price_wide  # noqa: E402

warnings.filterwarnings("ignore")

EVENTS_DIR = ROOT / "data" / "raw" / "tushare" / "events"
OUT_DIR = ROOT / "research" / "event_alpha"
PLOT_PATH = OUT_DIR / "lhb_event_study.png"
RESULTS_PATH = OUT_DIR / "lhb_event_study_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025
EVAL_HORIZONS = [1, 5, 10]

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. reason categorize
# ─────────────────────────────────────────────────────────────

def categorize_reason(reason: str) -> str:
    """LHB-specific reason taxonomy. Substring 匹配, 处理多种 wording 变体.

    含 "连续" 或 "累计" → multi_day (跨 N 日累计 deviation, 含主板 / 北交所)
    含 "无价格涨跌幅限制" → nolimit (ST / 退市过渡 / 北交所新股 / 科创板上市初期)
    含 "换手率" → daily_turnover
    含 "振幅" → daily_range
    含 "涨幅" (剔除前两条) → daily_up
    含 "跌幅" (剔除前两条) → daily_down

    Rev 2 修正 (rev 1 漏 ~30% 事件到 other): 加 "有价格涨跌幅限制的..." 和
    "非ST、*ST..." 等 wording 变体.
    """
    if not isinstance(reason, str):
        return "other"
    if "连续" in reason or "累计" in reason:
        return "multi_day"
    if "无价格涨跌幅限制" in reason:
        return "nolimit"
    if "换手率" in reason:
        return "daily_turnover"
    if "振幅" in reason:
        return "daily_range"
    if "涨幅" in reason:
        return "daily_up"
    if "跌幅" in reason:
        return "daily_down"
    return "other"


# ─────────────────────────────────────────────────────────────
# 2. per-event aggregate (同 date+symbol 多 reason 取 |net_amount| 最大那条)
# ─────────────────────────────────────────────────────────────

def aggregate_per_event(events: pd.DataFrame) -> pd.DataFrame:
    """同一 (date, symbol) 多 reason → 取 |net_amount| 最大那条作主信号."""
    events = events.copy()
    events["reason_cat"] = events["reason"].apply(categorize_reason)
    events["abs_net"] = events["net_amount"].abs()
    events_with_net = events.dropna(subset=["abs_net"])
    idx = events_with_net.groupby(["trade_date", "symbol"])["abs_net"].idxmax()
    idx = idx.dropna().astype(int)
    main = events.loc[idx].copy().drop(columns="abs_net").reset_index(drop=True)
    print(f"  [LHB] per-event aggregate rows={len(main):,}")
    return main


# ─────────────────────────────────────────────────────────────
# 3. plot
# ─────────────────────────────────────────────────────────────

def plot_event_study(long_df: pd.DataFrame, n_q: int = N_QUINTILES,
                     save_path: Path = PLOT_PATH) -> pd.DataFrame:
    """T-5 ~ T+30 累计 abn return, 按 net_rate quintile 分组."""
    ev_rate = long_df.groupby(["symbol", "event_date"])["net_rate"].first()
    ev_q = pd.qcut(ev_rate, q=n_q, labels=[f"Q{i}" for i in range(1, n_q + 1)],
                   duplicates="drop")
    long_df = long_df.merge(ev_q.rename("q").reset_index(),
                            on=["symbol", "event_date"])

    agg = (long_df.groupby(["q", "rel_day"], observed=True)["abn_ret"]
           .mean().unstack("q"))
    cum = agg.cumsum()

    plt.figure(figsize=(11, 6))
    for q in cum.columns:
        plt.plot(cum.index, cum[q] * 100, label=str(q), linewidth=1.6)
    plt.axvline(0, color="k", linestyle="--", alpha=0.5, label="event_date (T)")
    plt.axvline(1, color="g", linestyle=":", alpha=0.4, label="T+1 (含 gap, 不可收)")
    plt.axvline(2, color="b", linestyle=":", alpha=0.4, label="T+2 (CONSERVATIVE entry)")
    plt.axhline(0, color="gray", linewidth=0.5)
    plt.xlabel("Relative trading day (0 = top_list event)")
    plt.ylabel("Cumulative abnormal return (%)")
    plt.title(f"龙虎榜 event study — A股, 按 net_rate 分 {n_q} quintile")
    plt.legend(title="net_rate quintile (Q5=最强买入)")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    save_path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(save_path, dpi=120)
    print(f"  [plot] 保存 {save_path}")
    return cum


# ─────────────────────────────────────────────────────────────
# 4. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 76)
    print("龙虎榜 net_rate event study (Issue #55, A 路第一步, rev 2)")
    print("=" * 76)

    # 4.1 加载 + 清洗 (用 utils.event_study.load_event_parquets)
    print("\n[Step 1] 加载 top_list 全量")
    raw = load_event_parquets(
        prefix="top_list", events_dir=EVENTS_DIR,
        columns=["trade_date", "ts_code", "reason", "net_amount", "net_rate", "close"],
    )
    if raw.empty:
        raise RuntimeError("top_list 加载为空, 检查 EVENTS_DIR")
    print(f"  [LHB] dedup rows={len(raw):,}")
    main = aggregate_per_event(raw)
    print(f"  reason_cat 分布:\n{main['reason_cat'].value_counts().to_string()}")
    print(f"  日期范围: {main['trade_date'].min().date()} ~ {main['trade_date'].max().date()}")

    # 4.2 价格面板
    print("\n[Step 2] 价格面板 (load_adj_price_wide)")
    universe = sorted(main["symbol"].dropna().unique().tolist())
    print(f"  universe: {len(universe)} 支")
    start_date = (main["trade_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (main["trade_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")
    if prices.empty:
        raise RuntimeError("价格面板为空")

    # 4.3 abn return event window (向量化, ~1min → <5s)
    print("\n[Step 3] abn return event window (T-5 ~ T+30, vectorized)")
    main_for_event = main.rename(columns={"trade_date": "event_date"})
    long_df = compute_event_abn_returns(
        main_for_event, prices,
        date_col="event_date", symbol_col="symbol",
        extra_cols=["net_rate", "reason_cat"],
        pre_days=PRE_DAYS, post_days=POST_DAYS,
    )
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    # 4.4 全样本 quintile spread (CONSERVATIVE + NAIVE 两版本)
    print("\n[Step 4a] 全样本 spread — CONSERVATIVE (skip overnight gap, n_legs=2 long-short)")
    full_conserv = quintile_spread(
        long_df, signal_col="net_rate", horizons=EVAL_HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=True,
    )
    for h, m in full_conserv.items():
        if m["spread_gross"] is None:
            print(f"  T+{h}: insufficient events"); continue
        print(f"  T+{h} hold: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}% (cost {m['cost_total']*100:.2f}%) "
              f"t={m['t_stat']:+.2f} (p={m['p_value']:.4f}, n={m['n_events']:,})")

    print("\n[Step 4b] 全样本 spread — NAIVE (含 gap, 仅作上界对比)")
    full_naive = quintile_spread(
        long_df, signal_col="net_rate", horizons=EVAL_HORIZONS,
        cost_per_side=COST_PER_SIDE, n_legs=2, skip_overnight_gap=False,
    )
    for h, m in full_naive.items():
        if m["spread_gross"] is None: continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}%  t={m['t_stat']:+.2f}")

    # 4.5 时间切片
    print("\n[Step 5] 时间切片 (RIAD Fold convention) — CONSERVATIVE only")
    slice_results = {}
    for label, s, e in TIME_SLICES:
        mask = ((long_df["event_date"] >= pd.Timestamp(s))
                & (long_df["event_date"] <= pd.Timestamp(e)))
        sub = long_df[mask]
        sl = quintile_spread(sub, signal_col="net_rate", horizons=EVAL_HORIZONS,
                             cost_per_side=COST_PER_SIDE, n_legs=2,
                             skip_overnight_gap=True)
        slice_results[label] = sl
        print(f"\n  ── {label} ──")
        for h, m in sl.items():
            if m["spread_gross"] is None:
                print(f"    T+{h}: insufficient events ({m['n_events']:,})")
                continue
            verdict = ("PASS" if (m["spread_net"] > 0 and m["t_stat"] > 2)
                       else ("FAIL" if m["spread_net"] <= 0 else "MARGINAL"))
            print(f"    T+{h}: gross {m['spread_gross']*100:+.3f}% / "
                  f"net {m['spread_net']*100:+.3f}%  t={m['t_stat']:+.2f} {verdict}")

    # 4.6 reason subgroup (全样本)
    print("\n[Step 6] reason subgroup spread (T+5)")
    cat_results = {}
    for cat in ["daily_up", "daily_down", "daily_range", "daily_turnover",
                "multi_day", "nolimit", "other"]:
        sub = long_df[long_df["reason_cat"] == cat]
        if len(sub) == 0:
            continue
        cat_spread = quintile_spread(sub, signal_col="net_rate", horizons=[5],
                                     cost_per_side=COST_PER_SIDE, n_legs=2,
                                     skip_overnight_gap=True)
        cat_results[cat] = cat_spread[5]
        m = cat_spread[5]
        if m["spread_gross"] is None:
            print(f"  {cat:<16}: 事件不够 (n={m['n_events']})")
            continue
        print(f"  {cat:<16}: gross {m['spread_gross']*100:+.3f}% / "
              f"net {m['spread_net']*100:+.3f}%  t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    # 4.7 plot
    print("\n[Step 7] 画 cumulative abn return curve")
    plot_event_study(long_df)

    # 4.8 落盘
    payload = {
        "config": {
            "n_quintiles": N_QUINTILES,
            "pre_days": PRE_DAYS, "post_days": POST_DAYS,
            "cost_per_side": COST_PER_SIDE,
            "n_legs": 2, "cost_total": 4 * COST_PER_SIDE,
            "horizons": EVAL_HORIZONS, "skip_overnight_gap": True,
            "rev": 2,
        },
        "n_events_total": int(n_events),
        "full_sample_conservative": full_conserv,
        "full_sample_naive_with_gap": full_naive,
        "time_slices_conservative": slice_results,
        "reason_subgroups_conservative": cat_results,
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
