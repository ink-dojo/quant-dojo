"""
BGFD 月频 Long-Short 评估

因子仅在每月金股 universe 内打分 (通常 100-400 股), 做榜内 rank 回测:

    每月 m 末:
        pool_m = {被至少 1 家券商推荐的股票}
        score_m = BGFD zscore (within pool)
        top30_m = top 30% crowded (做空)
        bot30_m = bottom 30% fresh (做多)
    持有 ~21 交易日 (下月末收盘)
    L/S = 做多 bot30 - 做空 top30

双边成本 0.3% (fresh 上榜股通常流动性一般, 成本偏保守).

输出: logs/bgfd_eval_YYYYMMDD.json
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

from research.factors.broker_gold_fade.factor import (  # noqa: E402
    compute_bgfd_factor,
    compute_consensus_streak,
    load_broker_recommend,
)

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
COST_ONE_WAY = 0.0015
TOP_PCT = 0.30
BOT_PCT = 0.30


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    if sym[:1] in ("4", "8"):
        return f"{sym}.BJ"
    return f"{sym}.SZ"


def month_end_date(price: pd.DataFrame, year: int, month: int) -> pd.Timestamp | None:
    """返回 price.index 中属于该年月的最后一个交易日."""
    mask = (price.index.year == year) & (price.index.month == month)
    if not mask.any():
        return None
    return price.index[mask][-1]


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    print(f"price_wide 到 {price.index[-1].date()}")

    raw = load_broker_recommend("2020-03", "2026-04")
    print(f"broker_recommend 载入: {len(raw)} 行")
    cons = compute_consensus_streak(raw)
    months = sorted(cons["month_i"].unique())
    wide = compute_bgfd_factor(cons, months)
    print(f"BGFD 因子: {wide.shape}")

    # 每月 m: 用 m 月末价到 m+1 月末价作为 forward return
    period_rets: list[dict] = []
    for i, m in enumerate(months[:-1]):
        m_next = months[i + 1]
        y, mm = divmod(m, 100)
        y2, mm2 = divmod(m_next, 100)
        d0 = month_end_date(price, y, mm)
        d1 = month_end_date(price, y2, mm2)
        if d0 is None or d1 is None:
            continue

        if m not in wide.index:
            continue
        scores = wide.loc[m].dropna()
        if len(scores) < 50:
            continue
        q_top = scores.quantile(1 - TOP_PCT)
        q_bot = scores.quantile(BOT_PCT)
        top_syms = scores[scores >= q_top].index.tolist()
        bot_syms = scores[scores <= q_bot].index.tolist()

        p0, p1 = price.loc[d0], price.loc[d1]
        rets = (p1 / p0 - 1.0).dropna()

        top_r = rets.reindex(top_syms).dropna()
        bot_r = rets.reindex(bot_syms).dropna()

        if len(top_r) < 10 or len(bot_r) < 10:
            continue

        gross_ls = bot_r.mean() - top_r.mean()  # 做多 bot - 做空 top
        # 月度全换仓 → turnover = 1 each leg, cost = 2 * 2 * 0.15% = 0.6%
        net_ls = gross_ls - 0.006
        long_only = bot_r.mean() - 0.003  # 单边换仓成本 0.3%
        short_only = -top_r.mean() - 0.003

        period_rets.append({
            "month": int(m),
            "n_top": int(len(top_r)),
            "n_bot": int(len(bot_r)),
            "top_ret": float(top_r.mean()),
            "bot_ret": float(bot_r.mean()),
            "ls_gross": float(gross_ls),
            "ls_net": float(net_ls),
            "long_only_net": float(long_only),
            "short_only_net": float(short_only),
        })

    df = pd.DataFrame(period_rets)
    print(f"\n有效月份: {len(df)}")
    if df.empty:
        return

    # 分段
    df["year"] = df["month"].astype(str).str[:4].astype(int)
    results = {}
    for label, mask in [
        ("FULL", df["month"].notna()),
        ("IS 2020-2023", df["year"].between(2020, 2023)),
        ("IS 2024", df["year"] == 2024),
        ("OOS 2025", df["year"] == 2025),
    ]:
        sub = df[mask]
        if sub.empty:
            continue
        for col, label_col in [("ls_net", "LS_net"), ("long_only_net", "long_only"), ("short_only_net", "short_only")]:
            rets = sub[col].dropna().values
            if len(rets) == 0:
                continue
            ann = rets.mean() * 12
            vol = rets.std(ddof=1) * np.sqrt(12)
            sr = ann / vol if vol > 0 else np.nan
            cum = float(np.prod(1 + rets) - 1)
            wins = float((rets > 0).mean())
            results.setdefault(label, {})[label_col] = {
                "n_months": len(rets),
                "mean": float(rets.mean()),
                "ann_return": float(ann),
                "ann_vol": float(vol),
                "sharpe": float(sr) if not np.isnan(sr) else None,
                "cum_net": cum,
                "win_rate": wins,
            }

    print("\n=== BGFD 月频 Long-Short 汇总 (双边 0.3%) ===\n")
    header = f"{'Segment':<16} {'Strategy':<14} {'N':>4} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'Win%':>6} {'Cum%':>8}"
    print(header)
    print("-" * len(header))
    for seg, strats in results.items():
        for strat, r in strats.items():
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{seg:<16} {strat:<14} "
                f"{r['n_months']:>4} "
                f"{r['ann_return']*100:>6.2f} "
                f"{r['ann_vol']*100:>5.2f} "
                f"{sr:>7.2f} "
                f"{r['win_rate']*100:>5.1f} "
                f"{r['cum_net']*100:>7.2f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"bgfd_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "BGFD — Broker Gold-stock Fade Divergence",
                "cost_one_way": COST_ONE_WAY,
                "top_pct": TOP_PCT,
                "bot_pct": BOT_PCT,
                "segments": results,
                "per_month": period_rets,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
