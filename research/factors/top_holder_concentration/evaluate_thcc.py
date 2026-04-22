"""
THCC 月频 LS 评估

为对齐 RIAD/MFD/BGFD 的 20 日 fwd 月频框架:
    每个月末 d: 对每只股票取"在 d 之前最近一次 ann_date 的 thcc 值",
                 作为当月 signal (若 ann_date > 180 天前则视为陈旧, 置 NaN)
    持有 20 交易日
    top 30% 做多 (机构加仓), bot 30% 做空 (机构撤离)

分段: IS 2018-2024, OOS 2025
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

from research.factors.top_holder_concentration.factor import (  # noqa: E402
    compute_thcc_factors,
    load_top10_float,
)

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
HOLD = 20
COST_ONE_WAY = 0.0015
STALE_DAYS = 180  # 超过 180 天未更新视为陈旧


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


def ffill_with_staleness(
    event_wide: pd.DataFrame,
    target_index: pd.DatetimeIndex,
    stale_days: int = STALE_DAYS,
) -> pd.DataFrame:
    """
    对 event_wide (index=ann_date, columns=ts_code) 做 forward-fill 到 target_index.
    超过 stale_days 的 fill 视为 stale, 置 NaN.
    """
    combined_idx = target_index.union(event_wide.index).sort_values()
    combined = event_wide.reindex(combined_idx)
    filled = combined.ffill()

    # 对每列: 用 pandas 的 "上次非 NaN 日" 技巧
    # 构造一个"日期值"宽表, 只在非 NaN 处记录当前日, 其余 NaN, ffill 得到每个位置上一次事件日
    date_stamps = pd.DataFrame(
        np.where(combined.notna().values, combined_idx.values[:, None], pd.NaT),
        index=combined_idx, columns=combined.columns,
    ).ffill()
    # age = current_date - last_event_date (days)
    cur = pd.Series(combined_idx, index=combined_idx)
    age = date_stamps.apply(
        lambda col: (cur - pd.to_datetime(col)).dt.days, axis=0
    )
    out = filled.where(age <= stale_days, np.nan)
    return out.reindex(target_index)


def run_ls_monthly(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    start: str,
    end: str,
    top_pct: float = 0.3,
    bot_pct: float = 0.3,
) -> list[dict]:
    all_dates = price.loc[start:end].index
    rebal = all_dates[::HOLD]
    records = []
    prev_long: set[str] = set()
    prev_short: set[str] = set()
    for i, d in enumerate(rebal[:-1]):
        if d not in factor.index:
            continue
        s = factor.loc[d].dropna()
        if len(s) < 100:
            continue
        q_top = s.quantile(1 - top_pct)
        q_bot = s.quantile(bot_pct)
        long_syms = list(s[s >= q_top].index)
        short_syms = list(s[s <= q_bot].index)

        next_d = rebal[i + 1]
        p0, p1 = price.loc[d], price.loc[next_d]
        rets = (p1 / p0 - 1.0).dropna()
        lr = rets.reindex(long_syms).dropna()
        sr = rets.reindex(short_syms).dropna()
        if len(lr) < 10 or len(sr) < 10:
            continue

        long_mean = float(lr.mean())
        short_mean = float(sr.mean())
        gross = long_mean - short_mean

        new_long, new_short = set(long_syms), set(short_syms)
        tl = len(new_long.symmetric_difference(prev_long)) / max(len(new_long | prev_long), 1) if prev_long else 1.0
        ts_ = len(new_short.symmetric_difference(prev_short)) / max(len(new_short | prev_short), 1) if prev_short else 1.0
        cost = (tl + ts_) * COST_ONE_WAY
        net = gross - cost
        prev_long, prev_short = new_long, new_short

        records.append({
            "date": str(d.date()),
            "n_long": len(lr),
            "n_short": len(sr),
            "long_mean": long_mean,
            "short_mean": short_mean,
            "gross": gross,
            "net": net,
            "turnover_avg": float((tl + ts_) / 2),
        })
    return records


def summarize(records, label):
    if not records:
        return {}
    rets = np.array([r["net"] for r in records])
    ppy = 252 / HOLD
    ann = rets.mean() * ppy
    vol = rets.std(ddof=1) * np.sqrt(ppy)
    sr = ann / vol if vol > 0 else np.nan
    cum = float(np.prod(1 + rets) - 1)
    return {
        "label": label,
        "n_periods": len(rets),
        "ann_return": float(ann),
        "ann_vol": float(vol),
        "sharpe": float(sr) if not np.isnan(sr) else None,
        "cum_net": cum,
        "win_rate": float((rets > 0).mean()),
    }


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    price.columns = [_to_ts(c) for c in price.columns]

    print("加载 top10_floatholders (2018-2025)...")
    raw = load_top10_float(2018, 2025)
    print(f"raw rows: {len(raw)}")
    fac = compute_thcc_factors(raw)

    # 对两个变体做评估
    for key in ["thcc_all", "thcc_inst"]:
        wide = fac[key]
        # 重要: ann_date wide 的 index 不连续, 需 ffill 到 price 交易日
        target_idx = price.loc["2018-06-01":"2025-12-31"].index
        factor_daily = ffill_with_staleness(wide, target_idx)
        print(f"\n{key}: ffilled shape = {factor_daily.shape}, 日均有效股 {factor_daily.notna().sum(axis=1).mean():.0f}")

        records_full = run_ls_monthly(factor_daily, price, "2018-06-01", "2025-12-31")
        records_is = run_ls_monthly(factor_daily, price, "2018-06-01", "2024-12-31")
        records_oos = run_ls_monthly(factor_daily, price, "2025-01-01", "2025-12-31")

        print(f"  === {key} 月频 LS ===")
        for lab, recs in [("FULL 2018-2025", records_full), ("IS 2018-2024", records_is), ("OOS 2025", records_oos)]:
            s = summarize(recs, lab)
            if not s:
                continue
            sr = s["sharpe"] if s["sharpe"] is not None else float("nan")
            print(
                f"  {lab:<16} n={s['n_periods']:>3} "
                f"Ann={s['ann_return']*100:>+6.2f}% "
                f"Vol={s['ann_vol']*100:>6.2f}% "
                f"Sharpe={sr:>+6.2f} "
                f"Win={s['win_rate']*100:>5.1f}% "
                f"Cum={s['cum_net']*100:>+7.2f}%"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"thcc_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "THCC (Top-Holder Concentration Change)",
                "variants": ["thcc_all", "thcc_inst"],
                "hold_days": HOLD,
                "cost_one_way": COST_ONE_WAY,
                "stale_days": STALE_DAYS,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
