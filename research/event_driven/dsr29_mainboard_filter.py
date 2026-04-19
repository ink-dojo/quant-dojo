"""DSR #29 — 主板-only 宇宙过滤 (PRE-REG 2026-04-18, before execution).

### 假设 (ex-ante)
Capped ensemble 2/5 fail (ann/Sharpe/CI_low). 年度分布显示
2018/2022/2024 = 弱年, 其余强. 2024 Q1 = 小微盘 crash 主导, 主要
拖累 创业板(30x) + 科创板(68x) + 北交所(9x/83x) 仓位.

主板 (60x/00x) 公司大盘 + 成熟 + 波动低. 事件 universe 限定主板应:
- ↓ vol (特别是 2024) → ↑ Sharpe
- ↓ 左尾 DD
- ann 可能小降 (丢了小盘事件)

若 Sharpe 净 ↑ + ann 改善足够, 过 gate.

### Pre-registration spec (零 DoF)
- 事件过滤: listing_metadata.board == '主板'
  (即 symbol 以 '60' 或 '00' 开头, 排除 30x/68x/9x/83x)
- 其余 spec 同 #17 / #23 (top 30% monthly cross-section, T+1-T+20)
- UNIT: 保留原值 (1/15 for bb, 1/75 for pv) — 不额外调参
- gross cap = 1.0 (与 Phase 3.5 post-mortem 一致)
- 50/50 equal-weight ensemble of 2 filtered alphas

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线
- PASS 5/5 → paper-trade candidate
- 改善 但 <5/5 → 加入 DSR #30 (3-way with new event) 如果新数据有效
- 不改善或恶化 → 接受 Phase 4 无法攻破 baseline, 写结构化 terminal report

### DSR: 29 (cumulative)
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
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)

START, END = "2018-01-01", "2025-12-31"
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD_SYMBOLS = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())


def filter_mainboard(ev: pd.DataFrame) -> pd.DataFrame:
    mask = ev["symbol"].isin(MAIN_BOARD_SYMBOLS)
    dropped = len(ev) - mask.sum()
    logger.info(f"main-board filter: kept {mask.sum()}/{len(ev)} events, dropped {dropped}")
    return ev[mask].copy()


def run_alpha(load_fn, build_fn, cost: float, name: str) -> pd.Series:
    ev = load_fn(END)
    ev = filter_mainboard(ev)
    universe = sorted(ev["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=START, end=END)
    W = build_fn(ev, prices.pct_change().index).reindex(columns=prices.columns).fillna(0)
    W_capped = apply_gross_cap(W, cap=1.0)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)
    w_exec = W_capped.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (cost / 2)
    net = (daily_gross - daily_cost).loc[START:END].dropna()
    gross_ts = W_capped.abs().sum(axis=1).loc[START:END]
    print(f"\n{name}: events={len(ev)}, universe={len(universe)}, mean_gross={gross_ts.mean():.3f}")
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
    return dict(n_pass=n_pass, ann=ann, sharpe=sr, mdd=mdd, psr=psr)


def main():
    logging.basicConfig(level=logging.WARNING)
    print("=" * 70)
    print("  DSR #29 — 主板-only ensemble (pre-reg 2026-04-18)")
    print(f"  主板 symbols: {len(MAIN_BOARD_SYMBOLS)}")
    print("=" * 70)

    # DSR #29a: buyback main-board only
    r_bb = run_alpha(load_bb, build_bb_raw, BB_COST, "buyback 主板")
    gate_report("buyback 主板 only", r_bb)

    # DSR #29b: earnings preview main-board only
    r_pv = run_alpha(load_pv, build_pv_raw, PV_COST, "preview 主板")
    gate_report("preview 主板 only", r_pv)

    # Ensemble
    df = pd.concat([r_bb.rename("bb"), r_pv.rename("pv")], axis=1).dropna()
    ens = 0.5 * df["bb"] + 0.5 * df["pv"]
    corr = df.corr().iloc[0, 1]
    print(f"\n\ncorr(buyback, preview) on main-board = {corr:.3f}")
    res = gate_report("DSR #29 — 主板 ensemble 50/50", ens)
    ens.rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr29_mainboard_ensemble_oos.parquet"
    )

    print("\n" + "=" * 70)
    print(f"DSR #29 result: {res['n_pass']}/5 PASS")
    if res["n_pass"] == 5:
        print(">>> FULL PASS — paper-trade candidate <<<")
    elif res["sharpe"] > 0.7:
        print(">>> partial improvement over baseline (Sharpe 0.64) <<<")


if __name__ == "__main__":
    main()
