"""
RIAD Fold 3 诊断 — 数据源覆盖度月度检查

看 2025 H2 是否出现以下异常:
    1. ths_hot / dc_hot 每日榜单覆盖股数变化
    2. stk_surv 每月机构调研事件数变化
    3. 因子 retail_attn / inst_attn 的 cross-section dispersion 变化
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    load_inst_surveys, load_retail_hot_daily,
)


def main():
    retail = load_retail_hot_daily("2023-10-01", "2025-12-31")
    inst = load_inst_surveys("2023-10-01", "2025-12-31")

    print(f"ths+dc A-share records: {len(retail)}")
    print(f"stk_surv records: {len(inst)}")

    retail["month"] = retail["trade_date"].dt.to_period("M")
    inst["month"] = inst["trade_date"].dt.to_period("M")

    # 每月: 总记录数 + 独立股票数
    retail_monthly = retail.groupby("month").agg(
        n_records=("ts_code", "count"),
        n_unique=("ts_code", "nunique"),
    ).reset_index()

    inst_monthly = inst.groupby("month").agg(
        n_records=("n_surv", "count"),
        n_unique=("ts_code", "nunique"),
        total_orgs=("n_surv", "sum"),
    ).reset_index()

    print("\n=== ths + dc 热榜 A 股记录 (每月) ===")
    print(f"{'Month':<10} {'N Records':>10} {'N Unique Stocks':>16}")
    for _, r in retail_monthly.iterrows():
        print(f"{str(r['month']):<10} {int(r['n_records']):>10} {int(r['n_unique']):>16}")

    print("\n=== stk_surv 机构调研 (每月) ===")
    print(f"{'Month':<10} {'N Events':>10} {'N Unique Stocks':>16} {'Total Orgs':>12}")
    for _, r in inst_monthly.iterrows():
        print(f"{str(r['month']):<10} {int(r['n_records']):>10} {int(r['n_unique']):>16} {int(r['total_orgs']):>12}")

    # 分段汇总
    segments = [
        ("2023-Q4", "2023-10", "2023-12"),
        ("2024 H1", "2024-01", "2024-06"),
        ("2024 H2", "2024-07", "2024-12"),
        ("2025 H1", "2025-01", "2025-06"),
        ("2025 H2", "2025-07", "2025-12"),
    ]

    print("\n=== 分段汇总 ===")
    print(f"{'Segment':<10} {'retail 日均条目':>15} {'retail 独立股':>13} {'surv 月均调研':>14} {'surv 独立股':>13} {'surv 总机构':>13}")
    seg_records = {}
    for lab, s, e in segments:
        rm = retail_monthly[(retail_monthly["month"] >= s) & (retail_monthly["month"] <= e)]
        im = inst_monthly[(inst_monthly["month"] >= s) & (inst_monthly["month"] <= e)]
        r_rec = rm["n_records"].mean() / 21 if len(rm) else np.nan  # 日均
        r_uni = rm["n_unique"].mean() if len(rm) else np.nan
        i_rec = im["n_records"].mean() if len(im) else np.nan
        i_uni = im["n_unique"].mean() if len(im) else np.nan
        i_orgs = im["total_orgs"].mean() if len(im) else np.nan
        seg_records[lab] = {
            "retail_daily_records": float(r_rec) if pd.notna(r_rec) else None,
            "retail_monthly_unique": float(r_uni) if pd.notna(r_uni) else None,
            "surv_monthly_records": float(i_rec) if pd.notna(i_rec) else None,
            "surv_monthly_unique": float(i_uni) if pd.notna(i_uni) else None,
            "surv_monthly_total_orgs": float(i_orgs) if pd.notna(i_orgs) else None,
        }
        print(
            f"{lab:<10} "
            f"{r_rec:>13.1f}   "
            f"{r_uni:>11.0f}   "
            f"{i_rec:>12.0f}   "
            f"{i_uni:>11.0f}   "
            f"{i_orgs:>11.0f}"
        )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_data_coverage_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "segments": seg_records,
            "retail_monthly": retail_monthly.assign(month=retail_monthly["month"].astype(str)).to_dict("records"),
            "inst_monthly": inst_monthly.assign(month=inst_monthly["month"].astype(str)).to_dict("records"),
        }, f, indent=2, ensure_ascii=False)
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
