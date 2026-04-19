"""DSR #30 — 主板 ensemble + UNIT recalibration to mean_gross 0.8 (pre-reg).

### 前因
DSR #29 发现主板过滤显著提升 buyback Sharpe (0.78 → 0.94), 但 mean_gross
只剩 0.40 (因为主板过滤掉了 ~40% 事件). 原 pre-reg spec 声明目标
mean_gross 0.8; 本策略用 formula-based UNIT rescale 恢复 spec 初衷.

### Pre-registration spec (零 DoF, formula-driven)
- 事件过滤: board == '主板' (同 #29)
- UNIT rescale formula (pre-commit):
    bb_scale = 0.8 / 0.403 = 1.985
    pv_scale = 0.8 / 0.350 = 2.286
  (分母来自 #29 实测 capped mean_gross, 分子是 Phase 3 pre-reg
   spec 中 "gross 0.8 typical" 的目标)
- cap = 1.0 (保留)
- 50/50 equal-weight ensemble

### Ex-ante 预期
- ann: ~#29 × (0.8/0.4) ≈ 2× 提升 (线性 leverage)
- Sharpe: 不变 (ratio invariant to linear scaling)
- MDD: 约 #29 × 2 (注意 cap=1.0 限制上界)
- PSR: 不变 (基于 Sharpe)
- CI_low: 不变 (基于 Sharpe 不确定性)

若 ann 从 9.88% → ~20%, Sharpe 仍 0.73, MDD 需 < -30%, 其他不变.

### Gate 判定
标准 5 门. PASS 4/5 = 有价值 partial win; 5/5 = paper-trade candidate.

### 红线
- 5/5 PASS → paper-trade
- 4/5 PASS (ann/Sharpe/MDD/PSR 过, CI_low 差) → 加 3rd alpha (#31 once ggcg data ready)
- ≤ 3/5 PASS → Phase 4 terminal, 承认 baseline Sharpe 0.94 是上限

### DSR: 30
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
    UNIT_POS_WEIGHT as BB_UNIT_BASE,
)
from research.event_driven.earnings_preview_strategy import (
    load_events as load_pv,
    build_long_only_weights as build_pv_raw,
    TXN_ROUND_TRIP as PV_COST,
    UNIT_POS_WEIGHT as PV_UNIT_BASE,
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

# Pre-committed formula values (from DSR #29 measurement)
BB_SCALE = 0.8 / 0.403  # ≈ 1.985
PV_SCALE = 0.8 / 0.350  # ≈ 2.286


def filter_mainboard(ev: pd.DataFrame) -> pd.DataFrame:
    mask = ev["symbol"].isin(MAIN_BOARD_SYMBOLS)
    return ev[mask].copy()


def run_alpha(load_fn, build_fn, cost: float, unit_base: float, scale: float, name: str) -> pd.Series:
    ev = load_fn(END)
    ev = filter_mainboard(ev)
    universe = sorted(ev["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=START, end=END)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)
    W = build_fn(ev, rets.index, unit_weight=unit_base * scale).reindex(columns=prices.columns).fillna(0)
    W_capped = apply_gross_cap(W, cap=1.0)
    w_exec = W_capped.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (cost / 2)
    net = (daily_gross - daily_cost).loc[START:END].dropna()
    gross_ts = W_capped.abs().sum(axis=1).loc[START:END]
    print(f"\n{name}: mean_gross={gross_ts.mean():.3f}  max_gross={gross_ts.max():.3f}")
    return net


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
    print(f"  ann={ann:+.2%}  Sharpe={sr:.2f}  MDD={mdd:.2%}  PSR={psr:.3f}  CI_low={boot['ci_low']:.2f}")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    return dict(n_pass=n_pass, ann=ann, sharpe=sr, mdd=mdd, psr=psr, ci_low=boot["ci_low"])


def main():
    logging.basicConfig(level=logging.WARNING)
    print("=" * 70)
    print(f"  DSR #30 — 主板 ensemble + UNIT recal (BB ×{BB_SCALE:.2f}, PV ×{PV_SCALE:.2f})")
    print("=" * 70)

    r_bb = run_alpha(load_bb, build_bb_raw, BB_COST, BB_UNIT_BASE, BB_SCALE, "buyback 主板 rescaled")
    res_bb = gate_report("buyback 主板 rescaled", r_bb)

    r_pv = run_alpha(load_pv, build_pv_raw, PV_COST, PV_UNIT_BASE, PV_SCALE, "preview 主板 rescaled")
    res_pv = gate_report("preview 主板 rescaled", r_pv)

    df = pd.concat([r_bb.rename("bb"), r_pv.rename("pv")], axis=1).dropna()
    ens = 0.5 * df["bb"] + 0.5 * df["pv"]
    corr = df.corr().iloc[0, 1]
    print(f"\ncorr(bb, pv) 主板 rescaled = {corr:.3f}")
    res_ens = gate_report("DSR #30 — 主板 ensemble rescaled", ens)
    ens.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet"
    )
    r_bb.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr30_mainboard_bb_oos.parquet"
    )
    r_pv.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr30_mainboard_pv_oos.parquet"
    )

    # Try buyback-only vs ensemble
    print(f"\n=== Summary: best individual vs ensemble ===")
    print(f"  BB-only: {res_bb['n_pass']}/5 (Sharpe {res_bb['sharpe']:.2f})")
    print(f"  PV-only: {res_pv['n_pass']}/5 (Sharpe {res_pv['sharpe']:.2f})")
    print(f"  Ensemble: {res_ens['n_pass']}/5 (Sharpe {res_ens['sharpe']:.2f})")


if __name__ == "__main__":
    main()
