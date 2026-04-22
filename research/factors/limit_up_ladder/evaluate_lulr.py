"""
LULR 事件驱动评估 (5 日持有)

universe 小 (每日 ~100 股), 不做 cross-section IC.
改用"事件驱动 LS":
    每日 d: 从 limit_list 取 LULR 分数
    Top 20% (高连板+紧封) = 做空池
    Bot 20% (炸板/跌停) = 做多池
    持有 5 交易日后清仓

成本: 单边 0.15%, 双边 0.3% (每次进出清仓).
成本 drag: 每 5 日 0.3% = 年化 ~15% (极高)
    → LULR 需要绝对强信号才 net 正.

分段: IS 2019-2024, OOS 2025 (重点).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research.factors.limit_up_ladder.factor import (  # noqa: E402
    compute_lulr_factor,
    load_limit_list,
)

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
HOLD = 5  # 交易日
COST_ONE_WAY = 0.0015


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def event_backtest(wide: pd.DataFrame, price: pd.DataFrame, hold: int = HOLD) -> list[dict]:
    """每日触发: top/bot 各取 20%, 持有 hold 日."""
    records = []
    prices_idx = price.index
    for d in wide.index:
        scores = wide.loc[d].dropna()
        if len(scores) < 20:
            continue
        # 下一交易日为 entry, entry+hold 为 exit
        pos = prices_idx.searchsorted(d)
        if pos + hold + 1 >= len(prices_idx):
            continue
        entry_d = prices_idx[pos + 1]
        exit_d = prices_idx[pos + 1 + hold]

        q20_top = scores.quantile(0.8)
        q20_bot = scores.quantile(0.2)
        top_syms = list(scores[scores >= q20_top].index)  # 高位连板 → 做空
        bot_syms = list(scores[scores <= q20_bot].index)  # 炸板/跌停 → 做多 (反转)

        p_in = price.loc[entry_d]
        p_out = price.loc[exit_d]
        rets = (p_out / p_in - 1.0).dropna()

        top_r = rets.reindex(top_syms).dropna()
        bot_r = rets.reindex(bot_syms).dropna()
        if len(top_r) < 3 or len(bot_r) < 3:
            continue

        long_mean = float(bot_r.mean())
        short_mean = float(top_r.mean())
        gross_ls = long_mean - short_mean
        # 完整进出 → 双边成本
        cost = 2 * COST_ONE_WAY * 2  # 两腿 × 进出 = 0.6%
        net_ls = gross_ls - cost
        long_only_net = long_mean - 2 * COST_ONE_WAY  # 做多 bot 单边进出
        short_only_net = -short_mean - 2 * COST_ONE_WAY

        records.append({
            "date": str(d.date()),
            "n_top": int(len(top_r)),
            "n_bot": int(len(bot_r)),
            "long_mean": long_mean,
            "short_mean": short_mean,
            "ls_gross": float(gross_ls),
            "ls_net": float(net_ls),
            "long_only_net": float(long_only_net),
            "short_only_net": float(short_only_net),
        })
    return records


def summarize(records: list[dict], label: str, col: str, hold: int = HOLD) -> dict:
    if not records:
        return {}
    rets = np.array([r[col] for r in records])
    # 不是严格每 hold 日触发, 而是每日触发 + 持有 hold 日 (完全 overlap)
    # 所以 annualize 需要除以 hold (平均每日贡献)
    periods_per_year = 252 / hold
    ann_ret = rets.mean() * periods_per_year
    ann_vol = rets.std(ddof=1) * np.sqrt(periods_per_year)
    sr = ann_ret / ann_vol if ann_vol > 0 else np.nan
    return {
        "label": label,
        "col": col,
        "n_events": len(rets),
        "mean_per_event": float(rets.mean()),
        "std_per_event": float(rets.std(ddof=1)),
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "pct_pos": float((rets > 0).mean()),
    }


def main() -> None:
    full_start, full_end = "2019-01-01", "2025-12-31"

    print("加载 limit_list 2019-2025 ...")
    long = load_limit_list(full_start, full_end)
    wide = compute_lulr_factor(long)
    print(f"LULR 宽表: {wide.shape}, 每日平均上榜股数: {wide.notna().sum(axis=1).mean():.0f}")

    print("加载价格...")
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    # 全段
    records = event_backtest(wide.loc[full_start:full_end], price.loc[full_start:full_end])
    print(f"有效事件日: {len(records)}")

    df = pd.DataFrame(records)
    df["year"] = df["date"].astype(str).str[:4].astype(int)

    # 分段
    segments = [
        ("FULL 2019-2025", df["year"].between(2019, 2025)),
        ("IS 2019-2023", df["year"].between(2019, 2023)),
        ("IS 2024", df["year"] == 2024),
        ("OOS 2025", df["year"] == 2025),
    ]
    cols = ["ls_net", "long_only_net", "short_only_net"]

    all_results = {}
    for seg_name, mask in segments:
        sub = df[mask]
        if sub.empty:
            continue
        for c in cols:
            res = summarize(sub.to_dict("records"), seg_name, c)
            all_results.setdefault(seg_name, {})[c] = res

    print("\n=== LULR 5 日事件驱动 LS (双边 0.3%, 每腿 2 次) ===\n")
    header = f"{'Segment':<16} {'Strategy':<15} {'N':>5} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'Pct+%':>6}"
    print(header)
    print("-" * len(header))
    for seg, inner in all_results.items():
        for col, r in inner.items():
            if not r:
                continue
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{seg:<16} {col:<15} "
                f"{r['n_events']:>5} "
                f"{r['ann_return']*100:>6.2f} "
                f"{r['ann_vol']*100:>5.2f} "
                f"{sr:>7.2f} "
                f"{r['pct_pos']*100:>5.1f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"lulr_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "LULR — Limit-Up Ladder Reversal (5d hold)",
                "cost_one_way": COST_ONE_WAY,
                "hold_days": HOLD,
                "segments": all_results,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
