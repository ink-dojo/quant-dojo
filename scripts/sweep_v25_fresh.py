"""
v25 参数稳健性扫描 (fresh v16 base) —

sweep_v25_regime_params.py 复用 2026-04-14 的 v16 equity CSV，与 v25 实际
跑的 fresh v16 输出可能存在 universe 漂移导致的数值差异。本脚本改为先
跑一次 fresh v16 backtest，把同一份 base_ret 喂给所有 (threshold, ma) 组合，
保证横向对比严格 apples-to-apples。

输出 journal/v25_param_sweep_fresh_{date}.md 与 .csv。

运行: python scripts/sweep_v25_fresh.py
"""
from __future__ import annotations

import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd

from pipeline.strategy_registry import get_strategy
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, sharpe_ratio, max_drawdown, win_rate,
)
from utils.stop_loss import (
    regime_gated_half_position_stop, hs300_bear_regime,
)

THRESHOLDS = [-0.05, -0.06, -0.08, -0.10, -0.12, -0.15]
MA_WINDOWS = [60, 90, 120, 150, 180]
START = "2022-01-01"
END = "2025-12-31"
WARMUP_START = "2019-01-01"
N_STOCKS = 30


def main():
    t0 = time.time()
    print(f"[1/4] 加载 price 宽表 {WARMUP_START} ~ {END} …")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]
    print(f"  股票: {len(valid)} | 交易日: {len(price)}")

    print(f"[2/4] 跑一次 fresh v16 backtest 作为基底…")
    entry = get_strategy("multi_factor_v16")
    strategy = entry.factory({"n_stocks": N_STOCKS})
    v16_result = strategy.run(price)
    if "portfolio_return" in v16_result.columns:
        base_ret_full = v16_result["portfolio_return"].astype(float)
    elif "returns" in v16_result.columns:
        base_ret_full = v16_result["returns"].astype(float)
    else:
        raise RuntimeError(f"v16 未产出收益列: {v16_result.columns}")

    base_ret = base_ret_full.loc[START:END]
    first_nz = base_ret.ne(0).idxmax() if base_ret.ne(0).any() else base_ret.index[0]
    base_ret = base_ret.loc[first_nz:]
    base_sr = sharpe_ratio(base_ret)
    base_mdd = max_drawdown(base_ret)
    base_ann = annualized_return(base_ret)
    print(f"  fresh v16: n={len(base_ret)}  sharpe={base_sr:.3f}  ann={base_ann:.2%}  mdd={base_mdd:.2%}")

    print("[3/4] 加载 HS300 399300")
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")
    hs300_close = hs300["399300"].dropna()

    print(f"[4/4] 扫描 {len(THRESHOLDS)}x{len(MA_WINDOWS)}={len(THRESHOLDS)*len(MA_WINDOWS)} 组合…")
    rows = []
    for ma in MA_WINDOWS:
        regime = hs300_bear_regime(hs300_close, ma_window=ma, shift_days=1)
        regime = regime.reindex(base_ret.index).fillna(False).astype(bool)
        bear_pct = float(regime.mean())
        for thr in THRESHOLDS:
            adj = regime_gated_half_position_stop(base_ret, regime, threshold=thr)
            rows.append({
                "threshold": thr,
                "ma_window": ma,
                "bear_pct": bear_pct,
                "sharpe": float(sharpe_ratio(adj)),
                "ann_return": float(annualized_return(adj)),
                "max_drawdown": float(max_drawdown(adj)),
                "win_rate": float(win_rate(adj)),
                "sharpe_delta": float(sharpe_ratio(adj) - base_sr),
                "mdd_improve": float(max_drawdown(adj) - base_mdd),
            })
    df = pd.DataFrame(rows)

    # markdown
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v25 参数稳健性扫描（fresh v16 基底）— {today}\n")
    lines.append(f"**Baseline (fresh v16)**: sharpe={base_sr:.3f}, ann={base_ann:.2%}, MDD={base_mdd:.2%}, n={len(base_ret)}")
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

    passed = df[df["max_drawdown"] > -0.30].sort_values("sharpe", ascending=False)
    lines.append(f"## 过 admission MDD (>-30%) 的组合: {len(passed)}/{len(df)}")
    lines.append("")
    if not passed.empty:
        lines.append(passed[["threshold", "ma_window", "sharpe", "ann_return", "max_drawdown", "bear_pct"]].head(15).to_markdown(index=False, floatfmt=".3f"))
    lines.append("")

    all_gate = df[(df["max_drawdown"] > -0.30) & (df["sharpe"] >= 0.8) & (df["ann_return"] >= 0.15)]
    lines.append(f"## 过全部 admission (ann≥15%, sharpe≥0.8, MDD>-30%): {len(all_gate)}/{len(df)}")
    lines.append("")
    if not all_gate.empty:
        lines.append(all_gate[["threshold", "ma_window", "sharpe", "ann_return", "max_drawdown"]].sort_values("sharpe", ascending=False).to_markdown(index=False, floatfmt=".3f"))
    else:
        lines.append("**无组合全部过关**")
    lines.append("")

    out_md = Path(f"journal/v25_param_sweep_fresh_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    out_csv = Path(f"journal/v25_param_sweep_fresh_{today}.csv")
    df.to_csv(out_csv, index=False)

    print("\n=== Sharpe 网格 ===")
    print(pivot_sr.to_string(float_format=lambda x: f"{x:.3f}"))
    print("\n=== MDD 网格 ===")
    print(pivot_mdd.to_string(float_format=lambda x: f"{x:.2%}"))
    print(f"\n过 MDD 门: {len(passed)}/{len(df)}")
    print(f"过全部 admission: {len(all_gate)}/{len(df)}")
    print(f"\n✓ 写出 {out_md}  {out_csv}")
    print(f"\n总耗时: {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
