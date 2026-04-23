"""
MD&A LLM drift mini-IC — bootstrap CI (Step 1 的显著性确认).

对 2024 cross-section 的 5 维度 pooled IC 做 1000 次 bootstrap resampling,
输出 CI_low (2.5%) / CI_high (97.5%) / median.

判读:
    - CI_low > 0 且 mean > 0 → 正向信号, 显著
    - CI_high < 0 且 mean < 0 → 负向信号, 显著
    - CI 跨 0 → 不显著, noise-dominated
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from research.factors.mda_drift.factor import DEFAULT_MANIFEST_PATH
from utils.local_data_loader import load_adj_price_wide

SCORES_PATH = Path("data/processed/mda_llm_drift_scores_2024.parquet")
OUT_PATH = Path("journal/mda_llm_drift_bootstrap_20260422.json")
JOURNAL_APPEND = Path("journal/mda_llm_drift_mini_ic_20260422.md")

DIMS = ["specificity_drift", "hedging_drift", "tone_drift",
        "forward_drift", "transparency_drift"]
FWD_DAYS = 20
COST_BPS = 30
N_BOOTSTRAP = 1000
SEED = 42


def build_panel() -> pd.DataFrame:
    scores = pd.read_parquet(SCORES_PATH)
    scores = scores[~scores["tone_drift"].isna()].copy()
    for d in DIMS:
        scores[d] = scores[d].astype(float)
        scores.loc[scores["order"] == "swap", d] = -scores.loc[scores["order"] == "swap", d]

    manifest = pd.read_parquet(DEFAULT_MANIFEST_PATH)
    manifest["publish_date"] = pd.to_datetime(manifest["publish_date"])
    mmap = manifest.set_index(["symbol", "fiscal_year"])["publish_date"].to_dict()
    scores["publish_date"] = scores.apply(
        lambda r: mmap.get((r.symbol, r.year_curr)), axis=1,
    )
    scores = scores[~scores["publish_date"].isna()]

    symbols = list(scores["symbol"].unique())
    prices = load_adj_price_wide(symbols=symbols, start="2024-01-01", end="2026-04-21")

    def fwd_ret(row):
        sym = row["symbol"]; pub = row["publish_date"]
        if sym not in prices.columns: return None
        sr = prices[sym].dropna()
        i = sr.index.searchsorted(pub, side="right")
        if i + FWD_DAYS >= len(sr): return None
        a, b = sr.iloc[i], sr.iloc[i + FWD_DAYS]
        if a <= 0 or pd.isna(a) or pd.isna(b): return None
        return float(b / a - 1 - COST_BPS / 10000)

    scores["fwd_ret_20d"] = scores.apply(fwd_ret, axis=1)
    scores = scores[~scores["fwd_ret_20d"].isna()]
    return scores.reset_index(drop=True)


def bootstrap_ic(panel: pd.DataFrame, dim: str, n: int = N_BOOTSTRAP, seed: int = SEED) -> dict:
    rng = np.random.default_rng(seed)
    N = len(panel)
    ics = np.empty(n)
    for i in range(n):
        idx = rng.integers(0, N, size=N)
        sub = panel.iloc[idx]
        ic = sub[dim].rank().corr(sub["fwd_ret_20d"].rank())
        ics[i] = ic
    return {
        "mean": float(np.nanmean(ics)),
        "median": float(np.nanmedian(ics)),
        "ci_low": float(np.nanpercentile(ics, 2.5)),
        "ci_high": float(np.nanpercentile(ics, 97.5)),
        "pct_above_zero": float((ics > 0).mean()),
        "pct_below_zero": float((ics < 0).mean()),
    }


def main() -> int:
    panel = build_panel()
    print(f"[panel] n = {len(panel)}  dates {panel.publish_date.min().date()}..{panel.publish_date.max().date()}")

    results = {}
    print("\n=== Bootstrap CI (1000 resamples) ===")
    print(f"{'dim':24s}  {'mean':>8s}  {'CI_low':>8s}  {'CI_high':>8s}  {'%>0':>6s}  {'显著':>4s}")
    for d in DIMS:
        r = bootstrap_ic(panel, d)
        results[d] = r
        sig = "✅" if (r["ci_low"] > 0) or (r["ci_high"] < 0) else "❌"
        print(f"{d:24s}  {r['mean']:+.4f}  {r['ci_low']:+.4f}  {r['ci_high']:+.4f}  "
              f"{r['pct_above_zero']:.1%}  {sig}")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({"n": len(panel), "dims": results}, f, indent=2)
    print(f"\n[saved] {OUT_PATH}")

    # 追加到 journal
    if JOURNAL_APPEND.exists():
        append_lines = [
            "",
            "## Bootstrap CI (1000 resamples, seed=42)",
            "",
            "| 维度 | mean | CI_low (2.5%) | CI_high (97.5%) | %>0 | 显著 |",
            "|---|---:|---:|---:|---:|:---:|",
        ]
        for d in DIMS:
            r = results[d]
            sig = "✅" if (r["ci_low"] > 0) or (r["ci_high"] < 0) else "❌"
            append_lines.append(
                f"| {d.replace('_drift','')} | {r['mean']:+.4f} | "
                f"{r['ci_low']:+.4f} | {r['ci_high']:+.4f} | "
                f"{r['pct_above_zero']:.1%} | {sig} |"
            )
        # 显著维度的判读
        sig_dims = [d for d in DIMS if (results[d]["ci_low"] > 0) or (results[d]["ci_high"] < 0)]
        append_lines += ["", "### Bootstrap 判读"]
        if sig_dims:
            append_lines.append(f"- 显著维度 ({len(sig_dims)}/5): {', '.join(d.replace('_drift','') for d in sig_dims)}")
            for d in sig_dims:
                r = results[d]
                direction = "正向" if r["mean"] > 0 else "负向"
                append_lines.append(
                    f"  - **{d.replace('_drift','')}**: {direction} 信号, "
                    f"mean={r['mean']:+.4f}, CI=[{r['ci_low']:+.4f}, {r['ci_high']:+.4f}]"
                )
        else:
            append_lines.append("- 所有维度 CI 跨 0, 无显著信号")
        append_lines.append("")
        with open(JOURNAL_APPEND, "a") as f:
            f.write("\n".join(append_lines))
        print(f"[appended] {JOURNAL_APPEND}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
