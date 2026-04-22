"""
MFD 因子评估 — IC/ICIR + 分层回测 + 2025 OOS 对比

样本分段:
    IS (长): 2020-06-01 ~ 2024-12-31 (覆盖完整数据期)
    OOS (2025): 2025-01-01 ~ 2025-12-31
持仓窗口: 20 交易日 (fwd return)
采样频率: 每 5 交易日 (周频) 抑制 IC 自相关
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

from research.factors.moneyflow_divergence.factor import compute_mfd_factor  # noqa: E402
from research.factors.retail_inst_divergence.evaluate_riad import (  # noqa: E402
    FWD_DAYS,
    PRICE_PATH,
    evaluate_segment,
    load_forward_returns,
)

IS_START, IS_END = "2020-06-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2025-12-31"


def main() -> None:
    full_start, full_end = IS_START, OOS_END

    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[full_start:full_end].index
    print(f"交易日历: {len(cal)} 日")

    # 因子. 为保留 rolling-20 window, 加 40 日 warm-up
    factor = compute_mfd_factor(
        "2020-04-01", full_end, window=20, min_coverage=500,
    )
    print(f"MFD factor 宽表: {factor.shape}, 日均有效股: {factor.notna().sum(axis=1).mean():.0f}")

    fwd_ret, _ = load_forward_returns(full_start, full_end, FWD_DAYS)
    factor_shift = factor.shift(1)

    results = {}
    for label, s, e in [
        ("FULL", full_start, full_end),
        ("IS 2020-06~2024-12", IS_START, IS_END),
        ("OOS 2025", OOS_START, OOS_END),
    ]:
        print(f"\n────── {label} ──────")
        results[label] = evaluate_segment(factor_shift, fwd_ret, label, s, e)

    print("\n=== MFD 汇总 ===")
    for lab, r in results.items():
        print(
            f"[{lab}] n={r['n_obs']}  "
            f"IC={r['IC_mean']:+.4f}  ICIR={r['ICIR']:+.3f}  "
            f"HAC t={r['t_stat_hac']:+.2f}  "
            f"LS_mean={r['LS_mean_per_period']:+.4%}  "
            f"pct_pos={r['pct_pos']:.1%}"
        )
        qs = r["quintile_means"]
        if qs:
            print("  分层均值 (20 日持有):  " + "  ".join(f"{k}={v:+.2%}" for k, v in qs.items()))

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"mfd_eval_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "MFD (MoneyFlow Divergence: elg_ratio - sm_ratio)",
                "fwd_days": FWD_DAYS,
                "window": 20,
                "sample_cadence_days": 5,
                "segments": results,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
