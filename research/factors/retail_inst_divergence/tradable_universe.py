"""
RIAD 可交易 universe 过滤

两层过滤:
    (A) tradability_filter: 剔除 ST / 新股 (上市 < 60 日) / 低价 (< 2 元) / 低流动性
    (B) margin_shortable: short leg 必须在两融标的清单内 (代理: 有 margin/{symbol}.parquet)

应用:
    long_universe = tradable
    short_universe = tradable & margin_shortable

重算 daily LS returns 对比 baseline:
    预期 short 端 universe 收缩 ~50%, 但 alpha 应保留 (散户追涨股大多是两融标的)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
MARGIN_DIR = ROOT / "data" / "raw" / "tushare" / "margin"

from research.factors.retail_inst_divergence.daily_returns import (  # noqa: E402
    LONG_LOW, LONG_HIGH, SHORT_LOW, SHORT_HIGH,
    PRICE_PATH, REBALANCE_DAYS, COST_ONE_WAY,
    _to_ts, build_riad_neutral,
)
from utils.tradability_filter import apply_tradability_filter  # noqa: E402


def load_margin_universe() -> set[str]:
    """从 margin/ 目录推断两融标的 universe (有过 margin 数据的股票)."""
    syms = set()
    for f in sorted(MARGIN_DIR.glob("*.parquet")):
        code = f.stem  # 6-digit
        syms.add(_to_ts(code))
    return syms


def generate_daily_ls_filtered(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    tradable_mask: pd.DataFrame,
    margin_univ: set[str],
    start: str,
    end: str,
    rebalance_days: int = REBALANCE_DAYS,
) -> pd.DataFrame:
    dates = price.loc[start:end].index
    rebal_dates = dates[::rebalance_days]
    pct = price.pct_change()

    long_sets: list[set[str]] = []
    short_sets: list[set[str]] = []
    for d in rebal_dates:
        if d not in factor.index:
            long_sets.append(set()); short_sets.append(set()); continue
        s = factor.loc[d].dropna()
        if len(s) < 100:
            long_sets.append(set()); short_sets.append(set()); continue
        q_ll, q_lh = s.quantile(LONG_LOW), s.quantile(LONG_HIGH)
        q_sl, q_sh = s.quantile(SHORT_LOW), s.quantile(SHORT_HIGH)
        # 长期候选
        long_cand = s[(s >= q_ll) & (s <= q_lh)].index
        short_cand = s[(s >= q_sl) & (s <= q_sh)].index
        # 应用 tradable mask at date d
        if d in tradable_mask.index:
            tmask = tradable_mask.loc[d]
            long_cand = [c for c in long_cand if c in tmask.index and tmask[c]]
            short_cand = [c for c in short_cand if c in tmask.index and tmask[c]]
        # short 必须在 margin universe 内
        short_cand = [c for c in short_cand if c in margin_univ]
        long_sets.append(set(long_cand))
        short_sets.append(set(short_cand))

    rebal_idx = pd.DatetimeIndex(rebal_dates)
    daily_records = []
    prev_idx = -1
    for d in dates:
        pos = rebal_idx.searchsorted(d, side="right") - 1
        if pos < 0:
            daily_records.append({"date": d, "gross_long": np.nan, "gross_short": np.nan,
                                  "gross_ls": np.nan, "cost": 0.0, "net_ls": np.nan,
                                  "n_long": 0, "n_short": 0})
            continue
        cur_long, cur_short = long_sets[pos], short_sets[pos]
        is_rebal = (pos != prev_idx)
        prev_idx = pos

        row = pct.loc[d] if d in pct.index else pd.Series(dtype=float)
        long_syms = [s for s in cur_long if s in row.index]
        short_syms = [s for s in cur_short if s in row.index]
        long_r = float(row[long_syms].mean(skipna=True)) if long_syms else 0.0
        short_r = float(row[short_syms].mean(skipna=True)) if short_syms else 0.0
        gross = long_r - short_r

        cost = 0.0
        if is_rebal:
            if pos > 0:
                old_long, old_short = long_sets[pos - 1], short_sets[pos - 1]
                tl = len(cur_long.symmetric_difference(old_long)) / max(len(cur_long | old_long), 1) if cur_long or old_long else 0.0
                ts = len(cur_short.symmetric_difference(old_short)) / max(len(cur_short | old_short), 1) if cur_short or old_short else 0.0
                cost = (tl + ts) * COST_ONE_WAY
            else:
                cost = 2 * COST_ONE_WAY
        net = gross - cost
        daily_records.append({
            "date": d, "gross_long": long_r, "gross_short": short_r,
            "gross_ls": gross, "cost": cost, "net_ls": net,
            "n_long": len(long_syms), "n_short": len(short_syms),
        })

    out = pd.DataFrame(daily_records).set_index("date")
    return out


def summarize(series: pd.Series, label: str) -> dict:
    s = series.dropna()
    if s.empty:
        return {}
    ann = s.mean() * 252
    vol = s.std(ddof=1) * np.sqrt(252)
    sr = ann / vol if vol > 0 else np.nan
    cum_series = (1 + s).cumprod()
    dd = float((cum_series / cum_series.cummax() - 1).min())
    return {
        "label": label, "n_days": len(s),
        "ann_return": float(ann), "ann_vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": dd, "cum": float(cum_series.iloc[-1] - 1),
    }


def main() -> None:
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    print("加载 margin universe (两融标的)...")
    margin_univ = load_margin_universe()
    print(f"  margin universe size: {len(margin_univ)}")

    print("构造 tradability mask (ST / 新股 / 低价 / 低流动)...")
    sub_price = price.loc["2023-07-01":end]  # 留 60 日 warm-up
    tradable = apply_tradability_filter(sub_price)
    print(f"  tradable mask shape: {tradable.shape}, 日均可交易股: {tradable.sum(axis=1).mean():.0f}")

    print("构造 RIAD...")
    factor = build_riad_neutral(start, end, price).shift(1)

    print("\n生成 filtered daily LS ...")
    daily = generate_daily_ls_filtered(factor, price, tradable, margin_univ, start, end)
    print(f"daily shape: {daily.shape}")
    print(f"日均 long 股数: {daily['n_long'].mean():.0f} | short 股数: {daily['n_short'].mean():.0f}")

    # 保存
    out_pq = ROOT / "logs" / "riad_tradable_universe_returns.parquet"
    daily.to_parquet(out_pq)
    print(f"保存: {out_pq}")

    # 和 baseline 对比
    baseline = pd.read_parquet(ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet")
    print("\n=== Baseline (无 filter) vs Filtered (tradable + margin shortable) ===\n")
    rows = []
    for lab, s, e in [
        ("FULL 2023-10~2025-12", start, end),
        ("IS 2023-10~2024-12", start, "2024-12-31"),
        ("OOS 2025", "2025-01-01", end),
    ]:
        b = summarize(baseline.loc[s:e, "net_ls"], f"{lab} baseline")
        f = summarize(daily.loc[s:e, "net_ls"], f"{lab} filtered")
        rows.append((lab, b, f))

    header = f"{'Segment':<22} {'Mode':<10} {'n':>5} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'MDD%':>8}"
    print(header)
    print("-" * len(header))
    for lab, b, f in rows:
        for mode, r in [("baseline", b), ("filtered", f)]:
            if not r:
                continue
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{lab:<22} {mode:<10} "
                f"{r['n_days']:>5} "
                f"{r['ann_return']*100:>+6.2f} "
                f"{r['ann_vol']*100:>5.2f} "
                f"{sr:>+6.2f} "
                f"{r['mdd']*100:>+7.2f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_tradable_universe_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "margin_universe_size": len(margin_univ),
                "avg_daily_long": float(daily["n_long"].mean()),
                "avg_daily_short": float(daily["n_short"].mean()),
                "results": {lab: {"baseline": b, "filtered": fl} for lab, b, fl in rows},
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"保存: {out_json}")


if __name__ == "__main__":
    main()
