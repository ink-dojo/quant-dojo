"""
RIAD + MFD 合成因子评估

观察:
    - RIAD IC 负 (散户关注高 → 未来差), 符合 Barber-Odean 直觉
    - MFD IC 负 (超大单净流入高 → 未来差), 反转假设 (派发/尾盘对倒)
    两者方向一致都是"反向信号", 但数据源完全独立, 应 provide 增量 alpha.

合成:
    combined = -zscore(RIAD_raw) + -zscore(MFD_raw)
             = -(RIAD_z + MFD_z)
    即做多 (RIAD 低 ∩ MFD 低) 的股票, 做空 (RIAD 高 ∩ MFD 高).

输出:
    logs/riad_mfd_combined_YYYYMMDD.json
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
from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.evaluate_riad import (  # noqa: E402
    FWD_DAYS,
    PRICE_PATH,
    evaluate_segment,
    load_forward_returns,
)

# 用 RIAD 的样本区间 (受 stk_surv 约束 2023-10 起)
START, END = "2023-10-01", "2025-12-31"
IS_END = "2024-12-31"
OOS_START = "2025-01-01"


def _zscore_row(df: pd.DataFrame) -> pd.DataFrame:
    mu = df.mean(axis=1)
    sd = df.std(axis=1).replace(0.0, np.nan)
    return df.sub(mu, axis=0).div(sd, axis=0)


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[START:END].index
    print(f"交易日历: {len(cal)} 日")

    print("构造 RIAD...")
    panels = build_attention_panel(START, END, cal)
    riad = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    print(f"  RIAD: {riad.shape}")

    print("构造 MFD (提前 40 日 warm-up)...")
    mfd = compute_mfd_factor("2023-07-15", END, window=20, min_coverage=500)
    print(f"  MFD: {mfd.shape}")

    # 对齐 index / columns (并集)
    common_dates = riad.index.intersection(mfd.index)
    common_syms = riad.columns.union(mfd.columns)
    riad_a = riad.reindex(index=common_dates, columns=common_syms)
    mfd_a = mfd.reindex(index=common_dates, columns=common_syms)

    # 相关性 sanity (截面, 跨时间均值)
    stacked_r = riad_a.stack()
    stacked_m = mfd_a.stack()
    common_idx = stacked_r.index.intersection(stacked_m.index)
    if len(common_idx):
        corr = stacked_r.loc[common_idx].corr(stacked_m.loc[common_idx])
        print(f"RIAD × MFD 点对相关度: {corr:+.4f}")

    # 合成: 每日截面 zscore 后相加, 再取负号 (做多低分)
    riad_z = _zscore_row(riad_a)
    mfd_z = _zscore_row(mfd_a)
    combined_raw = riad_z + mfd_z
    combined = -combined_raw  # 方向调整: 做多低 RIAD + 低 MFD

    daily_count = combined.notna().sum(axis=1)
    combined = combined.where(daily_count >= 200, np.nan)
    print(f"combined factor 日均有效股: {combined.notna().sum(axis=1).mean():.0f}")

    fwd_ret, _ = load_forward_returns(START, END, FWD_DAYS)
    combined_shift = combined.shift(1)

    results = {}
    for label, s, e in [
        ("FULL", START, END),
        ("IS 2023-10~2024-12", START, IS_END),
        ("OOS 2025", OOS_START, END),
    ]:
        print(f"\n────── {label} ──────")
        res = evaluate_segment(combined_shift, fwd_ret, label, s, e)
        # 因为我们 flip 了因子方向, 现在期望 IC 正, Qn_minus_Q1 长空
        # 但 evaluate_segment 用 Q1_minus_Qn, 所以 LS_mean 应为负, 实际多空收益 = -LS_mean
        res["long_short_actual_mean"] = -res["LS_mean_per_period"] if res["LS_mean_per_period"] is not None else None
        results[label] = res

    print("\n=== RIAD+MFD 合成汇总 (正向因子, 做多高分) ===")
    for lab, r in results.items():
        print(
            f"[{lab}] n={r['n_obs']}  "
            f"IC={r['IC_mean']:+.4f}  ICIR={r['ICIR']:+.3f}  "
            f"HAC t={r['t_stat_hac']:+.2f}  "
            f"LS_actual={r['long_short_actual_mean']:+.4%}  "
            f"pct_pos={r['pct_pos']:.1%}"
        )
        qs = r["quintile_means"]
        if qs:
            print("  分层均值 (20 日持有): " + "  ".join(f"{k}={v:+.2%}" for k, v in qs.items()))

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_mfd_combined_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "RIAD + MFD 合成 (等权 zscore, 反向)",
                "fwd_days": FWD_DAYS,
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
