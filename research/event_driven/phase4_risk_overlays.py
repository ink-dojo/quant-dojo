"""Phase 4 — risk overlay 4 hypothesis 执行 (DSR #25/26/27/28).

Pre-registration spec locked in research/event_driven/PHASE4_SPEC.md (commit 45823b5).

### 执行顺序
1. DSR #25: vol-managed ensemble (Moreira-Muir)
2. DSR #26: CSI300 regime filter (Faber)
3. DSR #27: UNIT recalibration → capped @ 1.0
4. DSR #28: combined stack (vol × regime × recalibrated base)

### 输出
每个 hypothesis 落 parquet, side-by-side 对比 gate pass/fail.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from research.event_driven.buyback_long_only_strategy import (
    load_events as load_bb,
    build_long_only_weights as build_bb_raw,
    TXN_ROUND_TRIP as BB_COST,
)
from research.event_driven.earnings_preview_strategy import (
    load_events as load_pv,
    build_long_only_weights as build_pv_raw,
    TXN_ROUND_TRIP as PV_COST,
)
from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return,
    bootstrap_sharpe_ci,
    max_drawdown,
    probabilistic_sharpe,
    sharpe_ratio,
)
from utils.risk_overlay import (
    apply_gross_cap,
    vol_target_scale,
    regime_filter_scale,
)

logger = logging.getLogger(__name__)

START, END = "2018-01-01", "2025-12-31"
CSI300_PATH = Path("data/raw/indices/sh000300.parquet")


def gate_report(name: str, ret: pd.Series, dsr_id: int) -> dict:
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
    print(f"\n=== DSR #{dsr_id} — {name} ===")
    print(f"  ann={ann:+.2%}  Sharpe={sr:.2f}  MDD={mdd:.2%}  PSR={psr:.3f}  CI_low={boot['ci_low']:.2f}")
    print(f"  {n_pass}/5 gates:")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    return dict(name=name, dsr=dsr_id, ann=ann, sharpe=sr, mdd=mdd, psr=psr, ci_low=boot["ci_low"], n_pass=n_pass, returns=ret)


def load_csi300() -> pd.Series:
    df = pd.read_parquet(CSI300_PATH)
    return df["close"]


def build_capped_alpha(
    events: pd.DataFrame,
    prices: pd.DataFrame,
    build_fn,
    cost_round_trip: float,
    unit_scale: float = 1.0,
    cap: float = 1.0,
) -> pd.Series:
    """构建 alpha 净收益 — 可选 UNIT rescale, 再 apply_gross_cap(cap)."""
    import inspect
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)
    # build_fn returns W already; need to access UNIT via kwargs
    sig = inspect.signature(build_fn)
    if "unit_weight" in sig.parameters:
        # default UNIT of the module × scale
        from research.event_driven.buyback_long_only_strategy import UNIT_POS_WEIGHT as BB_UNIT
        from research.event_driven.earnings_preview_strategy import UNIT_POS_WEIGHT as PV_UNIT
        default_unit = BB_UNIT if build_fn is build_bb_raw else PV_UNIT
        W = build_fn(events, rets.index, unit_weight=default_unit * unit_scale)
    else:
        W = build_fn(events, rets.index)
    W = W.reindex(columns=prices.columns).fillna(0)
    W_capped = apply_gross_cap(W, cap=cap)
    w_exec = W_capped.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (cost_round_trip / 2)
    net = (daily_gross - daily_cost).loc[START:END].dropna()
    return net, W_capped.abs().sum(axis=1).loc[START:END]


def main():
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

    # ================================================================
    # Baseline: reuse capped ensemble from phase3_postmortem
    # ================================================================
    baseline = pd.read_parquet("research/event_driven/ensemble_v1_capped_oos_returns.parquet")["net_return"]
    csi300_close = load_csi300().loc[START:END]

    print("=" * 70)
    print("  Phase 4 — risk overlay on capped ensemble (DSR #25/26/27/28)")
    print("=" * 70)

    results = []

    gate_report("baseline (capped ensemble #24 recap)", baseline, 24)

    # ================================================================
    # DSR #25 — Vol-managed ensemble (Moreira-Muir 2017)
    # ================================================================
    vol_scale = vol_target_scale(baseline, target_vol=0.12, window=60, cap=1.5, floor=0.0)
    ret_25 = (baseline * vol_scale).dropna()
    print(f"\n[Phase 4.1] vol_target: mean_scale={vol_scale.mean():.3f}  max={vol_scale.max():.3f}  min={vol_scale.min():.3f}")
    r25 = gate_report("Vol-managed (target 12%, cap 1.5x)", ret_25, 25)
    results.append(r25)
    ret_25.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr25_vol_managed_oos.parquet"
    )

    # ================================================================
    # DSR #26 — CSI300 regime filter (Faber 2007)
    # ================================================================
    regime_scale = regime_filter_scale(csi300_close, sma_window=200, in_scale=1.0, out_scale=0.3)
    regime_scale_aligned = regime_scale.reindex(baseline.index).ffill().fillna(1.0)
    ret_26 = (baseline * regime_scale_aligned).dropna()
    days_off = (regime_scale_aligned < 1.0).sum()
    print(f"\n[Phase 4.2] regime filter: days OFF={days_off} ({days_off/len(regime_scale_aligned):.1%}), mean scale={regime_scale_aligned.mean():.3f}")
    r26 = gate_report("CSI300 200d SMA regime filter", ret_26, 26)
    results.append(r26)
    ret_26.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr26_regime_oos.parquet"
    )

    # ================================================================
    # DSR #27 — UNIT recalibration targeting mean gross ~1.0
    # ================================================================
    # First compute baseline capped mean gross (ex-post from previous run)
    # For formula: scale_factor = 1.0 / mean_capped_gross (baseline)
    # We know from post-mortem: buyback capped mean_gross = 0.542, preview = 0.462
    BB_MEAN_CAPPED = 0.542
    PV_MEAN_CAPPED = 0.462
    BB_SCALE = 1.0 / BB_MEAN_CAPPED  # ≈ 1.85
    PV_SCALE = 1.0 / PV_MEAN_CAPPED  # ≈ 2.16
    print(f"\n[Phase 4.3] UNIT recalibration: bb_scale={BB_SCALE:.3f}  pv_scale={PV_SCALE:.3f}")

    ev_bb = load_bb(END)
    uni_bb = sorted(ev_bb["symbol"].dropna().unique().tolist())
    prices_bb = load_adj_price_wide(uni_bb, start=START, end=END)
    ret_bb_recal, gross_bb = build_capped_alpha(ev_bb, prices_bb, build_bb_raw, BB_COST, unit_scale=BB_SCALE, cap=1.0)

    ev_pv = load_pv(END)
    uni_pv = sorted(ev_pv["symbol"].dropna().unique().tolist())
    prices_pv = load_adj_price_wide(uni_pv, start=START, end=END)
    ret_pv_recal, gross_pv = build_capped_alpha(ev_pv, prices_pv, build_pv_raw, PV_COST, unit_scale=PV_SCALE, cap=1.0)

    print(f"  recalibrated mean gross: bb={gross_bb.mean():.3f}  pv={gross_pv.mean():.3f}")
    df = pd.concat([ret_bb_recal.rename("bb"), ret_pv_recal.rename("pv")], axis=1).dropna()
    ret_27 = 0.5 * df["bb"] + 0.5 * df["pv"]
    r27 = gate_report("UNIT recal ensemble (mean gross ~1.0)", ret_27, 27)
    results.append(r27)
    ret_27.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr27_unit_recal_oos.parquet"
    )

    # ================================================================
    # DSR #28 — Combined stack: recalibrated × vol_target × regime
    # ================================================================
    vol_scale_27 = vol_target_scale(ret_27, target_vol=0.12, window=60, cap=1.5, floor=0.0)
    regime_scale_27 = regime_scale.reindex(ret_27.index).ffill().fillna(1.0)
    ret_28 = (ret_27 * vol_scale_27 * regime_scale_27).dropna()
    print(f"\n[Phase 4.4] combined stack: mean_vol_scale={vol_scale_27.mean():.3f}  mean_regime={regime_scale_27.mean():.3f}")
    r28 = gate_report("COMBINED (recal × vol × regime)", ret_28, 28)
    results.append(r28)
    ret_28.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr28_combined_oos.parquet"
    )

    # ================================================================
    # Summary table
    # ================================================================
    print("\n" + "=" * 70)
    print("  Phase 4 summary (all vs baseline capped #24)")
    print("=" * 70)
    print(f"{'trial':<45}{'ann':>10}{'Sharpe':>8}{'MDD':>10}{'PSR':>8}{'pass':>6}")
    print(f"{'#24 baseline (capped)':<45}{'+10.56%':>10}{'0.64':>8}{'-26.77%':>10}{'0.983':>8}{'2/5':>6}")
    for r in results:
        label = f"#{r['dsr']} {r['name']}"[:44]
        ann_s = f"{r['ann']:+.2%}"
        mdd_s = f"{r['mdd']:.2%}"
        psr_s = f"{r['psr']:.3f}"
        sr_s = f"{r['sharpe']:.2f}"
        pass_s = f"{r['n_pass']}/5"
        print(f"{label:<45}{ann_s:>10}{sr_s:>8}{mdd_s:>10}{psr_s:>8}{pass_s:>6}")

    best = max(results, key=lambda x: x["n_pass"])
    print(f"\nBest: DSR #{best['dsr']} — {best['name']} ({best['n_pass']}/5 PASS)")
    if best["n_pass"] >= 5:
        print(">>> FULL PASS — paper-trade candidate <<<")
    elif best["n_pass"] >= 3:
        print(">>> partial improvement, evaluate for jialong option A ensemble <<<")
    else:
        print(">>> no improvement — structural finding, recommend option B/C <<<")


if __name__ == "__main__":
    main()
