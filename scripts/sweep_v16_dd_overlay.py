"""
在 v16 equity 曲线上扫描回撤控制叠加层参数。

候选叠加：
  1. half_position_stop(threshold)       — 累计回撤触发 50% 降仓
  2. adaptive_half_position_stop(...)    — 同上但阈值随波动率缩放

目标: max_dd 降到 -30% 以内、sharpe 尽量保留。

运行: python scripts/sweep_v16_dd_overlay.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate,
)
from utils.stop_loss import half_position_stop, adaptive_half_position_stop

V16_EQUITY = Path(__file__).parent.parent / "live" / "runs" / "multi_factor_v16_20260414_36127e73_equity.csv"


def load_v16() -> pd.Series:
    df = pd.read_csv(V16_EQUITY, parse_dates=["date"]).set_index("date")
    r = df["portfolio_return"].astype(float)
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def report(name: str, r: pd.Series) -> dict:
    ann = annualized_return(r)
    vol = annualized_volatility(r)
    sr = sharpe_ratio(r)
    mdd = max_drawdown(r)
    wr = win_rate(r)
    gate_ann = ann >= 0.15
    gate_sr = sr >= 0.8
    gate_mdd = mdd > -0.30
    gate_all = gate_ann and gate_sr and gate_mdd
    row = {
        "overlay": name,
        "ann_return": float(ann),
        "sharpe": float(sr),
        "vol": float(vol),
        "max_dd": float(mdd),
        "win_rate": float(wr),
        "gate_ann": gate_ann,
        "gate_sr": gate_sr,
        "gate_mdd": gate_mdd,
        "gate_all": gate_all,
    }
    print(f"  {name:50s}  sr={sr:+.3f}  ann={ann:+.2%}  mdd={mdd:+.2%}  "
          f"gate={'✓' if gate_all else '✗'}  (ann={'✓' if gate_ann else '✗'}/"
          f"sr={'✓' if gate_sr else '✗'}/mdd={'✓' if gate_mdd else '✗'})")
    return row


def main():
    r = load_v16()
    print(f"v16 equity: {r.index[0].date()} ~ {r.index[-1].date()}, n={len(r)}")
    print()

    rows = []
    print("=" * 80)
    print("基线与 half_position_stop 扫描")
    print("=" * 80)
    rows.append(report("baseline_v16", r))
    for thr in [-0.05, -0.08, -0.10, -0.12, -0.15, -0.20, -0.25]:
        r_adj = half_position_stop(r, threshold=thr)
        rows.append(report(f"half_stop(thr={thr:+.2f})", r_adj))

    print()
    print("=" * 80)
    print("adaptive_half_position_stop 扫描 (baseline -0.10, ref_vol ∈ [0.15,0.25])")
    print("=" * 80)
    for ref_vol in [0.15, 0.20, 0.25, 0.30]:
        for baseline in [-0.08, -0.10, -0.12]:
            r_adj = adaptive_half_position_stop(
                r, baseline_threshold=baseline, vol_window=60, ref_vol=ref_vol,
                min_scale=0.5, max_scale=2.0,
            )
            rows.append(report(
                f"adaptive(base={baseline:+.2f},σref={ref_vol:.2f})", r_adj
            ))

    df = pd.DataFrame(rows)
    df_sorted = df.sort_values(["gate_all", "sharpe"], ascending=[False, False])
    print()
    print("=" * 80)
    print("总排名（按 gate 通过 + Sharpe 降序）")
    print("=" * 80)
    print(df_sorted[["overlay", "sharpe", "ann_return", "max_dd", "gate_all"]].to_string(index=False))

    # 打印通过全 gate 的参数组（如果有）
    passes = df_sorted[df_sorted["gate_all"]]
    print()
    print("=" * 80)
    if len(passes):
        print(f"✓ 通过 admission gate 的叠加方案: {len(passes)} 个")
        print(passes[["overlay", "sharpe", "ann_return", "max_dd"]].to_string(index=False))
    else:
        print("✗ 无叠加方案同时满足 ann≥15% + sr≥0.8 + mdd>-30%")
        # 找满足 mdd > -30% 且 sharpe 最高的
        mdd_ok = df_sorted[df_sorted["gate_mdd"]]
        if len(mdd_ok):
            best = mdd_ok.iloc[0]
            print(f"\n最佳满足 mdd>-30% 的方案: {best['overlay']}")
            print(f"  sharpe={best['sharpe']:+.3f}  ann={best['ann_return']:+.2%}  mdd={best['max_dd']:+.2%}")
        else:
            print("\n所有叠加方案都无法把 mdd 压到 -30% 以内")
    print("=" * 80)

    # 保存结果
    out_path = Path(__file__).parent.parent / "journal" / "v16_dd_overlay_sweep.csv"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"\n写出 {out_path}")


if __name__ == "__main__":
    main()
