"""
RIAD × DSR #30 BB-only 相关度分析

门槛 (DSR #30 stacking 规则): |corr| < 0.3 可做 2-leg ensemble.
双变量: Pearson (日收益) + Spearman (秩相关), 60d rolling.

数据:
    RIAD: research/factors/retail_inst_divergence/riad_ls_daily_returns.parquet
    DSR30-BB: research/event_driven/dsr30_mainboard_bb_oos.parquet

共同区间: 2023-10 ~ 2025-12 (受 RIAD stk_surv 样本约束)

输出:
    logs/riad_corr_dsr30_YYYYMMDD.json
    logs/riad_dsr30_combined_returns.parquet (若 corr < 0.3 则保留 50/50 叠加)
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
RIAD_PATH = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
DSR30_PATH = ROOT / "research" / "event_driven" / "dsr30_mainboard_bb_oos.parquet"


def main() -> None:
    riad = pd.read_parquet(RIAD_PATH)["net_ls"].rename("riad")
    dsr = pd.read_parquet(DSR30_PATH)["net_return"].rename("dsr30_bb")
    print(f"RIAD {len(riad)} 日 ({riad.index.min().date()} ~ {riad.index.max().date()})")
    print(f"DSR30 BB {len(dsr)} 日 ({dsr.index.min().date()} ~ {dsr.index.max().date()})")

    df = pd.concat([riad, dsr], axis=1).dropna()
    print(f"共同样本: {len(df)} 日 ({df.index.min().date()} ~ {df.index.max().date()})")

    pearson = df["riad"].corr(df["dsr30_bb"], method="pearson")
    spearman = df["riad"].corr(df["dsr30_bb"], method="spearman")
    print(f"\nPearson corr    : {pearson:+.4f}")
    print(f"Spearman corr   : {spearman:+.4f}")

    roll60 = df["riad"].rolling(60).corr(df["dsr30_bb"])
    print(f"\n60d rolling corr: mean={roll60.mean():+.3f}  median={roll60.median():+.3f}  "
          f"p10={roll60.quantile(0.1):+.3f}  p90={roll60.quantile(0.9):+.3f}")

    # 按分段
    for lab, mask in [
        ("IS 2023-10~2024-12", (df.index >= "2023-10-01") & (df.index <= "2024-12-31")),
        ("OOS 2025", df.index >= "2025-01-01"),
    ]:
        sub = df[mask]
        if len(sub) < 30:
            continue
        p = sub["riad"].corr(sub["dsr30_bb"], method="pearson")
        s = sub["riad"].corr(sub["dsr30_bb"], method="spearman")
        print(f"  [{lab}] n={len(sub)} Pearson={p:+.4f} Spearman={s:+.4f}")

    # 门槛判读
    threshold = 0.3
    passes = abs(pearson) < threshold
    print(f"\nStacking 门槛 |corr| < {threshold}: {'✅ PASS' if passes else '❌ FAIL'}")

    # 若过门槛, 生成 50/50 等波动合成 (Sharpe 额外验证)
    if passes:
        # 波动率归一化: 每个 strategy 缩放到年化 vol 10%
        riad_sc = riad / (riad.std(ddof=1) * np.sqrt(252)) * 0.10
        dsr_sc = dsr / (dsr.std(ddof=1) * np.sqrt(252)) * 0.10
        combined = 0.5 * riad_sc + 0.5 * dsr_sc
        combined = combined.dropna()
        sr_c = combined.mean() / combined.std(ddof=1) * np.sqrt(252) if combined.std(ddof=1) > 0 else np.nan
        sr_r = riad_sc.dropna().mean() / riad_sc.dropna().std(ddof=1) * np.sqrt(252)
        sr_d = dsr_sc.dropna().mean() / dsr_sc.dropna().std(ddof=1) * np.sqrt(252)
        print("\n=== 等波动 50/50 合成 (两者都先缩放到 ann vol 10%) ===")
        print(f"  RIAD (scaled)    : Sharpe {sr_r:+.3f}")
        print(f"  DSR30-BB (scaled): Sharpe {sr_d:+.3f}")
        print(f"  Combined 50/50   : Sharpe {sr_c:+.3f}")
        # 是否有 diversification gain
        mdd_c = ((1 + combined).cumprod() / (1 + combined).cumprod().cummax() - 1).min()
        print(f"  Combined MDD     : {mdd_c*100:+.2f}%")

        out_pq = ROOT / "logs" / "riad_dsr30_combined_returns.parquet"
        pd.DataFrame({"riad_scaled": riad_sc, "dsr30_scaled": dsr_sc, "combined_5050": combined}).to_parquet(out_pq)
        print(f"  保存合成 returns: {out_pq}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_corr_dsr30_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "pearson_corr": float(pearson),
                "spearman_corr": float(spearman),
                "threshold": threshold,
                "stacking_eligible": bool(passes),
                "n_common_days": int(len(df)),
                "rolling_60d": {
                    "mean": float(roll60.mean()),
                    "median": float(roll60.median()),
                    "p10": float(roll60.quantile(0.1)),
                    "p90": float(roll60.quantile(0.9)),
                },
            },
            f, indent=2, ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
