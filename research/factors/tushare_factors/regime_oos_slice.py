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
from typing import Literal, Optional

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_inst_flow,
    build_roe_stability,
    compute_forward_returns,
)
from research.factors.tushare_factors.neutralize_and_cost import (  # noqa: E402
    HORIZON,
    MIN_STOCKS_FOR_IC,
    Direction,
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

warnings.filterwarnings("ignore")

DATA = ROOT / "data" / "raw" / "tushare"
HS300_PATH = DATA / "index_daily_000300.parquet"
OUT = ROOT / "research" / "factors" / "tushare_factors"

REGIME_MA = 120  # HS300 牛熊判定窗口 (与 factor_research.regime_split 一致)
MIN_PERIODS_FOR_VERDICT = 3
PASS_SHARPE = 0.8

Verdict = Literal["PASS", "MARGINAL", "FAIL_NEG_SHARPE", "FAIL_IC_FLIP", "N/A"]
# 打印汇总顺序; 新增 verdict 必须加到这里, 否则汇总会漏行
VERDICT_ORDER: tuple[Verdict, ...] = (
    "PASS", "MARGINAL", "FAIL_NEG_SHARPE", "FAIL_IC_FLIP", "N/A",
)


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

def _na_metrics(n_days: int) -> dict:
    """切片样本太短或 IC 算不出来时的占位结果."""
    return {
        "n_days": int(n_days),
        "ic_mean": None, "ic_t_hac": None,
        "n_periods": 0, "sharpe_gross": None, "sharpe_net": None,
        "net_ann": None, "avg_turnover": None,
        "verdict": "N/A",
    }


def _round_or_none(v, ndigits: int):
    if v is None or pd.isna(v):
        return None
    return round(float(v), ndigits)


def _decide_verdict(
    sharpe_net: Optional[float],
    ic_mean: Optional[float],
    n_periods: int,
    full_sample_ic_sign: Optional[int],
) -> Verdict:
    if n_periods < MIN_PERIODS_FOR_VERDICT or sharpe_net is None or pd.isna(sharpe_net):
        return "N/A"
    if (full_sample_ic_sign is not None and ic_mean is not None
            and not pd.isna(ic_mean) and np.sign(ic_mean) != full_sample_ic_sign):
        return "FAIL_IC_FLIP"
    if sharpe_net <= 0:
        return "FAIL_NEG_SHARPE"
    if sharpe_net < PASS_SHARPE:
        return "MARGINAL"
    return "PASS"


def metrics_for_slice(
    factor_wide: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    dates: pd.DatetimeIndex,
    direction: Direction,
    full_ic_series: Optional[pd.Series] = None,
    full_sample_ic_sign: Optional[int] = None,
) -> dict:
    """切片内: IC + cost-aware L-S 净 sharpe + verdict.

    full_ic_series: 全样本上算好的 IC 序列 (与 factor_wide 同 index). 传入则
        切片直接重用对应日期, 不重跑 compute_ic_series 的逐日截面循环 —
        在 (factor x slice) 矩阵里这是 24x → 3x 的大优化.
    full_sample_ic_sign: +1/-1, 切片 IC 与全样本反号即 FAIL_IC_FLIP.
    """
    if len(dates) < HORIZON * MIN_PERIODS_FOR_VERDICT:
        return _na_metrics(len(dates))

    fac = factor_wide.reindex(dates)
    ret = fwd_ret.reindex(dates)

    if full_ic_series is not None:
        ic = full_ic_series.reindex(dates)
    else:
        ic = compute_ic_series(fac, ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)

    if ic.dropna().shape[0] < MIN_STOCKS_FOR_IC:
        return _na_metrics(len(dates))
    s = ic_summary(ic, name="slice", fwd_days=HORIZON, verbose=False)
    bt = cost_aware_long_short(fac, ret, long_short=direction)

    verdict = _decide_verdict(
        bt["sharpe_net"], s["IC_mean"], bt["n_periods"], full_sample_ic_sign,
    )
    return {
        "n_days": int(len(dates)),
        "ic_mean": _round_or_none(s["IC_mean"], 4),
        "ic_t_hac": _round_or_none(s["t_stat_hac"], 2),
        "n_periods": int(bt["n_periods"]),
        "sharpe_gross": _round_or_none(bt["sharpe_gross"], 3),
        "sharpe_net": _round_or_none(bt["sharpe_net"], 3),
        "net_ann": _round_or_none(bt["net_ann"], 4),
        "avg_turnover": _round_or_none(bt["avg_turnover"], 3),
        "verdict": verdict,
    }


# ─────────────────────────────────────────────────────────────
# 3. 主流程
# ─────────────────────────────────────────────────────────────

def run() -> dict:
    print("=" * 80)
    print("OOS regime 切片检验  (Issue #47)")
    print("=" * 80)

    # 3.1 股票池
    pools = resolve_stock_pools()
    core_stocks, quality_stocks = pools["core"], pools["quality"]
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
    r_inst = cross_section_rank(neutralize_factor(f_inst, df_info, n_sigma=3.0))
    r_roe = cross_section_rank(neutralize_factor(f_roe, df_info, n_sigma=3.0))
    r_stack = (r_inst + r_roe) / 2
    print()

    factors: dict[str, tuple[pd.DataFrame, Direction]] = {
        "inst_flow_20d": (r_inst, "Qn_minus_Q1"),
        "roe_stability": (r_roe, "Qn_minus_Q1"),
        "stacked_50_50": (r_stack, "Qn_minus_Q1"),
    }

    # 3.4 全样本 IC 序列 + sign — 序列在切片矩阵里复用 (避免 24x compute_ic_series)
    print("[Step 3] 全样本 IC 序列 + sign 锁定")
    full_ic_series: dict[str, pd.Series] = {}
    full_sample_signs: dict[str, int] = {}
    for name, (fac, _) in factors.items():
        ic = compute_ic_series(fac, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
        full_ic_series[name] = ic
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
        results[fname] = {
            slabel: metrics_for_slice(
                fac, fwd_ret, sidx, direction,
                full_ic_series=full_ic_series[fname],
                full_sample_ic_sign=full_sample_signs[fname],
            )
            for slabel, sidx in slices
        }
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
    for v in VERDICT_ORDER:
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
