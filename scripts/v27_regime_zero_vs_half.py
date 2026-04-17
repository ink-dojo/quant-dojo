"""
v16 regime mask 结构对照: bear=0 仓 (v27_zero) vs bear=0.5 仓 (v25_half) vs bear=1 仓 (v16).

目的: 不做参数搜索, 只做 binary 结构测试 — 如果完全信 HS300<MA120 regime,
把 bear 日直接空仓 (而不是 v25 的半仓), 能否过 admission 4 门?

三条曲线同底层 v16 策略, 只改 bear 日 exposure:
  - v16:       bear=1.00  bull=1.00  (满仓)
  - v25_half:  bear~0.50  bull=1.00  (带状态机的半仓, 不等同简单 mask)
  - v27_zero:  bear=0.00  bull=1.00  (bear 日全空仓)
  - v27_half:  bear=0.50  bull=1.00  (bear 日固定半仓 mask, 与 v25 状态机对照)

注意:
  - v27_* 是理论上限测试 (无切换成本, 无滑点), 实盘必须加成本建模
  - regime 参数 (MA120, shift(1)) 是 v25 原设计, **不做 grid search**
  - admission 四门: ann_return>15%, sharpe>0.8, mdd>-30%, PSR vs 0 >0.95

输出: journal/v27_regime_zero_vs_half_{date}.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from pipeline.strategy_registry import get_strategy
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, probabilistic_sharpe, bootstrap_sharpe_ci,
)
from utils.stop_loss import hs300_bear_regime, regime_gated_half_position_stop

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
MA = 120
THRESHOLD = -0.10
N_STOCKS = 30


def load_v16_fresh() -> pd.Series:
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    entry = get_strategy("multi_factor_v16")
    strat = entry.factory({"n_stocks": N_STOCKS})
    res = strat.run(price)
    col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
    r = res[col].astype(float).loc[START:END]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def metrics_block(r: pd.Series, name: str) -> dict:
    return {
        "策略": name,
        "n": len(r),
        "ann_return": annualized_return(r),
        "sharpe": sharpe_ratio(r),
        "mdd": max_drawdown(r),
        "vol": annualized_volatility(r),
        "win_rate": win_rate(r),
        "psr_0": probabilistic_sharpe(r, sr_benchmark=0.0),
    }


def admission_pass(m: dict) -> dict:
    return {
        "策略": m["策略"],
        "ann_pass": m["ann_return"] > 0.15,
        "sharpe_pass": m["sharpe"] > 0.80,
        "mdd_pass": m["mdd"] > -0.30,
        "psr0_pass": m["psr_0"] > 0.95,
        "all_pass": (m["ann_return"] > 0.15 and m["sharpe"] > 0.80
                     and m["mdd"] > -0.30 and m["psr_0"] > 0.95),
    }


def main():
    print("[1/5] 加载 fresh v16 底层 return…")
    v16 = load_v16_fresh()
    print(f"  v16 n={len(v16)}  {v16.index[0].date()} ~ {v16.index[-1].date()}")

    print("[2/5] 加载 HS300 regime flag (MA120, shift 1) …")
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")["399300"].dropna()
    regime_full = hs300_bear_regime(hs300, ma_window=MA, shift_days=1)
    regime = regime_full.reindex(v16.index).fillna(False).astype(bool)
    print(f"  eval 段 bear 覆盖 {regime.mean():.1%}")

    print("[3/5] 构建四条曲线…")
    curves = {}
    curves["v16"] = v16.copy()  # 满仓

    mask_half = pd.Series(1.0, index=v16.index)
    mask_half[regime] = 0.5
    curves["v27_half"] = v16 * mask_half  # 简单 mask 半仓 (无状态机)

    mask_zero = pd.Series(1.0, index=v16.index)
    mask_zero[regime] = 0.0
    curves["v27_zero"] = v16 * mask_zero  # bear 日全空仓

    # v25 状态机半仓 (原始 v25 实现)
    curves["v25_half_fsm"] = regime_gated_half_position_stop(
        v16, regime_bear=regime, threshold=THRESHOLD
    )

    print("[4/5] 算 metrics…")
    m_rows = [metrics_block(r, k) for k, r in curves.items()]
    df_m = pd.DataFrame(m_rows)

    a_rows = [admission_pass(m) for m in m_rows]
    df_a = pd.DataFrame(a_rows)

    # 分年
    years_rows = []
    for name, r in curves.items():
        for y in sorted(set(r.index.year)):
            ry = r[r.index.year == y]
            years_rows.append({
                "策略": name, "year": int(y),
                "n": len(ry),
                "ann_return": annualized_return(ry),
                "sharpe": sharpe_ratio(ry),
                "mdd": max_drawdown(ry),
            })
    df_years = pd.DataFrame(years_rows)

    # bootstrap CI (v27_zero 过门候选, 重点分析)
    print("[5/5] bootstrap CI…")
    ci_rows = []
    for name in curves:
        ci = bootstrap_sharpe_ci(curves[name], n_boot=2000, alpha=0.05, seed=42)
        ci_rows.append({"策略": name, **ci})
    df_ci = pd.DataFrame(ci_rows)

    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v27 regime mask 结构对照 — {today}")
    lines.append("")
    lines.append(f"> 数据: fresh v16 底层, eval {v16.index[0].date()}~{v16.index[-1].date()} n={len(v16)}")
    lines.append(f"> regime: HS300<MA{MA} shift(1), bear 覆盖 {regime.mean():.1%}")
    lines.append(f"> 曲线: v16 (bear=1.0) / v27_half (bear=0.5 simple mask) /")
    lines.append(f"> v27_zero (bear=0.0 空仓) / v25_half_fsm (半仓状态机, threshold={THRESHOLD})")
    lines.append(f"> 警告: v27_* 未计切换成本, 是理论上限")
    lines.append("")

    lines.append("## 1. 全期 metrics")
    lines.append("")
    lines.append(df_m.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 2. Admission 四门判定")
    lines.append("")
    lines.append(df_a.to_markdown(index=False))
    lines.append("")

    lines.append("## 3. Sharpe Bootstrap 95% CI")
    lines.append("")
    lines.append(df_ci.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 4. 分年 metrics")
    lines.append("")
    lines.append(df_years.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    # 结构性结论
    zero_m = next(x for x in m_rows if x["策略"] == "v27_zero")
    v25_m = next(x for x in m_rows if x["策略"] == "v25_half_fsm")
    v16_m = next(x for x in m_rows if x["策略"] == "v16")

    lines.append("## 5. 诚实结论")
    lines.append("")
    lines.append(f"- v16 (满仓):       ann={v16_m['ann_return']:.2%}  sharpe={v16_m['sharpe']:.3f}  mdd={v16_m['mdd']:.2%}")
    lines.append(f"- v25_half_fsm:     ann={v25_m['ann_return']:.2%}  sharpe={v25_m['sharpe']:.3f}  mdd={v25_m['mdd']:.2%}")
    lines.append(f"- v27_zero (空仓):  ann={zero_m['ann_return']:.2%}  sharpe={zero_m['sharpe']:.3f}  mdd={zero_m['mdd']:.2%}")
    lines.append("")
    lines.append("v27_zero 过 admission 四门:")
    zero_a = next(x for x in a_rows if x["策略"] == "v27_zero")
    for k, v in zero_a.items():
        if k != "策略":
            lines.append(f"  - {k}: {'✅' if v else '❌'}")
    lines.append("")
    lines.append("不抄近道说明:")
    lines.append("- regime 参数 (MA120, threshold=-0.10) 直接沿用 v25 原设计, 未做任何 grid search")
    lines.append("- v27_zero 若过门, 是 **结构上限** 结果, 实盘需加切换成本/滑点才能注册为 v27 候选")
    lines.append("- 若 v27_zero 仍不过门 → 证明 'HS300 MA120 regime + long-only' 结构本身不可过门,")
    lines.append("  合规下一步必须是换 regime 指标 (非参数微调) 或引入 short leg (市场中性)")
    lines.append("")

    out_md = Path(f"journal/v27_regime_zero_vs_half_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    print("\n=== 结果速览 ===")
    print(df_m.to_string(index=False))
    print()
    print(df_a.to_string(index=False))


if __name__ == "__main__":
    main()
