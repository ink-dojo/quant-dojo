"""
RIAD Fold 3 诊断 — 月度 IC + Long/Short leg attribution

看衰减是:
    (A) 突发 (某个月 IC 从 +0.07 掉到 -0.05) → 事件驱动 (数据规则改动?)
    (B) 渐进 (每月 IC 逐步下滑) → factor decay (normal erosion)
    (C) 只有某条腿垮 (long 或 short) → 分析为何某端失效

Benchmark = 等权 tradable universe (每日).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
DAILY_PATH = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"

from utils.tradability_filter import apply_tradability_filter  # noqa: E402
from research.factors.retail_inst_divergence.daily_returns import _to_ts  # noqa: E402


def _monthly_sharpe(daily: pd.Series) -> pd.Series:
    """按自然月聚合 Sharpe (月度 ann 口径)."""
    def _ann(x):
        x = x.dropna()
        if len(x) < 5:
            return np.nan
        mu = x.mean() * 252
        sd = x.std(ddof=1) * np.sqrt(252)
        return mu / sd if sd > 0 else np.nan
    return daily.resample("ME").apply(_ann)


def _monthly_ret(daily: pd.Series) -> pd.Series:
    return daily.resample("ME").apply(lambda x: (1 + x.dropna()).prod() - 1)


def main() -> None:
    daily = pd.read_parquet(DAILY_PATH)
    print(f"daily shape: {daily.shape}")

    # 构造等权 tradable benchmark
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    tradable = apply_tradability_filter(price.loc["2023-07-01":"2025-12-31"])
    pct = price.pct_change()

    bench_rets = []
    for d in daily.index:
        if d not in tradable.index or d not in pct.index:
            bench_rets.append(np.nan); continue
        tm = tradable.loc[d]
        syms = tm.index[tm].tolist()
        row = pct.loc[d]
        valid = [s for s in syms if s in row.index]
        bench_rets.append(float(row[valid].mean(skipna=True)) if valid else np.nan)
    bench = pd.Series(bench_rets, index=daily.index, name="bench_eqwt")

    # Leg returns (vs benchmark)
    # long_excess = long - benchmark        ← 做多超额
    # short_excess = benchmark - short      ← 做空超额 (空的股票跑输 benchmark 才赚)
    long_excess = (daily["gross_long"] - bench).rename("long_excess")
    short_excess = (bench - daily["gross_short"]).rename("short_excess")
    ls_net = daily["net_ls"].rename("ls_net")
    bench_s = bench.rename("bench")

    df = pd.concat([ls_net, long_excess, short_excess, bench_s], axis=1).dropna(subset=["ls_net"])
    print(f"对齐后 shape: {df.shape}")

    # 月度 Sharpe 时间线
    print("\n=== 月度 Sharpe (ann 口径, 单月数据) ===\n")
    monthly = pd.DataFrame({
        "ls_sharpe": _monthly_sharpe(df["ls_net"]),
        "long_excess_sharpe": _monthly_sharpe(df["long_excess"]),
        "short_excess_sharpe": _monthly_sharpe(df["short_excess"]),
        "ls_ret": _monthly_ret(df["ls_net"]),
        "long_excess_ret": _monthly_ret(df["long_excess"]),
        "short_excess_ret": _monthly_ret(df["short_excess"]),
        "bench_ret": _monthly_ret(df["bench"]),
    })
    # 打印
    header = f"{'Month':<10} {'LS SR':>7} {'Long exc SR':>12} {'Short exc SR':>13} "\
             f"{'LS %':>6} {'Long exc %':>11} {'Short exc %':>12} {'Bench %':>8}"
    print(header)
    print("-" * len(header))
    for idx, row in monthly.iterrows():
        ym = idx.strftime("%Y-%m")
        def _f(v, p="{:+.2f}"):
            return p.format(v) if pd.notna(v) else "   n/a"
        print(
            f"{ym:<10} "
            f"{_f(row['ls_sharpe'], '{:+.2f}'):>7} "
            f"{_f(row['long_excess_sharpe'], '{:+.2f}'):>12} "
            f"{_f(row['short_excess_sharpe'], '{:+.2f}'):>13} "
            f"{_f(row['ls_ret']*100, '{:+.2f}'):>6} "
            f"{_f(row['long_excess_ret']*100, '{:+.2f}'):>11} "
            f"{_f(row['short_excess_ret']*100, '{:+.2f}'):>12} "
            f"{_f(row['bench_ret']*100, '{:+.2f}'):>8}"
        )

    # 分段汇总
    print("\n=== 分段 Sharpe + 累计超额 ===\n")
    segments = [
        ("2023-Q4 建仓期", "2023-10-01", "2023-12-31"),
        ("2024 H1", "2024-01-01", "2024-06-30"),
        ("2024 H2", "2024-07-01", "2024-12-31"),
        ("2025 H1", "2025-01-01", "2025-06-30"),
        ("2025 H2", "2025-07-01", "2025-12-31"),
    ]

    seg_records = []
    header = f"{'Segment':<18} {'n':>4} {'LS SR':>7} {'L exc SR':>10} {'S exc SR':>10} "\
             f"{'LS cum%':>8} {'L exc cum%':>11} {'S exc cum%':>11}"
    print(header)
    print("-" * len(header))
    for lab, s, e in segments:
        sub = df.loc[s:e]
        if sub.empty:
            continue
        def _sr(x):
            x = x.dropna()
            if len(x) < 5:
                return np.nan
            mu, sd = x.mean() * 252, x.std(ddof=1) * np.sqrt(252)
            return mu / sd if sd > 0 else np.nan
        ls_sr = _sr(sub["ls_net"])
        lex_sr = _sr(sub["long_excess"])
        sex_sr = _sr(sub["short_excess"])
        ls_cum = (1 + sub["ls_net"].dropna()).prod() - 1
        lex_cum = (1 + sub["long_excess"].dropna()).prod() - 1
        sex_cum = (1 + sub["short_excess"].dropna()).prod() - 1
        seg_records.append({
            "segment": lab,
            "n_days": len(sub),
            "ls_sharpe": float(ls_sr) if pd.notna(ls_sr) else None,
            "long_excess_sharpe": float(lex_sr) if pd.notna(lex_sr) else None,
            "short_excess_sharpe": float(sex_sr) if pd.notna(sex_sr) else None,
            "ls_cum": float(ls_cum),
            "long_excess_cum": float(lex_cum),
            "short_excess_cum": float(sex_cum),
        })
        print(
            f"{lab:<18} {len(sub):>4} "
            f"{ls_sr:>+6.2f} "
            f"{lex_sr:>+9.2f} "
            f"{sex_sr:>+9.2f} "
            f"{ls_cum*100:>+7.2f} "
            f"{lex_cum*100:>+10.2f} "
            f"{sex_cum*100:>+10.2f}"
        )

    # 保存
    out_parquet = ROOT / "logs" / "riad_fold3_monthly_attribution.parquet"
    monthly.to_parquet(out_parquet)
    out_detail = ROOT / "logs" / "riad_fold3_daily_attribution.parquet"
    df.to_parquet(out_detail)

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_fold3_attribution_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "monthly_series": {idx.strftime("%Y-%m"): {
                k: (float(v) if pd.notna(v) else None) for k, v in row.items()
            } for idx, row in monthly.iterrows()},
            "segments": seg_records,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
