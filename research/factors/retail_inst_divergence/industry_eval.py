"""
RIAD 行业 + 市值 双中性化评估

继续 neutralize_eval.py (size-only) 的工作流, 加一层 SW 1 级行业 demean,
验证 RIAD alpha 不是行业风格/板块轮动代理.

行业数据: data/raw/fundamentals/industry_sw.parquet
         (5805 股 × 396 SW 3 级行业, 取前 2 位 = SW 1 级 ≈ 28 行业)
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
from research.factors.retail_inst_divergence.neutralize_eval import (  # noqa: E402
    load_circ_mv_wide,
    size_neutralize,
)
from utils.factor_analysis import industry_neutralize_fast  # noqa: E402

IND_PATH = ROOT / "data" / "raw" / "fundamentals" / "industry_sw.parquet"
IS_START, IS_END = "2023-10-01", "2024-12-31"
OOS_START, OOS_END = "2025-01-01", "2025-12-31"


def load_industry_series() -> pd.Series:
    """返回 pd.Series(index=ts_code, value=SW1-级行业前 2 位)."""
    df = pd.read_parquet(IND_PATH)

    def _to_ts(sym: str) -> str:
        s = str(sym).zfill(6)
        if s.startswith(("60", "68")):
            return f"{s}.SH"
        if s.startswith(("00", "30", "001", "002", "003")):
            return f"{s}.SZ"
        if s[:1] in ("4", "8"):
            return f"{s}.BJ"
        return f"{s}.SZ"

    df["ts_code"] = df["symbol"].apply(_to_ts)
    df["sw1"] = df["industry_code"].astype(str).str[:2]
    ser = df.set_index("ts_code")["sw1"]
    ser = ser[~ser.index.duplicated(keep="first")]
    return ser


def main() -> None:
    full_start, full_end = IS_START, OOS_END

    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[full_start:full_end].index
    print(f"交易日历: {len(cal)} 日")

    print("构造 RIAD raw...")
    panels = build_attention_panel(full_start, full_end, cal)
    factor_raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])

    print("Step 1: size-neutralize...")
    circ_mv = load_circ_mv_wide(full_start, full_end)
    factor_size_n = size_neutralize(factor_raw, circ_mv)

    print("Step 2: industry-neutralize (SW 1 级)...")
    ind_series = load_industry_series()
    print(f"  SW1 行业数: {ind_series.nunique()}  (样本 industry 代码: {sorted(ind_series.unique())[:5]}...)")

    factor_full_n = industry_neutralize_fast(factor_size_n, ind_series)
    daily_count = factor_full_n.notna().sum(axis=1)
    factor_full_n = factor_full_n.where(daily_count >= 200, np.nan)
    print(f"full-neutral factor 日均有效股: {factor_full_n.notna().sum(axis=1).mean():.0f}")

    # 行业中性化后与 size-only 的相关
    s1 = factor_size_n.stack()
    s2 = factor_full_n.stack()
    common_idx = s1.index.intersection(s2.index)
    corr = s1.loc[common_idx].corr(s2.loc[common_idx])
    print(f"size-neut vs (size+ind)-neut 相关度: {corr:.4f}")

    fwd_ret, _ = load_forward_returns(full_start, full_end, FWD_DAYS)
    factor_shift = factor_full_n.shift(1)

    results = {}
    for label, s, e in [
        ("FULL (size+ind)", full_start, full_end),
        ("IS 2023-10~2024-12 (size+ind)", IS_START, IS_END),
        ("OOS 2025 (size+ind)", OOS_START, OOS_END),
    ]:
        print(f"\n────── {label} ──────")
        results[label] = evaluate_segment(factor_shift, fwd_ret, label, s, e)

    print("\n=== RIAD size+industry neutral 汇总 ===")
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
    out_json = ROOT / "logs" / f"riad_industry_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "RIAD (size + SW1 industry neutral)",
                "size_vs_full_neut_corr": float(corr),
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
