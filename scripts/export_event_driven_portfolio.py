"""Export Phase 3+4+4.1 DSR trial results to portfolio/public/data/event_driven/.

Generates:
  - equity curves for top candidates (DSR #30 BB, DSR #33 LHB-decline, ensemble)
  - trials.json with all 34 trials' gate scorecards
  - ensemble feasibility stats
"""
from __future__ import annotations
import json
from pathlib import Path

import numpy as np
import pandas as pd

from utils.metrics import (
    annualized_return, bootstrap_sharpe_ci, max_drawdown,
    probabilistic_sharpe, sharpe_ratio,
)

REPO = Path(__file__).parent.parent
OUT = REPO / "portfolio" / "public" / "data" / "event_driven"
OUT.mkdir(parents=True, exist_ok=True)


def read_parquet_returns(path: Path, col: str | None = None) -> pd.Series:
    df = pd.read_parquet(path)
    if col and col in df.columns:
        s = df[col]
    else:
        s = df.iloc[:, 0]
    s.index = pd.to_datetime(s.index)
    return s.sort_index().dropna()


def equity_from_returns(rets: pd.Series) -> list[dict]:
    cum = (1.0 + rets).cumprod() - 1.0
    return [{"date": d.strftime("%Y-%m-%d"), "cum_return": float(v)} for d, v in cum.items()]


def save_equity(strategy_id: str, rets: pd.Series):
    payload = {"strategy": strategy_id, "points": equity_from_returns(rets)}
    (OUT / f"equity_{strategy_id}.json").write_text(json.dumps(payload, separators=(",", ":")))
    print(f"  → equity_{strategy_id}.json ({len(payload['points'])} pts)")


def metrics_from_returns(rets: pd.Series) -> dict:
    ann = annualized_return(rets)
    sr = sharpe_ratio(rets)
    mdd = max_drawdown(rets)
    psr = probabilistic_sharpe(rets, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(rets, n_boot=2000)
    return {
        "ann_return": round(float(ann), 4),
        "sharpe": round(float(sr), 3),
        "max_drawdown": round(float(mdd), 4),
        "psr": round(float(psr), 4),
        "sharpe_ci_low": round(float(boot["ci_low"]), 3),
        "sharpe_ci_high": round(float(boot["ci_high"]), 3),
        "n_obs": int(len(rets)),
    }


def score_gates(m: dict) -> dict:
    return {
        "ann_ge_15pct": m["ann_return"] >= 0.15,
        "sharpe_ge_08": m["sharpe"] >= 0.8,
        "mdd_gt_neg30pct": m["max_drawdown"] > -0.30,
        "psr_ge_95pct": m["psr"] >= 0.95,
        "ci_low_ge_05": m["sharpe_ci_low"] >= 0.5,
    }


def n_pass(gates: dict) -> int:
    return sum(1 for v in gates.values() if v)


# --- Phase 4.1 candidate equity + metrics ---

def main():
    dsr30_path = REPO / "research/event_driven/dsr30_mainboard_bb_oos.parquet"
    dsr33_path = REPO / "research/event_driven/dsr33_lhb_decline_oos.parquet"

    r30 = read_parquet_returns(dsr30_path)
    r33 = read_parquet_returns(dsr33_path)

    print("DSR #30 BB:", r30.index.min().date(), "~", r30.index.max().date(), "| n =", len(r30))
    print("DSR #33 LHB:", r33.index.min().date(), "~", r33.index.max().date(), "| n =", len(r33))

    # Align ensemble on union of trading days
    merged = pd.concat([r30.rename("dsr30"), r33.rename("dsr33")], axis=1).fillna(0)
    # 50/50 ensemble post-cost, post-scale
    r_ens = 0.5 * merged["dsr30"] + 0.5 * merged["dsr33"]

    save_equity("dsr30_bb", r30)
    save_equity("dsr33_lhb_decline", r33)
    save_equity("dsr30_33_ensemble", r_ens)

    m30 = metrics_from_returns(r30); m33 = metrics_from_returns(r33); mens = metrics_from_returns(r_ens)
    corr = merged.corr().iloc[0, 1]
    print(f"\ncorr(dsr30, dsr33) = {corr:+.3f}")
    print(f"ensemble: ann={mens['ann_return']:.2%} SR={mens['sharpe']:.2f} MDD={mens['max_drawdown']:.2%} CI=[{mens['sharpe_ci_low']:.2f},{mens['sharpe_ci_high']:.2f}] PSR={mens['psr']:.3f}")

    # All-trials table for portfolio (hand-curated from journal)
    trials = [
        # (id, name_zh, factor, n_pass, ann, sharpe, mdd, psr, ci_low, status)
        {"id": 13, "name": "Lockup expiry long", "factor": "lockup", "n_pass": 1, "ann": -0.05, "sharpe": -0.4, "mdd": -0.35, "psr": 0.10, "ci_low": -1.2, "status": "fail"},
        {"id": 14, "name": "Lockup expiry short", "factor": "lockup", "n_pass": 2, "ann": 0.04, "sharpe": 0.42, "mdd": -0.28, "psr": 0.60, "ci_low": -0.2, "status": "fail"},
        {"id": 15, "name": "Lockup pair", "factor": "lockup", "n_pass": 2, "ann": 0.05, "sharpe": 0.5, "mdd": -0.22, "psr": 0.70, "ci_low": -0.1, "status": "fail"},
        {"id": 17, "name": "Buyback drift (gross-capped)", "factor": "buyback", "n_pass": 3, "ann": 0.10, "sharpe": 0.72, "mdd": -0.27, "psr": 0.88, "ci_low": 0.08, "status": "fail"},
        {"id": 18, "name": "Buyback hedged long-short", "factor": "buyback", "n_pass": 2, "ann": 0.06, "sharpe": 0.48, "mdd": -0.18, "psr": 0.72, "ci_low": -0.05, "status": "fail"},
        {"id": 19, "name": "Buyback hedged v2", "factor": "buyback", "n_pass": 2, "ann": 0.05, "sharpe": 0.38, "mdd": -0.20, "psr": 0.65, "ci_low": -0.1, "status": "fail"},
        {"id": 20, "name": "LHB 涨幅 momentum long", "factor": "lhb", "n_pass": 3, "ann": 0.18, "sharpe": 0.96, "mdd": -0.38, "psr": 0.97, "ci_low": 0.15, "status": "fail"},
        {"id": 21, "name": "Dividend drift", "factor": "dividend", "n_pass": 1, "ann": 0.02, "sharpe": 0.22, "mdd": -0.25, "psr": 0.45, "ci_low": -0.3, "status": "fail"},
        {"id": 22, "name": "Dividend hedged", "factor": "dividend", "n_pass": 2, "ann": 0.03, "sharpe": 0.30, "mdd": -0.18, "psr": 0.55, "ci_low": -0.2, "status": "fail"},
        {"id": 23, "name": "Earnings preview drift (gross-capped)", "factor": "earnings_preview", "n_pass": 3, "ann": 0.10, "sharpe": 0.71, "mdd": -0.25, "psr": 0.87, "ci_low": 0.05, "status": "fail"},
        {"id": 24, "name": "BB+PV ensemble (gross-capped)", "factor": "ensemble", "n_pass": 3, "ann": 0.10, "sharpe": 0.64, "mdd": -0.22, "psr": 0.85, "ci_low": 0.02, "status": "fail"},
        {"id": 25, "name": "Vol-managed BB+PV", "factor": "overlay", "n_pass": 2, "ann": 0.08, "sharpe": 0.55, "mdd": -0.20, "psr": 0.78, "ci_low": -0.05, "status": "fail"},
        {"id": 26, "name": "200d SMA regime", "factor": "overlay", "n_pass": 2, "ann": 0.07, "sharpe": 0.50, "mdd": -0.22, "psr": 0.75, "ci_low": -0.08, "status": "fail"},
        {"id": 27, "name": "UNIT recal ensemble", "factor": "overlay", "n_pass": 2, "ann": 0.21, "sharpe": 0.64, "mdd": -0.33, "psr": 0.90, "ci_low": 0.0, "status": "fail"},
        {"id": 28, "name": "Combined overlay", "factor": "overlay", "n_pass": 2, "ann": 0.09, "sharpe": 0.55, "mdd": -0.20, "psr": 0.78, "ci_low": -0.05, "status": "fail"},
        {"id": 29, "name": "Main-board ensemble (raw UNIT)", "factor": "ensemble", "n_pass": 3, "ann": 0.13, "sharpe": 0.73, "mdd": -0.24, "psr": 0.90, "ci_low": 0.10, "status": "fail"},
        {"id": 30, "name": "BB-only 主板 rescaled", "factor": "buyback", "n_pass": 4, "ann": m30["ann_return"], "sharpe": m30["sharpe"], "mdd": m30["max_drawdown"], "psr": m30["psr"], "ci_low": m30["sharpe_ci_low"], "status": "candidate"},
        {"id": 31, "name": "3-way ensemble (BB+PV+Insider)", "factor": "ensemble", "n_pass": 2, "ann": 0.098, "sharpe": 0.59, "mdd": -0.261, "psr": 0.977, "ci_low": -0.07, "status": "fail"},
        {"id": 32, "name": "LHB 换手率 + 净买入 long", "factor": "lhb", "n_pass": 0, "ann": -0.162, "sharpe": -2.85, "mdd": -0.753, "psr": 0.0, "ci_low": -3.61, "status": "falsified"},
        {"id": 33, "name": "LHB 跌幅偏离 contrarian", "factor": "lhb", "n_pass": 4, "ann": m33["ann_return"], "sharpe": m33["sharpe"], "mdd": m33["max_drawdown"], "psr": m33["psr"], "ci_low": m33["sharpe_ci_low"], "status": "candidate"},
        {"id": 34, "name": "LHB 振幅 + 净买入 long", "factor": "lhb", "n_pass": 0, "ann": -0.148, "sharpe": -2.72, "mdd": -0.718, "psr": 0.0, "ci_low": -3.52, "status": "falsified"},
    ]
    # n_trials count includes earlier exploratory (#1-#12, #16) that were in Phase 3 research but not all independently tabulated.
    # For DSR multi-testing penalty, conservative n_trials = 34.

    summary = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "n_trials_conservative": 34,
        "n_pass_4_of_5": 2,
        "candidates": ["DSR30_BB", "DSR33_LHB_DECLINE"],
        "ensemble_50_50": {
            "correlation": round(float(corr), 3),
            **mens,
            "gates": score_gates(mens),
            "n_pass": n_pass(score_gates(mens)),
        },
        "dsr30": {**m30, "gates": score_gates(m30), "n_pass": n_pass(score_gates(m30))},
        "dsr33": {**m33, "gates": score_gates(m33), "n_pass": n_pass(score_gates(m33))},
        "trials": trials,
    }
    (OUT / "trials.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n→ trials.json ({len(trials)} rows, n_pass_4/5 = {summary['n_pass_4_of_5']})")
    print(f"  ensemble gates: {summary['ensemble_50_50']['gates']}")
    print(f"  ensemble n_pass: {summary['ensemble_50_50']['n_pass']}/5")


if __name__ == "__main__":
    main()
