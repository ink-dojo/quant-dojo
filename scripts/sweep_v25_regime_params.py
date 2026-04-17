"""
v25 参数稳健性扫描（regime_gated_half_position_stop）

复用最新 v16 equity CSV，基于相同底层组合收益，扫描:
  threshold  ∈ {-0.05, -0.08, -0.10, -0.12, -0.15}
  ma_window  ∈ {60, 90, 120, 150, 180}

目的：确认 v25 (threshold=-0.10, ma=120) 是否 p-hacked，而是
参数网格上有相对平坦的 "好区域"。admission 真正该比较的是 baseline 与
替换 regime 参数后性能退化的程度。

输出 markdown 表格到 journal/v25_param_sweep_{date}.md。

运行: python scripts/sweep_v25_regime_params.py
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from utils.local_data_loader import load_price_wide
from utils.metrics import (
    annualized_return, sharpe_ratio, max_drawdown, win_rate,
)
from utils.stop_loss import (
    regime_gated_half_position_stop, hs300_bear_regime,
)

THRESHOLDS = [-0.05, -0.08, -0.10, -0.12, -0.15]
MA_WINDOWS = [60, 90, 120, 150, 180]
START = "2022-01-01"
END = "2025-12-31"


def latest_v16_equity() -> Path:
    files = sorted(Path("live/runs").glob("multi_factor_v16_*_equity.csv"))
    if not files:
        raise FileNotFoundError("未找到 multi_factor_v16_*_equity.csv")
    return files[-1]


def main():
    eq_path = latest_v16_equity()
    print(f"[1/3] 加载 v16 equity: {eq_path.name}")
    v16_df = pd.read_csv(eq_path, parse_dates=["date"]).set_index("date")
    base_ret = v16_df["portfolio_return"].astype(float)
    base_ret = base_ret.loc[START:END]
    # 去掉 warmup 零行
    first_nz = base_ret.ne(0).idxmax() if base_ret.ne(0).any() else base_ret.index[0]
    base_ret = base_ret.loc[first_nz:]
    print(f"  评估期: {base_ret.index[0].date()} ~ {base_ret.index[-1].date()}  n={len(base_ret)}")

    print("[2/3] 加载 HS300 399300")
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")
    if hs300.empty:
        raise RuntimeError("HS300 加载失败")
    hs300_close = hs300["399300"].dropna()

    print("[3/3] 扫描 5x5 网格…")
    # Baseline
    base_sr = sharpe_ratio(base_ret)
    base_mdd = max_drawdown(base_ret)
    base_ann = annualized_return(base_ret)
    print(f"\n  baseline (v16, 无止损): sharpe={base_sr:.3f}  ann={base_ann:.2%}  mdd={base_mdd:.2%}")

    rows = []
    for ma in MA_WINDOWS:
        regime = hs300_bear_regime(hs300_close, ma_window=ma, shift_days=1)
        regime = regime.reindex(base_ret.index).fillna(False).astype(bool)
        bear_pct = float(regime.mean())
        for thr in THRESHOLDS:
            adj = regime_gated_half_position_stop(base_ret, regime, threshold=thr)
            row = {
                "threshold": thr,
                "ma_window": ma,
                "bear_pct": bear_pct,
                "sharpe": float(sharpe_ratio(adj)),
                "ann_return": float(annualized_return(adj)),
                "max_drawdown": float(max_drawdown(adj)),
                "win_rate": float(win_rate(adj)),
                "sharpe_delta": float(sharpe_ratio(adj) - base_sr),
                "mdd_improve": float(max_drawdown(adj) - base_mdd),
            }
            rows.append(row)
    df = pd.DataFrame(rows)

    # ── Markdown 输出 ─────────────────────────────────────────────
    lines = []
    lines.append(f"# v25 参数稳健性扫描 — {date.today()}\n")
    lines.append("扫描 regime_gated_half_position_stop 参数空间，基于同一 v16 底层组合收益。")
    lines.append("")
    lines.append(f"**Baseline (v16)**: sharpe={base_sr:.3f}, ann={base_ann:.2%}, MDD={base_mdd:.2%}")
    lines.append("")
    lines.append("## Sharpe 网格")
    lines.append("")
    pivot_sr = df.pivot(index="threshold", columns="ma_window", values="sharpe")
    lines.append(pivot_sr.to_markdown(floatfmt=".3f"))
    lines.append("")
    lines.append("## MDD 网格")
    lines.append("")
    pivot_mdd = df.pivot(index="threshold", columns="ma_window", values="max_drawdown")
    lines.append(pivot_mdd.to_markdown(floatfmt=".2%"))
    lines.append("")
    lines.append("## 年化 网格")
    lines.append("")
    pivot_ann = df.pivot(index="threshold", columns="ma_window", values="ann_return")
    lines.append(pivot_ann.to_markdown(floatfmt=".2%"))
    lines.append("")

    # 过 admission MDD 的配置
    passed = df[df["max_drawdown"] > -0.30].sort_values("sharpe", ascending=False)
    lines.append("## 过 MDD admission（>-30%）的参数配置")
    lines.append("")
    if passed.empty:
        lines.append("**无** — 所有 (threshold, ma_window) 组合 MDD 都突破 -30% 红线。")
    else:
        keep = passed[["threshold", "ma_window", "sharpe", "ann_return", "max_drawdown", "bear_pct"]]
        lines.append(keep.to_markdown(index=False, floatfmt=".3f"))
    lines.append("")

    # 同时 sharpe>=0.76 和 MDD>-30% 的稳健区
    strong = df[(df["max_drawdown"] > -0.30) & (df["sharpe"] >= 0.76)]
    lines.append(f"## 稳健区（MDD>-30% 且 sharpe≥0.76）: {len(strong)} 组")
    lines.append("")
    if not strong.empty:
        lines.append(strong[["threshold", "ma_window", "sharpe", "ann_return", "max_drawdown"]].to_markdown(index=False, floatfmt=".3f"))
    else:
        lines.append("**无稳健区** — v25 选中的 (threshold=-0.10, ma=120) 可能是孤立点。")
    lines.append("")

    # 导出
    out_md = Path(f"journal/v25_param_sweep_{date.today().strftime('%Y%m%d')}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_csv = Path(f"journal/v25_param_sweep_{date.today().strftime('%Y%m%d')}.csv")
    df.to_csv(out_csv, index=False)
    print(f"\n✓ 写出 {out_md}")
    print(f"✓ 写出 {out_csv}")

    # 终端摘要
    print("\n=== Sharpe 网格 ===")
    print(pivot_sr.to_string(float_format=lambda x: f"{x:.3f}"))
    print("\n=== MDD 网格 ===")
    print(pivot_mdd.to_string(float_format=lambda x: f"{x:.2%}"))
    print(f"\n过 MDD 门 (>-30%) 的组合: {len(passed)} / {len(df)}")
    print(f"稳健区（MDD>-30% & sharpe>=0.76）: {len(strong)} / {len(df)}")


if __name__ == "__main__":
    main()
