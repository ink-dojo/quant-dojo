"""
RIAD DSR + Bootstrap Sharpe CI

核心判断: 过 paper-trade 前 5-gate 的最终统计显著性门槛
    - Sharpe > 0.8 (Phase 4 门槛)
    - PSR >= 0.95 (显著优于 0)
    - DSR >= 0.95 (显著优于 n_trials selection)
    - bootstrap CI_low >= 0.5 (DSR #30 stacking 标准)

n_trials 估计:
    Phase 3+4 31 trials
    + PEAD修 +1
    + RIAD Q1/Q2Q3/Q1Q5/Top20/Bot20 等分位方案 = 5
    + MFD/BGFD/LULR/THCC/SB 另外 5 factor pre-screen
    + 各因子 variant (size vs size+ind, cost cases) 估 ×2
    保守估计 **n_trials = 44**

trials_sharpe_std 估计:
    31 DSR trials 里 Sharpe std ≈ 0.4 (Phase 3+4 报告)
    RIAD 6 因子的 LS Sharpe 分布 std ≈ 0.5-0.6
    保守取 0.5 年化
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]

from utils.metrics import (  # noqa: E402
    bootstrap_sharpe_ci,
    deflated_sharpe,
    probabilistic_sharpe,
    sharpe_ratio,
)

RIAD_BASELINE = ROOT / "research" / "factors" / "retail_inst_divergence" / "riad_ls_daily_returns.parquet"
RIAD_FILTERED = ROOT / "logs" / "riad_tradable_universe_returns.parquet"
RIAD_GATED = ROOT / "logs" / "riad_regime_gated_returns.parquet"
DSR30 = ROOT / "research" / "event_driven" / "dsr30_mainboard_bb_oos.parquet"
COMBINED = ROOT / "logs" / "riad_dsr30_combined_returns.parquet"

N_TRIALS = 44
TRIALS_SR_STD = 0.5
CI_ALPHA = 0.05


def evaluate(returns: pd.Series, label: str) -> dict:
    r = returns.dropna()
    if len(r) < 60:
        return {"label": label, "n": len(r), "error": "insufficient data"}

    sr = sharpe_ratio(r)
    psr = probabilistic_sharpe(r, sr_benchmark=0.0)
    dsr = deflated_sharpe(r, n_trials=N_TRIALS, trials_sharpe_std=TRIALS_SR_STD)
    ci = bootstrap_sharpe_ci(r, n_boot=2000, alpha=CI_ALPHA, seed=42)

    return {
        "label": label,
        "n": len(r),
        "sharpe": float(sr),
        "PSR": float(psr),
        "DSR": float(dsr),
        "CI_low": float(ci["ci_low"]),
        "CI_high": float(ci["ci_high"]),
        "passes_sharpe_0.8": sr > 0.8,
        "passes_PSR_0.95": psr >= 0.95,
        "passes_DSR_0.95": dsr >= 0.95,
        "passes_CI_low_0.5": ci["ci_low"] >= 0.5,
    }


def main() -> None:
    targets = []
    baseline = pd.read_parquet(RIAD_BASELINE)["net_ls"]
    targets.append(("RIAD baseline (full)", baseline))
    targets.append(("RIAD baseline IS 2023-10~2024-12", baseline.loc[:"2024-12-31"]))
    targets.append(("RIAD baseline OOS 2025", baseline.loc["2025-01-01":]))

    filtered = pd.read_parquet(RIAD_FILTERED)["net_ls"]
    targets.append(("RIAD filtered (full)", filtered))
    targets.append(("RIAD filtered OOS 2025", filtered.loc["2025-01-01":]))

    gated = pd.read_parquet(RIAD_GATED)["gated_net_ls"]
    targets.append(("RIAD gated (full)", gated))
    targets.append(("RIAD gated OOS 2025", gated.loc["2025-01-01":]))

    dsr30 = pd.read_parquet(DSR30)["net_return"]
    dsr30_aligned = dsr30.loc[baseline.index.min():baseline.index.max()]
    targets.append(("DSR #30 BB-only (共同区间)", dsr30_aligned))

    combined = pd.read_parquet(COMBINED)["combined_5050"]
    targets.append(("RIAD + DSR30 合成 50/50", combined))

    print("\n=== RIAD / DSR30 / Combined 5-gate 审计 ===")
    print(f"n_trials = {N_TRIALS}, trials_SR_std = {TRIALS_SR_STD} (保守估计)\n")

    header = f"{'Strategy':<36} {'n':>4} {'Sharpe':>7} {'PSR':>6} {'DSR':>6} {'CI_lo':>7} {'CI_hi':>7} {'SR>0.8':>7} {'CI>0.5':>7}"
    print(header)
    print("-" * len(header))
    records = {}
    for label, r in targets:
        rec = evaluate(r, label)
        records[label] = rec
        if "error" in rec:
            print(f"{label:<36}  (n={rec['n']}, skip)")
            continue
        print(
            f"{label:<36} "
            f"{rec['n']:>4} "
            f"{rec['sharpe']:>+6.2f} "
            f"{rec['PSR']:>6.3f} "
            f"{rec['DSR']:>6.3f} "
            f"{rec['CI_low']:>+6.2f} "
            f"{rec['CI_high']:>+6.2f} "
            f"{'✅' if rec['passes_sharpe_0.8'] else '❌':>7} "
            f"{'✅' if rec['passes_CI_low_0.5'] else '❌':>7}"
        )

    # Gate 判读汇总
    print("\n=== 最终 5-gate 判读 (必须全过 → paper-trade ready) ===")
    for label, rec in records.items():
        if "error" in rec:
            continue
        gates = {
            "Sharpe>0.8": rec["passes_sharpe_0.8"],
            "PSR>=0.95": rec["passes_PSR_0.95"],
            "DSR>=0.95": rec["passes_DSR_0.95"],
            "CI_low>=0.5": rec["passes_CI_low_0.5"],
        }
        n_pass = sum(gates.values())
        verdict = "READY" if n_pass == 4 else f"{n_pass}/4"
        passed = [k for k, v in gates.items() if v]
        failed = [k for k, v in gates.items() if not v]
        print(f"  [{verdict}] {label}: ✅{passed} ❌{failed}")

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_dsr_ci_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump({
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "n_trials_used": N_TRIALS,
            "trials_sharpe_std": TRIALS_SR_STD,
            "CI_alpha": CI_ALPHA,
            "records": records,
        }, f, indent=2, ensure_ascii=False)
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
