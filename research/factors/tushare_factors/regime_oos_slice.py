"""
OOS regime 切片检验 (Issue #47).

对 Issue #46 的 stacked 2-腿 (roe_stability + inst_flow_20d, 等权 rank) 以及
两个单腿做时间分段 + bull/bear regime 分段, 看每段是否站得住. 用 RIAD Fold
失败的教训反推: 全样本 sharpe 1.66 不能直接当 OOS 证据.

切片:
    时间 (RIAD Fold 同款边界, 数据范围内能切多少切多少):
        T1 long_history    : 2020-01 ~ 2023-12
        T2 fold1_2024      : 2024-01 ~ 2024-12
        T3 fold2_2025h1    : 2025-01 ~ 2025-06
        T4 fold3_2025h2    : 2025-07 ~ 2025-12   ← RIAD 在此崩
        T5 fresh_2026q1    : 2026-01 ~ 2026-04
    Regime (HS300 vs MA120):
        R1 bull            : HS300 close >= MA120
        R2 bear            : HS300 close <  MA120
    Anchor:
        F  full_sample     : 2020-01 ~ end

度量 (每个 (factor, slice) cell):
    n_days, ic_mean, ic_t_hac    — 信号强度
    n_periods, sharpe_gross,
    sharpe_net, net_ann,
    avg_turnover                 — 落地后表现 (cost-aware, 月频, 双边 0.3%)
    verdict                       — PASS / MARGINAL / FAIL / N/A (n_periods<3)

判定 (per-cell):
    PASS     : sharpe_net >= 0.8 且 ic_mean 与全样本同号
    MARGINAL : 0 < sharpe_net < 0.8
    FAIL     : sharpe_net <= 0 或 ic_mean 翻号
    N/A      : n_periods < 3 (样本太短, 不评判)

输出:
    research/factors/tushare_factors/regime_oos_results.json (gitignored)
    控制台打印 PASS/FAIL 矩阵

执行:
    python research/factors/tushare_factors/regime_oos_slice.py
"""
import json
import sys
import warnings
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_inst_flow,
    build_roe_stability,
)
from research.factors.tushare_factors.neutralize_and_cost import (  # noqa: E402
    HORIZON,
    build_df_info,
    build_price_panel,
    build_size_panel,
    compute_forward_returns,
    cost_aware_long_short,
    load_industry_l1,
)
from utils.factor_analysis import (  # noqa: E402
    compute_ic_series,
    ic_summary,
    neutralize_factor,
)

warnings.filterwarnings("ignore")

DATA = ROOT / "data" / "raw" / "tushare"
HS300_PATH = DATA / "index_daily_000300.parquet"
OUT = ROOT / "research" / "factors" / "tushare_factors"

REGIME_MA = 120  # HS300 牛熊判定窗口 (与 factor_research.regime_split 一致)
MIN_PERIODS_FOR_VERDICT = 3
PASS_SHARPE = 0.8


# ─────────────────────────────────────────────────────────────
# 1. 切片定义
# ─────────────────────────────────────────────────────────────

def time_slices() -> list[tuple[str, str, str]]:
    """(label, start, end) 三元组, end 为闭区间."""
    return [
        ("T1_long_history",  "2020-01-01", "2023-12-31"),
        ("T2_fold1_2024",    "2024-01-01", "2024-12-31"),
        ("T3_fold2_2025h1",  "2025-01-01", "2025-06-30"),
        ("T4_fold3_2025h2",  "2025-07-01", "2025-12-31"),
        ("T5_fresh_2026q1",  "2026-01-01", "2026-12-31"),
    ]


def load_hs300_regime(price_idx: pd.DatetimeIndex, ma: int = REGIME_MA) -> pd.Series:
    """返回 bool Series, True=bull (HS300 >= MA120), False=bear, 与 price_idx 对齐."""
    hs = pd.read_parquet(HS300_PATH)
    if hs.index.name != "trade_date":
        if "trade_date" in hs.columns:
            hs["trade_date"] = pd.to_datetime(hs["trade_date"], errors="coerce")
            hs = hs.set_index("trade_date").sort_index()
        else:
            hs.index = pd.to_datetime(hs.index)
            hs = hs.sort_index()
    if "close" not in hs.columns:
        raise KeyError(f"index_daily_000300.parquet 没找到 close 列, 实际列: {list(hs.columns)}")
    ma_close = hs["close"].rolling(ma, min_periods=ma).mean()
    is_bull = (hs["close"] >= ma_close).reindex(price_idx).ffill()
    return is_bull.fillna(False).astype(bool)


def slice_dates(
    full_idx: pd.DatetimeIndex,
    start: Optional[str] = None,
    end: Optional[str] = None,
    mask: Optional[pd.Series] = None,
) -> pd.DatetimeIndex:
    idx = full_idx
    if start is not None:
        idx = idx[idx >= pd.Timestamp(start)]
    if end is not None:
        idx = idx[idx <= pd.Timestamp(end)]
    if mask is not None:
        m = mask.reindex(idx).fillna(False)
        idx = idx[m.values]
    return idx


# ─────────────────────────────────────────────────────────────
# 2. 单切片度量
# ─────────────────────────────────────────────────────────────

def metrics_for_slice(
    factor_wide: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    dates: pd.DatetimeIndex,
    direction: str,
    full_sample_ic_sign: Optional[int] = None,
) -> dict:
    """切片内: IC + cost-aware L-S 净 sharpe + verdict.

    full_sample_ic_sign: +1/-1, 用于检测 IC 翻号 (slice IC 与全样本反号 → FAIL).
    """
    if len(dates) < HORIZON * MIN_PERIODS_FOR_VERDICT:
        return {
            "n_days": int(len(dates)),
            "ic_mean": None, "ic_t_hac": None,
            "n_periods": 0, "sharpe_gross": None, "sharpe_net": None,
            "net_ann": None, "avg_turnover": None,
            "verdict": "N/A",
        }

    fac = factor_wide.reindex(dates)
    ret = fwd_ret.reindex(dates)

    ic = compute_ic_series(fac, ret, method="spearman", min_stocks=30)
    ic_clean = ic.dropna()
    if len(ic_clean) < 30:
        return {
            "n_days": int(len(dates)),
            "ic_mean": None, "ic_t_hac": None,
            "n_periods": 0, "sharpe_gross": None, "sharpe_net": None,
            "net_ann": None, "avg_turnover": None,
            "verdict": "N/A",
        }
    s = ic_summary(ic, name="slice", fwd_days=HORIZON, verbose=False)

    bt = cost_aware_long_short(fac, ret, long_short=direction)

    # verdict
    sharpe_net = bt["sharpe_net"]
    ic_mean = s["IC_mean"]
    n_periods = bt["n_periods"]
    if n_periods < MIN_PERIODS_FOR_VERDICT or pd.isna(sharpe_net):
        verdict = "N/A"
    elif (full_sample_ic_sign is not None
          and ic_mean is not None
          and not pd.isna(ic_mean)
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
        "sharpe_gross": round(float(bt["sharpe_gross"]), 3) if not pd.isna(bt["sharpe_gross"]) else None,
        "sharpe_net": round(float(sharpe_net), 3) if not pd.isna(sharpe_net) else None,
        "net_ann": round(float(bt["net_ann"]), 4) if not pd.isna(bt["net_ann"]) else None,
        "avg_turnover": round(float(bt["avg_turnover"]), 3) if not pd.isna(bt["avg_turnover"]) else None,
        "verdict": verdict,
    }


# ─────────────────────────────────────────────────────────────
# 3. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 80)
    print("OOS regime 切片检验  (Issue #47)")
    print("=" * 80)

    # 3.1 股票池 (与 stacking_analysis 一致)
    mf_stocks = {f.stem for f in (DATA / "moneyflow").glob("*.parquet")}
    db_stocks = {f.stem for f in (DATA / "daily_basic").glob("*.parquet")}
    fi_stocks = {f.stem.replace("fina_indicator_", "")
                 for f in (DATA / "financial").glob("fina_indicator_*.parquet")}
    core_stocks = sorted(mf_stocks & db_stocks)
    quality_stocks = sorted(mf_stocks & db_stocks & fi_stocks)
    print(f"股票池: core={len(core_stocks)} quality={len(quality_stocks)}\n")

    # 3.2 价格 / size / 行业 / 前向收益
    print("[Step 1] 价格 / size / 行业 / 前向收益")
    price_wide = build_price_panel(core_stocks, "20200101", "20261231")
    fwd_ret = compute_forward_returns(price_wide, horizon=HORIZON)
    size_panel = build_size_panel(core_stocks, price_wide.index)
    industry_l1 = load_industry_l1()
    df_info = build_df_info(size_panel, industry_l1)
    print()

    # 3.3 中性化两个 winner + 等权 stacked
    print("[Step 2] 构造 + 中性化 (size + SW-L1)")
    f_inst = build_inst_flow(core_stocks).reindex(price_wide.index)
    f_roe = build_roe_stability(quality_stocks, price_wide.index).reindex(price_wide.index)
    n_inst = neutralize_factor(f_inst, df_info, n_sigma=3.0)
    n_roe = neutralize_factor(f_roe, df_info, n_sigma=3.0)
    r_inst = n_inst.rank(axis=1, pct=True)
    r_roe = n_roe.rank(axis=1, pct=True)
    r_stack = (r_inst + r_roe) / 2
    print()

    factors = {
        "inst_flow_20d": (r_inst, "Qn_minus_Q1"),
        "roe_stability": (r_roe, "Qn_minus_Q1"),
        "stacked_50_50": (r_stack, "Qn_minus_Q1"),
    }

    # 3.4 全样本 IC sign (作为 slice IC 翻号检测的 baseline)
    print("[Step 3] 全样本 IC sign 锁定")
    full_sample_signs = {}
    for name, (fac, _) in factors.items():
        ic = compute_ic_series(fac, fwd_ret, method="spearman", min_stocks=30)
        full_sample_signs[name] = int(np.sign(ic.dropna().mean()))
        print(f"  {name}: full IC mean = {ic.dropna().mean():+.4f} → sign = {full_sample_signs[name]:+d}")
    print()

    # 3.5 regime mask (HS300 牛熊)
    print("[Step 4] HS300 regime mask")
    is_bull = load_hs300_regime(price_wide.index, ma=REGIME_MA)
    print(f"  bull days = {is_bull.sum()}, bear days = {(~is_bull).sum()}, "
          f"bull% = {is_bull.mean():.1%}")
    print()

    # 3.6 slice 定义
    slices: list[tuple[str, pd.DatetimeIndex]] = []
    for label, s, e in time_slices():
        slices.append((label, slice_dates(price_wide.index, start=s, end=e)))
    slices.append(("R1_bull",        slice_dates(price_wide.index, mask=is_bull)))
    slices.append(("R2_bear",        slice_dates(price_wide.index, mask=~is_bull)))
    slices.append(("F_full_sample",  price_wide.index))

    # 3.7 跑 (factor × slice) 矩阵
    print("[Step 5] (factor × slice) 矩阵")
    results: dict[str, dict[str, dict]] = {}
    for fname, (fac, direction) in factors.items():
        results[fname] = {}
        for slabel, sidx in slices:
            m = metrics_for_slice(
                fac, fwd_ret, sidx, direction,
                full_sample_ic_sign=full_sample_signs[fname],
            )
            results[fname][slabel] = m
    print()

    # 3.8 控制台打印
    slice_labels = [s[0] for s in slices]
    print("=" * 80)
    print("结果表 (cost-aware, 月频, 双边 0.3%)")
    print("=" * 80)
    for fname in factors:
        print(f"\n  ── {fname} ──")
        cols = ["n_days", "n_periods", "ic_mean", "ic_t_hac",
                "sharpe_gross", "sharpe_net", "net_ann", "avg_turnover", "verdict"]
        rows = []
        for slabel in slice_labels:
            m = results[fname][slabel]
            rows.append({"slice": slabel, **{c: m.get(c) for c in cols}})
        df = pd.DataFrame(rows).set_index("slice")
        print(df.to_string(na_rep="—"))

    # 3.9 stacked 总结判定
    print("\n" + "=" * 80)
    print("Stacked 50/50 判定汇总")
    print("=" * 80)
    stacked_results = results["stacked_50_50"]
    by_verdict: dict[str, list[str]] = {}
    for slabel in slice_labels:
        v = stacked_results[slabel]["verdict"]
        by_verdict.setdefault(v, []).append(slabel)
    for v in ["PASS", "MARGINAL", "FAIL_NEG_SHARPE", "FAIL_IC_FLIP", "N/A"]:
        if v in by_verdict:
            print(f"  {v:<18}: {', '.join(by_verdict[v])}")

    # FAIL 切片做归因 (看是哪只腿)
    fail_slices = (by_verdict.get("FAIL_NEG_SHARPE", [])
                   + by_verdict.get("FAIL_IC_FLIP", []))
    if fail_slices:
        print("\n  FAIL 切片归因 (单腿表现):")
        for slabel in fail_slices:
            print(f"    {slabel}:")
            for leg in ["inst_flow_20d", "roe_stability"]:
                m = results[leg][slabel]
                print(f"      {leg:<16} sharpe_net={m['sharpe_net']} "
                      f"ic={m['ic_mean']} verdict={m['verdict']}")

    # 3.10 落盘
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "regime_oos_results.json"
    payload = {
        "horizon_days": HORIZON,
        "regime_ma": REGIME_MA,
        "pass_sharpe": PASS_SHARPE,
        "full_sample_ic_signs": full_sample_signs,
        "results": results,
    }
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str))
    print(f"\n✅ 写入 {out_path}")

    return payload


if __name__ == "__main__":
    run()
