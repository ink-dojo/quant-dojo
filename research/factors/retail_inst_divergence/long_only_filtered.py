"""
RIAD Long-only Q2Q3 在 filtered universe 里的表现

由 tradable_universe.py 发现: LS 在 filtered universe 下 OOS Sharpe -0.34 (变负).
原因: Q5 "散户追涨股" 大多是 ST / 小盘 / 非两融标的, short leg 实际不可执行.

解决方案测试:
    (1) Long-only Q2Q3 (无 short leg)
    (2) Long Q2Q3 + Short HS300 期货 (systematic hedge, 不依赖个股融券)

两者都只用 tradable universe (含 ST/新股 filter).
benchmark = 等权全 A tradable universe
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from research.factors.retail_inst_divergence.daily_returns import (  # noqa: E402
    COST_ONE_WAY, LONG_HIGH, LONG_LOW, PRICE_PATH, REBALANCE_DAYS,
    _to_ts, build_riad_neutral,
)
from utils.tradability_filter import apply_tradability_filter  # noqa: E402

HS300_PATH = ROOT / "data" / "raw" / "tushare" / "index_daily_000300.parquet"


def load_hs300_daily() -> pd.Series:
    df = pd.read_parquet(HS300_PATH)
    df["trade_date"] = pd.to_datetime(df["trade_date"].astype(str).str.strip(), format="%Y%m%d")
    df = df.sort_values("trade_date").set_index("trade_date")
    return (df["pct_chg"].astype(float) / 100.0).rename("hs300")


def run_long_only(factor, price, tradable, start, end):
    dates = price.loc[start:end].index
    rebal = dates[::REBALANCE_DAYS]
    pct = price.pct_change()

    long_sets = []
    for d in rebal:
        if d not in factor.index:
            long_sets.append(set()); continue
        s = factor.loc[d].dropna()
        if len(s) < 100:
            long_sets.append(set()); continue
        q_ll, q_lh = s.quantile(LONG_LOW), s.quantile(LONG_HIGH)
        cand = s[(s >= q_ll) & (s <= q_lh)].index
        if d in tradable.index:
            tmask = tradable.loc[d]
            cand = [c for c in cand if c in tmask.index and tmask[c]]
        long_sets.append(set(cand))

    hs300 = load_hs300_daily()
    recs = []
    prev_long = set()
    prev_pos = -1
    rebal_idx = pd.DatetimeIndex(rebal)
    for d in dates:
        pos = rebal_idx.searchsorted(d, side="right") - 1
        if pos < 0:
            recs.append({"date": d, "long_r": np.nan, "hs300": np.nan,
                         "long_only_net": np.nan, "hedged_net": np.nan, "cost": 0.0}); continue
        cur = long_sets[pos]
        is_rebal = (pos != prev_pos)
        prev_pos = pos

        row = pct.loc[d] if d in pct.index else pd.Series(dtype=float)
        syms = [s for s in cur if s in row.index]
        long_r = float(row[syms].mean(skipna=True)) if syms else 0.0
        hs_r = float(hs300.reindex([d]).iloc[0]) if d in hs300.index else 0.0

        cost = 0.0
        if is_rebal:
            if pos > 0:
                old = long_sets[pos - 1]
                turn = len(cur.symmetric_difference(old)) / max(len(cur | old), 1) if cur or old else 0.0
                cost_long_only = turn * COST_ONE_WAY  # 单腿进出
                cost_hedged = cost_long_only + turn * COST_ONE_WAY * 0.1  # hedge 期货 cost 按 0.01%/边估计
            else:
                cost_long_only = 2 * COST_ONE_WAY
                cost_hedged = 2 * COST_ONE_WAY + 0.0002

        long_only_net = long_r - (cost if is_rebal else 0.0)
        # hedged: long - beta × HS300; 简化 beta = 1
        hedged_gross = long_r - hs_r
        hedged_net = hedged_gross - (cost if is_rebal else 0.0)

        recs.append({"date": d, "long_r": long_r, "hs300": hs_r,
                     "long_only_net": long_only_net, "hedged_net": hedged_net,
                     "cost": (cost if is_rebal else 0.0)})

    return pd.DataFrame(recs).set_index("date")


def summarize(series, label):
    s = series.dropna()
    if s.empty:
        return {}
    ann = s.mean() * 252
    vol = s.std(ddof=1) * np.sqrt(252)
    sr = ann / vol if vol > 0 else np.nan
    cum_s = (1 + s).cumprod()
    mdd = float((cum_s / cum_s.cummax() - 1).min())
    return {
        "label": label, "n": len(s),
        "ann": float(ann), "vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": mdd, "cum": float(cum_s.iloc[-1] - 1),
    }


def main():
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    tradable = apply_tradability_filter(price.loc["2023-07-01":end])
    factor = build_riad_neutral(start, end, price).shift(1)

    daily = run_long_only(factor, price, tradable, start, end)
    print(f"daily shape: {daily.shape}")

    # Benchmark: 等权全 A tradable
    pct = price.pct_change()
    bench_rets = []
    for d in daily.index:
        if d not in tradable.index:
            bench_rets.append(np.nan); continue
        tm = tradable.loc[d]
        syms = tm.index[tm].tolist()
        row = pct.loc[d] if d in pct.index else pd.Series()
        valid = [s for s in syms if s in row.index]
        bench_rets.append(float(row[valid].mean(skipna=True)) if valid else np.nan)
    bench = pd.Series(bench_rets, index=daily.index, name="bench_eqwt")

    print("\n=== Filtered universe, 不同模式对比 ===\n")
    rows = []
    for lab, s, e in [
        ("FULL 2023-10~2025-12", start, end),
        ("IS 2023-10~2024-12", start, "2024-12-31"),
        ("OOS 2025", "2025-01-01", end),
    ]:
        lo = summarize(daily.loc[s:e, "long_only_net"], f"{lab} long_only")
        hd = summarize(daily.loc[s:e, "hedged_net"], f"{lab} hedged(HS300)")
        bm = summarize(bench.loc[s:e], f"{lab} benchmark")
        rows.append((lab, lo, hd, bm))

    header = f"{'Segment':<22} {'Mode':<18} {'n':>5} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'MDD%':>8}"
    print(header)
    print("-" * len(header))
    for lab, lo, hd, bm in rows:
        for mode, r in [("long_only Q2Q3", lo), ("hedged HS300", hd), ("bench eqwt", bm)]:
            if not r:
                continue
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{lab:<22} {mode:<18} "
                f"{r['n']:>5} "
                f"{r['ann']*100:>+6.2f} "
                f"{r['vol']*100:>5.2f} "
                f"{sr:>+6.2f} "
                f"{r['mdd']*100:>+7.2f}"
            )

    # 关键比对: long_only - benchmark (alpha vs 等权)
    print("\n=== Long-only Q2Q3 超额 vs 等权全 A (alpha only) ===")
    excess = (daily["long_only_net"] - bench).dropna()
    for lab, s, e in [("FULL", start, end), ("IS", start, "2024-12-31"), ("OOS", "2025-01-01", end)]:
        sub = excess.loc[s:e]
        ann = sub.mean() * 252
        vol = sub.std(ddof=1) * np.sqrt(252)
        sr = ann / vol if vol > 0 else np.nan
        print(f"  [{lab}] n={len(sub)} Excess Ann={ann*100:+.2f}% Vol={vol*100:.2f}% IR={sr:+.3f}")

    out_pq = ROOT / "logs" / "riad_long_only_filtered.parquet"
    pd.concat([daily, bench], axis=1).to_parquet(out_pq)
    print(f"\n保存: {out_pq}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_long_only_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "results": {lab: {"long_only": lo, "hedged": hd, "bench": bm}
                            for lab, lo, hd, bm in rows},
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"保存: {out_json}")


if __name__ == "__main__":
    main()
