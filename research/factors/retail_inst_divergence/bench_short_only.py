"""
RIAD 改造策略: "Long Benchmark - Short Q5"

月度 attribution 发现 RIAD long Q2Q3 leg 结构性跑输 benchmark.
全部 alpha 来自 short Q5. 直接替换 long leg 为 benchmark (等权 tradable universe):

    long_leg  = 等权 tradable 全 A (benchmark)
    short_leg = Q5 (top 20% RIAD 分数 = 散户追涨股)
    net_ret   = bench_ret - Q5_ret - cost

成本估计:
    long_bench 的换手 ~ 10%/月 (tradable universe 变化 + rebalance 微调)
    short_Q5 的换手 ~ 70%/月 (每月一换, 变化大)
    cost = (0.1 + 0.7) × 0.15% × 2 (每月 buy+sell)  ≈ 0.24%/期

比较 baseline (Q2Q3-Q5 LS):
    预期 Sharpe 上升 (扔掉 long-side noise)
    MDD 可能上升 (benchmark beta 未对冲)
    OOS 2025 H2 是否真的有改善 (因 short_excess 降到 +1.05)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from research.factors.retail_inst_divergence.daily_returns import (  # noqa: E402
    COST_ONE_WAY, PRICE_PATH, REBALANCE_DAYS, SHORT_HIGH, SHORT_LOW,
    _to_ts, build_riad_neutral,
)
from utils.tradability_filter import apply_tradability_filter  # noqa: E402


def build_bench_short_daily(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    tradable: pd.DataFrame,
    start: str,
    end: str,
    margin_univ: set[str] | None = None,
) -> pd.DataFrame:
    """
    每日 daily LS:
        long_leg  = tradable universe 等权 (每日重取 tradable 子集)
        short_leg = RIAD top 20% (Q5), 20 日调仓, optional margin filter
    """
    dates = price.loc[start:end].index
    rebal = dates[::REBALANCE_DAYS]
    pct = price.pct_change()

    short_sets = []
    for d in rebal:
        if d not in factor.index:
            short_sets.append(set()); continue
        s = factor.loc[d].dropna()
        if len(s) < 100:
            short_sets.append(set()); continue
        q_lo, q_hi = s.quantile(SHORT_LOW), s.quantile(SHORT_HIGH)
        cand = s[(s >= q_lo) & (s <= q_hi)].index
        if d in tradable.index:
            tm = tradable.loc[d]
            cand = [c for c in cand if c in tm.index and tm[c]]
        if margin_univ is not None:
            cand = [c for c in cand if c in margin_univ]
        short_sets.append(set(cand))

    rebal_idx = pd.DatetimeIndex(rebal)
    recs = []
    prev_long_size = 0
    prev_short = set()
    prev_pos = -1
    for d in dates:
        pos = rebal_idx.searchsorted(d, side="right") - 1
        if pos < 0 or d not in pct.index or d not in tradable.index:
            recs.append({"date": d, "bench_r": np.nan, "short_r": np.nan,
                         "gross_ls": np.nan, "cost": 0.0, "net_ls": np.nan,
                         "n_long": 0, "n_short": 0})
            continue

        # long = tradable universe 等权 (每日重算)
        tm = tradable.loc[d]
        long_syms = tm.index[tm].tolist()
        row = pct.loc[d]
        valid_long = [s for s in long_syms if s in row.index]
        bench_r = float(row[valid_long].mean(skipna=True)) if valid_long else 0.0

        # short = Q5
        cur_short = short_sets[pos]
        short_syms = [s for s in cur_short if s in row.index]
        short_r = float(row[short_syms].mean(skipna=True)) if short_syms else 0.0

        gross_ls = bench_r - short_r

        # cost
        is_rebal = (pos != prev_pos)
        prev_pos = pos
        cost = 0.0
        if is_rebal:
            # long benchmark 换手按 10% 估算 (tradable set 每月微调)
            # 更保守: 假设 long side 没有主动换手, cost 只来自 rebalance 带入新股
            bench_turn = 0.10
            if pos > 0:
                old_short = short_sets[pos - 1]
                short_turn = len(cur_short.symmetric_difference(old_short)) / max(len(cur_short | old_short), 1)
            else:
                short_turn = 1.0
            cost = (bench_turn + short_turn) * COST_ONE_WAY
        net = gross_ls - cost

        prev_short = cur_short
        recs.append({
            "date": d, "bench_r": bench_r, "short_r": short_r,
            "gross_ls": gross_ls, "cost": cost, "net_ls": net,
            "n_long": len(valid_long), "n_short": len(short_syms),
        })

    return pd.DataFrame(recs).set_index("date")


def load_margin_universe() -> set[str]:
    mg = ROOT / "data" / "raw" / "tushare" / "margin"
    return {_to_ts(f.stem) for f in mg.glob("*.parquet")}


def summarize(s: pd.Series, label: str) -> dict:
    s = s.dropna()
    if s.empty:
        return {}
    ann = s.mean() * 252
    vol = s.std(ddof=1) * np.sqrt(252)
    sr = ann / vol if vol > 0 else np.nan
    cum = (1 + s).cumprod()
    mdd = float((cum / cum.cummax() - 1).min())
    return {
        "label": label, "n": len(s),
        "ann": float(ann), "vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": mdd, "cum": float(cum.iloc[-1] - 1),
    }


def main() -> None:
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    tradable = apply_tradability_filter(price.loc["2023-07-01":end])
    factor = build_riad_neutral(start, end, price).shift(1)
    margin_univ = load_margin_universe()

    # 两版本: 无 margin filter (回测上限) + 带 margin filter (实盘估计)
    print("=== 版本 A: unconstrained Q5 (回测上限) ===")
    daily_unrestr = build_bench_short_daily(factor, price, tradable, start, end)
    print(f"daily shape: {daily_unrestr.shape}, 日均 long={daily_unrestr['n_long'].mean():.0f} short={daily_unrestr['n_short'].mean():.0f}")

    print("\n=== 版本 B: margin-shortable Q5 (实盘估计) ===")
    daily_margin = build_bench_short_daily(factor, price, tradable, start, end, margin_univ)
    print(f"daily shape: {daily_margin.shape}, 日均 long={daily_margin['n_long'].mean():.0f} short={daily_margin['n_short'].mean():.0f}")

    baseline = pd.read_parquet(
        ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
    )["net_ls"]

    print("\n=== 对比汇总 ===\n")
    rows = []
    for lab, s, e in [
        ("FULL 2023-10~2025-12", start, end),
        ("2024 H1", "2024-01-01", "2024-06-30"),
        ("2024 H2", "2024-07-01", "2024-12-31"),
        ("2025 H1", "2025-01-01", "2025-06-30"),
        ("2025 H2", "2025-07-01", "2025-12-31"),
    ]:
        base = summarize(baseline.loc[s:e], f"{lab} Q2Q3-Q5 (baseline)")
        ver_a = summarize(daily_unrestr.loc[s:e, "net_ls"], f"{lab} Bench-Q5 unrestr")
        ver_b = summarize(daily_margin.loc[s:e, "net_ls"], f"{lab} Bench-Q5 margin")
        rows.append((lab, base, ver_a, ver_b))

    header = f"{'Segment':<22} {'Strategy':<26} {'n':>4} {'Ann%':>7} {'Vol%':>6} {'SR':>6} {'MDD%':>8}"
    print(header)
    print("-" * len(header))
    for lab, b, a, c in rows:
        for mode, r in [("baseline Q2Q3-Q5", b),
                         ("Bench-Q5 unconstrained", a),
                         ("Bench-Q5 margin filter", c)]:
            if not r:
                continue
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{lab:<22} {mode:<26} "
                f"{r['n']:>4} "
                f"{r['ann']*100:>+6.2f} "
                f"{r['vol']*100:>5.2f} "
                f"{sr:>+5.2f} "
                f"{r['mdd']*100:>+7.2f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_bench_short_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "strategy": "Long Bench(tradable eqwt) - Short Q5 (RIAD top 20%)",
            "results": {lab: {"baseline": b, "unrestr": a, "margin_filter": c}
                        for lab, b, a, c in rows},
        }, f, indent=2, ensure_ascii=False)
    print(f"\n保存: {out_json}")

    out_pq = ROOT / "logs" / "riad_bench_short_daily.parquet"
    daily_margin.to_parquet(out_pq)
    print(f"保存 (margin filter): {out_pq}")


if __name__ == "__main__":
    main()
