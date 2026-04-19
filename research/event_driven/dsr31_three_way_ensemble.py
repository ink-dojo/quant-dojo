"""DSR #31 — 3-way ensemble: BB + PV + Insider (主板 rescaled to gross 0.8).

Pre-registration: research/event_driven/DSR31_SPEC.md (commit-locked).

### 执行顺序
1. Load BB & PV 主板 rescaled OOS parquets (DSR #30 产物, 不重算)
2. Build insider_purchase_strategy.py 主板 rescaled (new)
3. 3-way equal-weight ensemble
4. Gate 判定 + 诊断

### 红线
- 5/5 PASS → paper-trade candidate #2
- 4/5 仍 miss CI_low → option A (modify gate for paper-trade)
- ≤ 3/5 → insider 拖累, 不 promote

### DSR: 31
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from research.event_driven.insider_purchase_strategy import (
    load_events as load_insider,
    build_long_only_weights as build_insider_raw,
    TXN_ROUND_TRIP as INSIDER_COST,
    UNIT_POS_WEIGHT as INSIDER_UNIT_BASE,
)
from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return,
    bootstrap_sharpe_ci,
    max_drawdown,
    probabilistic_sharpe,
    sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)

START, END = "2018-01-01", "2025-12-31"
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD_SYMBOLS = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())

TARGET_GROSS = 0.8


def filter_mainboard(ev: pd.DataFrame) -> pd.DataFrame:
    return ev[ev["symbol"].isin(MAIN_BOARD_SYMBOLS)].copy()


def run_insider_alpha() -> tuple[pd.Series, float]:
    """Insider purchase 主板 rescaled — 保留 formula-driven UNIT rescale."""
    ev = load_insider(END)
    logger.info(f"insider raw events: {len(ev)}")
    ev_mb = filter_mainboard(ev)
    logger.info(f"insider 主板 events: {len(ev_mb)}")

    universe = sorted(ev_mb["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=START, end=END)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    # Pass 1: measure capped mean gross at base UNIT
    W_base = build_insider_raw(ev_mb, rets.index, unit_weight=INSIDER_UNIT_BASE)
    W_base = W_base.reindex(columns=prices.columns).fillna(0)
    W_base_capped = apply_gross_cap(W_base, cap=1.0)
    mean_gross_base = W_base_capped.abs().sum(axis=1).loc[START:END].mean()
    scale = TARGET_GROSS / max(mean_gross_base, 1e-6)
    print(f"\ninsider base mean_gross={mean_gross_base:.3f}  scale={scale:.3f}")

    # Pass 2: apply rescale
    W = build_insider_raw(ev_mb, rets.index, unit_weight=INSIDER_UNIT_BASE * scale)
    W = W.reindex(columns=prices.columns).fillna(0)
    W_capped = apply_gross_cap(W, cap=1.0)
    w_exec = W_capped.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (INSIDER_COST / 2)
    net = (daily_gross - daily_cost).loc[START:END].dropna()
    gross_final = W_capped.abs().sum(axis=1).loc[START:END].mean()
    print(f"insider rescaled mean_gross={gross_final:.3f}")
    return net, scale


def gate_report(name: str, ret: pd.Series) -> dict:
    ann = annualized_return(ret)
    sr = sharpe_ratio(ret)
    mdd = max_drawdown(ret)
    psr = probabilistic_sharpe(ret, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(ret, n_boot=2000)
    gate = {
        "ann>15%": ann > 0.15,
        "sharpe>0.8": sr > 0.8,
        "mdd>-30%": mdd > -0.30,
        "PSR>0.95": psr > 0.95,
        "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    n_pass = sum(gate.values())
    print(f"\n=== {name} ===")
    print(f"  ann={ann:+.2%}  Sharpe={sr:.2f}  MDD={mdd:.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    return dict(n_pass=n_pass, ann=ann, sharpe=sr, mdd=mdd, psr=psr,
                ci_low=boot["ci_low"], ci_high=boot["ci_high"])


def yearly_breakdown(name: str, ret: pd.Series) -> None:
    yr = ret.groupby(ret.index.year).agg(
        ann=lambda s: annualized_return(s),
        sharpe=lambda s: sharpe_ratio(s),
    )
    print(f"\n{name} — yearly:")
    print(yr.to_string())


def main():
    logging.basicConfig(level=logging.WARNING)
    print("=" * 72)
    print("  DSR #31 — 3-way ensemble (BB + PV + Insider, 主板 rescaled)")
    print("=" * 72)

    # Load existing DSR #30 alphas
    r_bb = pd.read_parquet(
        "research/event_driven/dsr30_mainboard_bb_oos.parquet"
    )["net_return"]
    r_pv = pd.read_parquet(
        "research/event_driven/dsr30_mainboard_pv_oos.parquet"
    )["net_return"]
    print(f"\nLoaded BB: {r_bb.shape}, PV: {r_pv.shape}")

    # Build insider alpha
    r_ins, ins_scale = run_insider_alpha()
    print(f"insider alpha: {r_ins.shape}, scale={ins_scale:.2f}")

    # Individual gates
    res_bb = gate_report("BB 主板 rescaled", r_bb)
    res_pv = gate_report("PV 主板 rescaled", r_pv)
    res_ins = gate_report("Insider 主板 rescaled", r_ins)

    # Align and ensemble
    df = pd.concat(
        [r_bb.rename("bb"), r_pv.rename("pv"), r_ins.rename("ins")],
        axis=1
    ).dropna()
    print(f"\naligned shape: {df.shape}")

    # Correlations
    print("\n=== pairwise correlations ===")
    print(df.corr().round(3).to_string())

    # 3-way ensemble
    ens = (df["bb"] + df["pv"] + df["ins"]) / 3
    res_ens = gate_report("DSR #31 — 3-way ensemble 主板 rescaled", ens)

    yearly_breakdown("3-way ensemble", ens)

    # Save
    ens.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr31_threeway_ensemble_oos.parquet"
    )
    r_ins.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr31_insider_mainboard_oos.parquet"
    )

    # Summary
    print("\n" + "=" * 72)
    print("  DSR #31 Summary")
    print("=" * 72)
    print(f"  BB-only    {res_bb['n_pass']}/5  ann={res_bb['ann']:+.2%}  SR={res_bb['sharpe']:.2f}  CI_low={res_bb['ci_low']:.2f}")
    print(f"  PV-only    {res_pv['n_pass']}/5  ann={res_pv['ann']:+.2%}  SR={res_pv['sharpe']:.2f}  CI_low={res_pv['ci_low']:.2f}")
    print(f"  Insider    {res_ins['n_pass']}/5  ann={res_ins['ann']:+.2%}  SR={res_ins['sharpe']:.2f}  CI_low={res_ins['ci_low']:.2f}")
    print(f"  3-way Ens  {res_ens['n_pass']}/5  ann={res_ens['ann']:+.2%}  SR={res_ens['sharpe']:.2f}  CI_low={res_ens['ci_low']:.2f}")

    if res_ens["n_pass"] >= 5:
        print("\n>>> FULL PASS — paper-trade candidate #2 <<<")
    elif res_ens["n_pass"] >= 4 and res_ens["ci_low"] < 0.5 and res_ens["ci_low"] > res_bb["ci_low"]:
        print("\n>>> 4/5 PASS 但 CI_low 仍 fail. 改善 vs BB-only. Option A 候选. <<<")
    elif res_ens["n_pass"] > res_bb["n_pass"]:
        print("\n>>> partial improvement over BB-only <<<")
    else:
        print("\n>>> insider alpha 拖累 ensemble, 不 promote <<<")


if __name__ == "__main__":
    main()
