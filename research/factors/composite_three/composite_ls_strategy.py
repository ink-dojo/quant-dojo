"""
3-因子 Composite Market-Neutral Long-Short 策略

在 composite_strategy.py (long-only) 基础上加 short leg 实现 beta 对冲:
    long  = top 30% signal
    short = bottom 30% signal
    LS ret = (long.mean - short.mean)  每期

同时对比:
    Q2Q3_minus_Q5 变体 (借用 RIAD 倒 U 发现): long = 40%-70% 分位, short = bottom 30%

成本: 双边 0.3% × 两腿 turnover = max 1.2% / 期
但合成因子更稳 → turnover 应低于单因子 (相关低时极端分位更一致)

注意: A 股融券成本暂用 0.3% 近似, 实际融券费约 6-8% ann (单边 0.5-0.7% /月).
     此处保守估计, 实盘需重新校准.
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
from research.factors.composite_three.composite_strategy import (  # noqa: E402
    PRICE_PATH,
    _to_ts,
    build_composite,
)
from research.factors.moneyflow_divergence.factor import compute_mfd_factor  # noqa: E402
from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.industry_eval import load_industry_series  # noqa: E402
from research.factors.retail_inst_divergence.neutralize_eval import (  # noqa: E402
    load_circ_mv_wide,
    size_neutralize,
)
from utils.factor_analysis import industry_neutralize_fast  # noqa: E402

START, END = "2023-10-01", "2025-12-31"
COST_ONE_WAY = 0.0015
HOLD_DAYS = 20


def ls_backtest(
    signal: pd.DataFrame,
    price: pd.DataFrame,
    long_low: float,
    long_high: float,
    short_low: float,
    short_high: float,
    hold_days: int = HOLD_DAYS,
) -> list[dict]:
    """
    通用 LS 回测: long = 分位 [long_low, long_high], short = 分位 [short_low, short_high].
    分位是 0~1 浮点, e.g. top 30% = [0.7, 1.0].
    """
    all_dates = signal.index.intersection(price.index)
    rebal_dates = all_dates[::hold_days]

    records = []
    prev_long: set[str] = set()
    prev_short: set[str] = set()
    for i, d in enumerate(rebal_dates[:-1]):
        s = signal.loc[d].dropna()
        if len(s) < 100:
            continue
        q_ll = s.quantile(long_low)
        q_lh = s.quantile(long_high)
        q_sl = s.quantile(short_low)
        q_sh = s.quantile(short_high)

        long_syms = list(s[(s >= q_ll) & (s <= q_lh)].index)
        short_syms = list(s[(s >= q_sl) & (s <= q_sh)].index)

        next_d = rebal_dates[i + 1]
        p0, p1 = price.loc[d], price.loc[next_d]
        rets = (p1 / p0 - 1.0).dropna()

        lr = rets.reindex(long_syms).dropna()
        sr = rets.reindex(short_syms).dropna()
        if len(lr) < 10 or len(sr) < 10:
            continue

        long_mean = float(lr.mean())
        short_mean = float(sr.mean())
        gross = long_mean - short_mean

        # two-leg turnover
        new_long = set(long_syms)
        new_short = set(short_syms)
        tl = len(new_long.symmetric_difference(prev_long)) / max(
            len(new_long | prev_long), 1
        )
        ts_ = len(new_short.symmetric_difference(prev_short)) / max(
            len(new_short | prev_short), 1
        )
        if not prev_long:
            tl = 1.0
        if not prev_short:
            ts_ = 1.0
        cost = (tl + ts_) * COST_ONE_WAY  # 每腿 buy+sell 已经在 symmetric diff 中体现
        net = gross - cost

        prev_long, prev_short = new_long, new_short
        records.append({
            "date": str(d.date()),
            "n_long": int(len(lr)),
            "n_short": int(len(sr)),
            "long_mean": long_mean,
            "short_mean": short_mean,
            "gross": gross,
            "net": net,
            "turnover_avg": float((tl + ts_) / 2),
            "cost": float(cost),
        })
    return records


def summarize_ls(records: list[dict], label: str) -> dict:
    if not records:
        return {}
    rets = np.array([r["net"] for r in records])
    periods_per_year = 252 / HOLD_DAYS
    ann_ret = rets.mean() * periods_per_year
    ann_vol = rets.std(ddof=1) * np.sqrt(periods_per_year)
    sr = ann_ret / ann_vol if ann_vol > 0 else np.nan
    cum = np.cumprod(1 + rets) - 1
    peak = np.maximum.accumulate(np.cumprod(1 + rets))
    dd = (np.cumprod(1 + rets) - peak) / peak
    mdd = float(dd.min()) if len(dd) else 0.0
    return {
        "label": label,
        "n_periods": len(rets),
        "ann_return": float(ann_ret),
        "ann_vol": float(ann_vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "mdd": mdd,
        "cum_net": float(cum[-1]) if len(cum) else 0.0,
        "avg_turnover": float(np.mean([r["turnover_avg"] for r in records])),
        "win_rate": float((rets > 0).mean()),
    }


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]
    cal = price.loc[START:END].index

    print("构造 RIAD (size+ind)...")
    panels = build_attention_panel(START, END, cal)
    riad_raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    circ_mv = load_circ_mv_wide(START, END)
    riad_sn = size_neutralize(riad_raw, circ_mv)
    ind_series = load_industry_series()
    riad = industry_neutralize_fast(riad_sn, ind_series)

    print("构造 MFD / BGFD...")
    mfd = compute_mfd_factor("2023-07-15", END, window=20, min_coverage=500)
    br_raw = load_broker_recommend("2023-07", "2025-12")
    cons = compute_consensus_streak(br_raw)
    bgfd = compute_bgfd_factor(cons, sorted(cons["month_i"].unique()))

    print("构造 composite 信号...")
    signal = build_composite(riad, mfd, bgfd, cal)
    signal_exec = signal.shift(1)

    # 三种变体:
    variants = {
        "Top30_Short30": dict(long_low=0.7, long_high=1.0, short_low=0.0, short_high=0.3),
        "Q2Q3_Short_Q5": dict(long_low=0.2, long_high=0.6, short_low=0.8, short_high=1.0),
        "Top20_Short20": dict(long_low=0.8, long_high=1.0, short_low=0.0, short_high=0.2),
    }

    all_results = {}
    for v_name, kwargs in variants.items():
        print(f"\n── {v_name} ──")
        records_full = ls_backtest(signal_exec.loc[START:END], price.loc[START:END], **kwargs)
        records_is = ls_backtest(
            signal_exec.loc["2023-10-01":"2024-12-31"],
            price.loc["2023-10-01":"2024-12-31"], **kwargs,
        )
        records_oos = ls_backtest(
            signal_exec.loc["2025-01-01":"2025-12-31"],
            price.loc["2025-01-01":"2025-12-31"], **kwargs,
        )
        res = {
            "FULL": summarize_ls(records_full, "FULL"),
            "IS": summarize_ls(records_is, "IS"),
            "OOS 2025": summarize_ls(records_oos, "OOS 2025"),
        }
        all_results[v_name] = res
        header = f"  {'Segment':<12} {'N':>3} {'Ann%':>7} {'Vol%':>6} {'Sharpe':>7} {'MDD%':>8} {'Turn%':>8} {'Win%':>6}"
        print(header)
        for lab in ["FULL", "IS", "OOS 2025"]:
            r = res[lab]
            if not r:
                continue
            sr_val = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"  {lab:<12} {r['n_periods']:>3} "
                f"{r['ann_return']*100:>6.2f} "
                f"{r['ann_vol']*100:>5.2f} "
                f"{sr_val:>7.2f} "
                f"{r['mdd']*100:>7.2f} "
                f"{r['avg_turnover']*100:>7.2f} "
                f"{r['win_rate']*100:>5.1f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"composite_ls_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "strategy": "3-factor composite LS (market-neutral)",
                "hold_days": HOLD_DAYS,
                "cost_one_way": COST_ONE_WAY,
                "variants": all_results,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
