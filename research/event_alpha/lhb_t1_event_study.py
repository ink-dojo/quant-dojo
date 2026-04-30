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
- 最早 entry: T+1 (rel_day=1)
- 报告 "T+1 ret" = rel_day=1 累计 = T close → T+1 close
- Q5-Q1 backtest: T close 收盘下单, T+H close 平仓 (H=1/5/10)

Cost: 双边 0.5% (Live-Tier 1 标准). 0.25% per side.

时间切片 (RIAD Fold convention):
- T1: 2015-2019 (long history)
- T2: 2020-2023 (mid)
- T3: 2024-2026 (recent OOS)
- F: full sample

输出:
- research/event_alpha/lhb_event_study.png (累计 abn return curve, 全样本)
- research/event_alpha/lhb_event_study_results.json (gitignored)
- 控制台: quintile spread + 时间切片表 + reason subgroup

执行:
    python research/event_alpha/lhb_t1_event_study.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path
from typing import Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from utils.factor_analysis import ic_summary  # noqa: E402
from utils.local_data_loader import load_adj_price_wide  # noqa: E402

warnings.filterwarnings("ignore")

EVENTS_DIR = ROOT / "data" / "raw" / "tushare" / "events"
OUT_DIR = ROOT / "research" / "event_alpha"
PLOT_PATH = OUT_DIR / "lhb_event_study.png"
RESULTS_PATH = OUT_DIR / "lhb_event_study_results.json"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5
COST_PER_SIDE = 0.0025  # 双边 0.5% = 0.25% per side
EVAL_HORIZONS = [1, 5, 10]  # T+H close-to-close 累计 abn return 报告点

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_2015_2019",  "2015-01-01", "2019-12-31"),
    ("T2_2020_2023",  "2020-01-01", "2023-12-31"),
    ("T3_2024_2026",  "2024-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. 加载 + 清洗 top_list
# ─────────────────────────────────────────────────────────────

def _strip_ts_suffix(ts_code: str) -> str:
    """000001.SZ → 000001 (匹配 local_data_loader 的 bare 6-digit symbol)."""
    return ts_code.split(".")[0] if isinstance(ts_code, str) else ts_code


def load_lhb_events(start: str = "20150101", end: str = "20261231") -> pd.DataFrame:
    """读全部 top_list_*.parquet, dedup, 加 date/symbol 列, 返回 long 表.

    返回列: trade_date (datetime), symbol (6-digit str), reason (str),
            net_amount (float, 元), net_rate (float, %), close (float)
    """
    print(f"  [LHB] 扫 {EVENTS_DIR} ...")
    files = sorted(EVENTS_DIR.glob("top_list_*.parquet"))
    print(f"  [LHB] {len(files)} 文件")
    frames = []
    start_int, end_int = int(start.replace("-", "")), int(end.replace("-", ""))
    for f in files:
        # 文件名 top_list_YYYYMMDD.parquet
        try:
            d = int(f.stem.replace("top_list_", ""))
        except ValueError:
            continue
        if d < start_int or d > end_int:
            continue
        df = pd.read_parquet(f, columns=["trade_date", "ts_code", "reason",
                                         "net_amount", "net_rate", "close"])
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame()

    raw = pd.concat(frames, ignore_index=True)
    print(f"  [LHB] 合并 raw rows={len(raw):,}")
    raw = raw.drop_duplicates()
    print(f"  [LHB] dedup rows={len(raw):,}")

    raw["trade_date"] = pd.to_datetime(raw["trade_date"], format="%Y%m%d")
    raw["symbol"] = raw["ts_code"].apply(_strip_ts_suffix)
    return raw[["trade_date", "symbol", "ts_code", "reason",
                "net_amount", "net_rate", "close"]]


def categorize_reason(reason: str) -> str:
    """把 raw reason 字符串归大类, 用于 subgroup 分析."""
    if not isinstance(reason, str):
        return "other"
    if reason.startswith("日涨幅") or "日涨幅" in reason[:5]:
        return "daily_up"
    if reason.startswith("日跌幅") or "日跌幅" in reason[:5]:
        return "daily_down"
    if reason.startswith("日振幅") or "日振幅" in reason[:5]:
        return "daily_range"
    if reason.startswith("日换手") or "日换手" in reason[:5]:
        return "daily_turnover"
    if "连续三个交易日" in reason or "连续3" in reason:
        return "multi_day"
    return "other"


def aggregate_per_event(events: pd.DataFrame) -> pd.DataFrame:
    """同一 (date, symbol) 多 reason → 取 |net_amount| 最大那条作主信号.

    保留 reason_cat 用于 subgroup. 多 reason 同股都强 = 取最大代表性.
    """
    events = events.copy()
    events["reason_cat"] = events["reason"].apply(categorize_reason)
    events["abs_net"] = events["net_amount"].abs()
    # 按 (date, symbol) 取 abs_net 最大那行; 全 NaN 组 idxmax 返回 NaN, 必须先排掉
    events_with_net = events.dropna(subset=["abs_net"])
    idx = events_with_net.groupby(["trade_date", "symbol"])["abs_net"].idxmax()
    idx = idx.dropna().astype(int)
    main = events.loc[idx].copy()
    main = main.drop(columns="abs_net").reset_index(drop=True)
    print(f"  [LHB] per-event aggregate rows={len(main):,}")
    return main


# ─────────────────────────────────────────────────────────────
# 2. abn return event window
# ─────────────────────────────────────────────────────────────

def compute_event_abn_returns(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    pre_days: int = PRE_DAYS,
    post_days: int = POST_DAYS,
) -> pd.DataFrame:
    """对每个事件算 T-pre ~ T+post 的相对日 abn_ret.

    abn_ret = ret - mkt_ew_mean (简化 market-adj). ret 的极值 (>0.25 或 <-0.25)
    设 NaN 防 corp action 污染.

    rel_day=0 是 event_date 当天 (top_list 盘后披露, 不可交易, 但收益已发生).
    rel_day=1 是 T+1 close-to-close 收益 (= T close → T+1 close).

    返回 long DataFrame: symbol, event_date, net_rate, reason_cat, rel_day, abn_ret
    """
    daily_ret = prices.pct_change().where(lambda x: x.abs() < 0.25)
    mkt = daily_ret.mean(axis=1)
    abn = daily_ret.sub(mkt, axis=0)

    td_arr = daily_ret.index.values
    rows = []

    for _, e in events.iterrows():
        sym = e["symbol"]
        if sym not in abn.columns:
            continue
        ad = np.datetime64(e["trade_date"])
        i0 = int(np.searchsorted(td_arr, ad, side="left"))
        # 容易出问题: searchsorted 返回的 i0 对应的日期可能不是 ad 本身 (停牌日)
        if i0 >= len(td_arr) or td_arr[i0] != ad:
            continue
        if i0 < pre_days or i0 + post_days >= len(td_arr):
            continue

        for rd in range(-pre_days, post_days + 1):
            val = abn.iloc[i0 + rd][sym]
            if pd.isna(val):
                continue
            rows.append({
                "symbol": sym,
                "event_date": pd.Timestamp(e["trade_date"]),
                "net_rate": float(e["net_rate"]) if pd.notna(e["net_rate"]) else np.nan,
                "reason_cat": e["reason_cat"],
                "rel_day": rd,
                "abn_ret": float(val),
            })

    return pd.DataFrame(rows)


# ─────────────────────────────────────────────────────────────
# 3. quintile spread + cost-aware
# ─────────────────────────────────────────────────────────────

def quintile_spread(
    long_df: pd.DataFrame,
    horizons: list[int] = EVAL_HORIZONS,
    n_q: int = N_QUINTILES,
    cost_per_side: float = COST_PER_SIDE,
    skip_overnight_gap: bool = True,
) -> dict:
    """按 net_rate quintile 分组, 计算每个 horizon 的 Q5-Q1 spread + cost-aware net.

    skip_overnight_gap (默认 True, **conservative tradeable**):
        每个事件 horizon-累计 ret = sum(abn_ret, rel_day in [2..H+1]).
        rel_day=1 是 T close → T+1 close, 包含 T 晚 top_list 披露后的 T+1 OPEN gap.
        这个 gap 不可收 (T close 不能下单, T+1 open 才能进场). 跳过 rel_day=1
        给 conservative bound: 假设 T+1 open ≈ T+1 close (近似), entry 在 T+1
        close 后, 持有 H 天到 T+H+1 close.
    skip_overnight_gap=False (lookahead-naive 上界):
        sum(abn_ret, rel_day in [1..H]). 这个数会被 T close→T+1 open 的 gap 拉大.

    Q5-Q1 spread = cross-event mean diff. cost = 2 * cost_per_side per round trip.
    """
    # 每事件取 net_rate (rel_day=0 那行就有, 但所有 rel_day 行 net_rate 一样, 取 first)
    ev_rate = long_df.groupby(["symbol", "event_date"])["net_rate"].first().rename("net_rate")
    ev_cat = long_df.groupby(["symbol", "event_date"])["reason_cat"].first().rename("reason_cat")

    out = {}
    rel_lo = 2 if skip_overnight_gap else 1
    for h in horizons:
        # tradeable 累计: skip overnight gap → [2..h+1], 否则 [1..h]
        rel_hi = h + 1 if skip_overnight_gap else h
        sub = long_df[(long_df["rel_day"] >= rel_lo) & (long_df["rel_day"] <= rel_hi)]
        cum = sub.groupby(["symbol", "event_date"])["abn_ret"].sum().rename(f"cum_{h}")
        df = pd.concat([ev_rate, ev_cat, cum], axis=1).dropna(subset=["net_rate", f"cum_{h}"])

        if len(df) < n_q * 20:
            out[h] = {"n_events": int(len(df)), "spread_gross": None, "spread_net": None}
            continue

        df["q"] = pd.qcut(df["net_rate"], q=n_q, labels=False, duplicates="drop")
        # 横截面: 同期 events 数千条, 不需要按时间二次分组
        q_means = df.groupby("q")[f"cum_{h}"].mean()
        spread_gross = float(q_means.iloc[-1] - q_means.iloc[0])
        spread_net = spread_gross - 2 * cost_per_side  # 多腿 + 空腿 entry+exit 共 4 次 cost? 或简化为 round trip

        # t 统计: 把 Q5 / Q1 cross-event ret 当独立观测, 算 spread series 的 t
        q_high = df[df["q"] == df["q"].max()][f"cum_{h}"].values
        q_low = df[df["q"] == 0][f"cum_{h}"].values
        # 不同样本 size 的 Welch t-test (近似)
        from scipy import stats
        t_stat, p_val = stats.ttest_ind(q_high, q_low, equal_var=False)

        out[h] = {
            "n_events": int(len(df)),
            "n_q5": int(len(q_high)),
            "n_q1": int(len(q_low)),
            "spread_gross": round(spread_gross, 5),
            "spread_net": round(spread_net, 5),
            "t_stat": round(float(t_stat), 3),
            "p_value": round(float(p_val), 4),
            "q_means": {str(int(k)): round(float(v), 5) for k, v in q_means.items()},
        }
    return out


# ─────────────────────────────────────────────────────────────
# 4. plot
# ─────────────────────────────────────────────────────────────

def plot_event_study(long_df: pd.DataFrame, n_q: int = N_QUINTILES, save_path: Path = PLOT_PATH) -> pd.DataFrame:
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
    plt.axvline(1, color="g", linestyle=":", alpha=0.4, label="T+1 (entry possible)")
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
# 5. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 76)
    print("龙虎榜 net_rate event study (Issue #55, A 路第一步)")
    print("=" * 76)

    # 5.1 加载 + 清洗
    print("\n[Step 1] 加载 top_list 全量")
    raw = load_lhb_events()
    if raw.empty:
        raise RuntimeError("top_list 加载为空, 检查 EVENTS_DIR")
    main = aggregate_per_event(raw)
    print(f"  reason_cat 分布:\n{main['reason_cat'].value_counts().to_string()}")
    print(f"  日期范围: {main['trade_date'].min().date()} ~ {main['trade_date'].max().date()}")

    # 5.2 价格面板
    print("\n[Step 2] 价格面板 (load_adj_price_wide)")
    universe = sorted(main["symbol"].dropna().unique().tolist())
    print(f"  universe: {len(universe)} 支")
    start_date = (main["trade_date"].min() - pd.Timedelta(days=20)).date()
    end_date = (main["trade_date"].max() + pd.Timedelta(days=POST_DAYS + 10)).date()
    prices = load_adj_price_wide(universe, str(start_date), str(end_date))
    print(f"  prices shape: {prices.shape}")
    if prices.empty:
        raise RuntimeError("价格面板为空")

    # 5.3 abn return event window
    print("\n[Step 3] abn return event window (T-5 ~ T+30)")
    long_df = compute_event_abn_returns(main, prices)
    print(f"  long rows: {len(long_df):,}")
    n_events = long_df.groupby(["symbol", "event_date"]).ngroups
    print(f"  unique events: {n_events:,}")

    # 5.4 全样本 quintile spread (报 conservative tradeable + naive 两版本)
    print("\n[Step 4a] 全样本 quintile spread — CONSERVATIVE (skip T close→T+1 open gap)")
    full_conserv = quintile_spread(long_df, skip_overnight_gap=True)
    for h, m in full_conserv.items():
        if m["spread_gross"] is None:
            print(f"  T+{h}: insufficient events")
            continue
        print(f"  T+{h} hold: gross {m['spread_gross']*100:+.3f}% / net {m['spread_net']*100:+.3f}%  "
              f"t={m['t_stat']:+.2f} (p={m['p_value']:.4f}, n={m['n_events']:,})")

    print("\n[Step 4b] 全样本 quintile spread — NAIVE (含 overnight gap, 不可收, 仅作上界对比)")
    full_naive = quintile_spread(long_df, skip_overnight_gap=False)
    for h, m in full_naive.items():
        if m["spread_gross"] is None:
            continue
        print(f"  T+{h}: gross {m['spread_gross']*100:+.3f}% / net {m['spread_net']*100:+.3f}%  "
              f"t={m['t_stat']:+.2f}")
    full_spread = full_conserv  # 主结果用 conservative

    # 5.5 时间切片
    print("\n[Step 5] 时间切片 (RIAD Fold convention)")
    slice_results = {}
    for label, s, e in TIME_SLICES:
        mask = (long_df["event_date"] >= pd.Timestamp(s)) & (long_df["event_date"] <= pd.Timestamp(e))
        sub = long_df[mask]
        sl = quintile_spread(sub)
        slice_results[label] = sl
        print(f"\n  ── {label} ──")
        for h, m in sl.items():
            if m["spread_gross"] is None:
                print(f"    T+{h}: insufficient events ({m['n_events']:,})")
                continue
            verdict = "PASS" if (m["spread_net"] > 0 and m["t_stat"] > 2) else (
                      "FAIL" if (m["spread_net"] <= 0) else "MARGINAL")
            print(f"    T+{h}: gross {m['spread_gross']*100:+.3f}% / net {m['spread_net']*100:+.3f}%  "
                  f"t={m['t_stat']:+.2f} {verdict}")

    # 5.6 reason subgroup (全样本)
    print("\n[Step 6] reason subgroup spread (T+5)")
    cat_results = {}
    for cat in ["daily_up", "daily_down", "daily_range", "daily_turnover", "multi_day", "other"]:
        sub = long_df[long_df["reason_cat"] == cat]
        if len(sub) == 0:
            continue
        cat_spread = quintile_spread(sub, horizons=[5])
        cat_results[cat] = cat_spread[5]
        m = cat_spread[5]
        if m["spread_gross"] is None:
            print(f"  {cat:<16}: 事件不够 (n={m['n_events']})")
            continue
        print(f"  {cat:<16}: gross {m['spread_gross']*100:+.3f}% / net {m['spread_net']*100:+.3f}%  "
              f"t={m['t_stat']:+.2f} (n={m['n_events']:,})")

    # 5.7 plot 全样本 cumulative
    print("\n[Step 7] 画 cumulative abn return curve")
    cum = plot_event_study(long_df)

    # 5.8 落盘
    payload = {
        "config": {
            "n_quintiles": N_QUINTILES,
            "pre_days": PRE_DAYS,
            "post_days": POST_DAYS,
            "cost_per_side": COST_PER_SIDE,
            "horizons": EVAL_HORIZONS,
            "skip_overnight_gap": True,
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
