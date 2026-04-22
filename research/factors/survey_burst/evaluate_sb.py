"""
SB 因子评估 (IC + 月频 LS)

样本期: 2024-01-01 ~ 2025-12-31 (留 warm-up)
fwd_days: 20 (月频调仓, 和 RIAD/MFD 一致)
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

from research.factors.retail_inst_divergence.evaluate_riad import (  # noqa: E402
    FWD_DAYS,
    PRICE_PATH,
    evaluate_segment,
    load_forward_returns,
)
from research.factors.survey_burst.factor import (  # noqa: E402
    compute_sb_factor,
    load_survey_counts,
)

IS_END = "2024-12-31"
OOS_START = "2025-01-01"


def main() -> None:
    start, end = "2023-10-01", "2025-12-31"
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[start:end].index
    print(f"交易日历: {len(cal)} 日")

    long = load_survey_counts(start, end)
    print(f"survey long rows: {len(long)}")
    sb = compute_sb_factor(long, cal)
    print(f"SB wide: {sb.shape}, 日均有效股: {sb.notna().sum(axis=1).mean():.0f}")

    fwd_ret, _ = load_forward_returns(start, end, FWD_DAYS)
    sb_shift = sb.shift(1)

    results = {}
    for label, s, e in [
        ("FULL", "2024-01-01", end),  # 留 warm-up 到 2024-01
        ("IS 2024", "2024-01-01", IS_END),
        ("OOS 2025", OOS_START, end),
    ]:
        print(f"\n────── {label} ──────")
        results[label] = evaluate_segment(sb_shift, fwd_ret, label, s, e)

    def _fmt(v, pat):
        return pat.format(v) if v is not None and not (isinstance(v, float) and np.isnan(v)) else "   n/a"

    print("\n=== SB 汇总 ===")
    for lab, r in results.items():
        print(
            f"[{lab}] n={r['n_obs']}  "
            f"IC={_fmt(r['IC_mean'], '{:+.4f}')}  ICIR={_fmt(r['ICIR'], '{:+.3f}')}  "
            f"HAC t={_fmt(r['t_stat_hac'], '{:+.2f}')}  "
            f"LS_mean={_fmt(r['LS_mean_per_period'], '{:+.4%}')}  "
            f"pct_pos={_fmt(r['pct_pos'], '{:.1%}')}"
        )
        qs = r["quintile_means"]
        if qs:
            print("  分层均值 (20 日持有): " + "  ".join(f"{k}={v:+.2%}" for k, v in qs.items()))

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"sb_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "SB (Survey Burst: 7d / 91d median)",
                "fwd_days": FWD_DAYS,
                "sample_cadence_days": 5,
                "segments": results,
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
