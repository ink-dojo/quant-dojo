"""
C 路: roe_stability + HS300 composite regime overlay (Issue #60).

假设: roe_stability 单腿 5/7 切片 PASS, T4 (2025 H2) 失败是 regime 错配
(高低切换 + 大蓝筹被抛弃). 加 HS300 composite regime mask (RSRS + vol/turnover
two-vote) 在 bear 日子空仓, T4 自动失活 → 通过 framework 全 OOS 严格门.

数据:
- 复用 Issue #47 路径 (utils.factor_analysis.neutralize_factor + cross_section_rank)
- HS300 价量信号: data/raw/tushare/index_daily_000300.parquet (high/low/close/vol)

红线 (CLAUDE.md):
- regime mask 只能用 HS300 价量 (外生信号), 不能用 forward returns
- 不调任何参数 (RSRS 默认 upper=0.7/lower=-0.7/window=18, vol_turnover 默认)
- 跟 baseline (no overlay) 数字并列报告, 让 jialong 自己判 "改善是否显著"

执行: python research/factors/tushare_factors/roe_stability_regime_overlay.py
"""
from __future__ import annotations

import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_roe_stability,
    compute_forward_returns,
)
from research.factors.tushare_factors.neutralize_and_cost import (  # noqa: E402
    HORIZON,
    MIN_STOCKS_FOR_IC,
    build_df_info,
    build_price_panel,
    build_size_panel,
    cost_aware_long_short,
    load_industry_l1,
    resolve_stock_pools,
)
from utils.factor_analysis import (  # noqa: E402
    compute_ic_series,
    cross_section_rank,
    ic_summary,
    neutralize_factor,
)
from utils.market_regime import (  # noqa: E402
    composite_regime,
    rsrs_regime_mask,
    vol_turnover_regime,
)

warnings.filterwarnings("ignore")

DATA = ROOT / "data" / "raw" / "tushare"
HS300_PATH = DATA / "index_daily_000300.parquet"
OUT = ROOT / "research" / "factors" / "tushare_factors"
RESULTS_PATH = OUT / "roe_stability_regime_overlay_results.json"

PASS_SHARPE = 0.8
MIN_PERIODS_FOR_VERDICT = 3

TIME_SLICES: list[tuple[str, str, str]] = [
    ("T1_long_history",  "2020-01-01", "2023-12-31"),
    ("T2_fold1_2024",    "2024-01-01", "2024-12-31"),
    ("T3_fold2_2025h1",  "2025-01-01", "2025-06-30"),
    ("T4_fold3_2025h2",  "2025-07-01", "2025-12-31"),
    ("T5_fresh_2026q1",  "2026-01-01", "2026-12-31"),
]


# ─────────────────────────────────────────────────────────────
# 1. HS300 composite regime
# ─────────────────────────────────────────────────────────────

def load_hs300_composite_regime(price_idx: pd.DatetimeIndex) -> pd.Series:
    """HS300 composite (RSRS + vol_turnover) bull mask, 与 price_idx 对齐.

    True = bull (持仓), False = bear/flat (空仓).
    用 high/low (RSRS) + close/volume (vol_turnover) 双信号 AND.
    """
    hs = pd.read_parquet(HS300_PATH)
    hs["trade_date"] = pd.to_datetime(hs["trade_date"], format="%Y%m%d", errors="coerce")
    hs = hs.set_index("trade_date").sort_index()
    composite = composite_regime(hs["high"], hs["low"], hs["close"], hs["vol"])
    aligned = composite.reindex(price_idx).ffill().fillna(False).astype(bool)
    print(f"  [regime] composite bull: {aligned.sum()} days ({aligned.mean():.1%}), "
          f"bear/flat: {(~aligned).sum()} days")
    return aligned


# ─────────────────────────────────────────────────────────────
# 2. metrics on a slice (with regime overlay choice)
# ─────────────────────────────────────────────────────────────

def slice_dates(idx: pd.DatetimeIndex, start: str, end: str) -> pd.DatetimeIndex:
    return idx[(idx >= pd.Timestamp(start)) & (idx <= pd.Timestamp(end))]


def metrics_for_slice(
    factor_wide: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    dates: pd.DatetimeIndex,
    full_ic_series: pd.Series,
    full_sample_ic_sign: int,
) -> dict:
    """切片 IC + cost-aware sharpe + verdict. 复用 regime_oos_slice 模式."""
    if len(dates) < HORIZON * MIN_PERIODS_FOR_VERDICT:
        return {"n_days": int(len(dates)), "verdict": "N/A",
                "ic_mean": None, "ic_t_hac": None,
                "sharpe_net": None, "net_ann": None, "n_periods": 0}

    fac = factor_wide.reindex(dates)
    ret = fwd_ret.reindex(dates)
    ic = full_ic_series.reindex(dates)
    if ic.dropna().shape[0] < MIN_STOCKS_FOR_IC:
        return {"n_days": int(len(dates)), "verdict": "N/A",
                "ic_mean": None, "ic_t_hac": None,
                "sharpe_net": None, "net_ann": None, "n_periods": 0}

    s = ic_summary(ic, name="slice", fwd_days=HORIZON, verbose=False)
    bt = cost_aware_long_short(fac, ret, long_short="Qn_minus_Q1")

    sharpe_net = bt["sharpe_net"]
    ic_mean = s["IC_mean"]
    n_periods = bt["n_periods"]
    if n_periods < MIN_PERIODS_FOR_VERDICT or pd.isna(sharpe_net):
        verdict = "N/A"
    elif (ic_mean is not None and not pd.isna(ic_mean)
          and np.sign(ic_mean) != full_sample_ic_sign):
        verdict = "FAIL_IC_FLIP"
    elif sharpe_net <= 0:
        verdict = "FAIL_NEG_SHARPE"
    elif sharpe_net < PASS_SHARPE:
        verdict = "MARGINAL"
    else:
        verdict = "PASS"

    return {
        "n_days": int(len(dates)),
        "ic_mean": round(float(ic_mean), 4) if not pd.isna(ic_mean) else None,
        "ic_t_hac": round(float(s["t_stat_hac"]), 2) if not pd.isna(s["t_stat_hac"]) else None,
        "n_periods": int(n_periods),
        "sharpe_net": round(float(sharpe_net), 3) if not pd.isna(sharpe_net) else None,
        "sharpe_gross": round(float(bt["sharpe_gross"]), 3) if not pd.isna(bt["sharpe_gross"]) else None,
        "net_ann": round(float(bt["net_ann"]), 4) if not pd.isna(bt["net_ann"]) else None,
        "verdict": verdict,
    }


# ─────────────────────────────────────────────────────────────
# 3. 主流程: baseline vs overlay 并列
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 92)
    print("roe_stability + HS300 composite regime overlay (Issue #60, C 路)")
    print("=" * 92)

    # 3.1 数据 (复用 Issue #47 路径)
    pools = resolve_stock_pools()
    quality_stocks = pools["quality"]
    print(f"\n股票池: quality={len(quality_stocks)}")

    print("\n[Step 1] 价格 / size / 行业 / 前向收益")
    price_wide = build_price_panel(pools["core"], "20200101", "20261231")
    fwd_ret = compute_forward_returns(price_wide, horizon=HORIZON)
    size_panel = build_size_panel(pools["core"], price_wide.index)
    industry_l1 = load_industry_l1()
    df_info = build_df_info(size_panel, industry_l1)
    print(f"  price shape: {price_wide.shape}")

    print("\n[Step 2] roe_stability 中性化 (size + SW-L1) + rank")
    f_roe = build_roe_stability(quality_stocks, price_wide.index).reindex(price_wide.index)
    r_roe = cross_section_rank(neutralize_factor(f_roe, df_info, n_sigma=3.0))

    # 3.2 HS300 composite regime mask
    print("\n[Step 3] HS300 composite regime mask (RSRS + vol_turnover)")
    bull_mask = load_hs300_composite_regime(price_wide.index)

    # 3.3 baseline IC + sign
    print("\n[Step 4] baseline 全样本 IC sign")
    ic_baseline = compute_ic_series(r_roe, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
    sign_baseline = int(np.sign(ic_baseline.dropna().mean()))
    print(f"  baseline IC mean = {ic_baseline.dropna().mean():+.4f} (sign {sign_baseline:+d})")

    # 3.4 overlay 版: bear 日子的 fwd_ret 全设 NaN (相当于该日不持仓)
    fwd_ret_overlay = fwd_ret.copy()
    bear_dates = price_wide.index[~bull_mask.values]
    fwd_ret_overlay.loc[bear_dates, :] = np.nan
    print(f"\n[Step 5] overlay 版 fwd_ret: bear {len(bear_dates)} 日 全设 NaN")

    ic_overlay = compute_ic_series(r_roe, fwd_ret_overlay, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
    sign_overlay = int(np.sign(ic_overlay.dropna().mean()))
    print(f"  overlay IC mean = {ic_overlay.dropna().mean():+.4f} (sign {sign_overlay:+d})")

    # 3.5 跑 7 切片 baseline + overlay 并列
    print("\n" + "=" * 92)
    print("OOS 切片 baseline vs overlay 并列")
    print("=" * 92)
    print(f"  {'slice':<22} {'BASELINE':<28}    {'OVERLAY':<28}")
    print(f"  {'':<22} {'sharpe_net':>10} {'verdict':<14}    {'sharpe_net':>10} {'verdict':<14}")
    print("  " + "─" * 88)

    slices = [(label, slice_dates(price_wide.index, s, e)) for label, s, e in TIME_SLICES]
    slices.append(("F_full_sample", price_wide.index))

    results = {}
    for slabel, sidx in slices:
        m_base = metrics_for_slice(r_roe, fwd_ret, sidx, ic_baseline, sign_baseline)
        m_over = metrics_for_slice(r_roe, fwd_ret_overlay, sidx, ic_overlay, sign_overlay)
        results[slabel] = {"baseline": m_base, "overlay": m_over}
        sb = f"{m_base['sharpe_net']:>+9.3f}" if m_base['sharpe_net'] is not None else f"{'—':>10}"
        so = f"{m_over['sharpe_net']:>+9.3f}" if m_over['sharpe_net'] is not None else f"{'—':>10}"
        print(f"  {slabel:<22} {sb} {m_base['verdict']:<14}    "
              f"{so} {m_over['verdict']:<14}")

    # 3.6 决议
    print("\n" + "=" * 92)
    print("决策: baseline 7 切片 vs overlay 7 切片 PASS/FAIL 计数")
    print("=" * 92)
    base_pass = sum(1 for r in results.values() if r["baseline"]["verdict"] == "PASS")
    base_fail = sum(1 for r in results.values() if r["baseline"]["verdict"].startswith("FAIL"))
    over_pass = sum(1 for r in results.values() if r["overlay"]["verdict"] == "PASS")
    over_fail = sum(1 for r in results.values() if r["overlay"]["verdict"].startswith("FAIL"))
    print(f"  baseline:  PASS {base_pass} / FAIL {base_fail} / 总 {len(results)}")
    print(f"  overlay :  PASS {over_pass} / FAIL {over_fail} / 总 {len(results)}")

    if over_fail == 0 and base_fail > 0:
        print("\n  ✅ overlay 把所有 FAIL 切片救活 (设计意图达成).")
        print("     接下来需要 jialong 评审: regime overlay 是否引入 OOS 拟合风险?")
        print("     正面: overlay 用纯外生 HS300 信号, 没用 fwd_ret 反推. 红线没破.")
        print("     负面: overlay 在 T4 把策略空仓, 等于事后说 '我知道 2025H2 不该持仓'.")
        print("           用 RSRS/vol_turnover 信号, 是否真能 ex-ante 识别 T4 ?")
    elif over_fail < base_fail:
        print(f"\n  🟡 overlay 减少 FAIL 切片 ({base_fail} → {over_fail}) 但仍有 FAIL.")
        print("     部分 regime 错配可控, 但不全部.")
    else:
        print(f"\n  ❌ overlay 没改善 FAIL 切片 (base {base_fail} → over {over_fail}).")
        print("     HS300 composite regime 信号不能识别 T4 失败时点. roe_stability 仍卡 framework 严格门.")

    payload = {
        "config": {
            "horizon": HORIZON, "pass_sharpe": PASS_SHARPE,
            "regime_method": "composite (RSRS + vol_turnover)",
        },
        "n_days": int(len(price_wide.index)),
        "n_bull_days": int(bull_mask.sum()),
        "baseline_ic_mean": float(ic_baseline.dropna().mean()),
        "overlay_ic_mean": float(ic_overlay.dropna().mean()),
        "results": results,
        "summary": {
            "baseline": {"PASS": base_pass, "FAIL": base_fail, "total": len(results)},
            "overlay": {"PASS": over_pass, "FAIL": over_fail, "total": len(results)},
        },
    }
    OUT.mkdir(parents=True, exist_ok=True)
    RESULTS_PATH.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {RESULTS_PATH}")
    return payload


if __name__ == "__main__":
    run()
