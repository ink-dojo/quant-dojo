"""
RX factor monitor — 为 '差异化因子探索轨道' (Issue #33/#35/#36) 的 6+ 因子做周期性监控

和 pipeline/factor_monitor.py (legacy v7/v16 snapshot-based) 的区别:
    - legacy 从 live/factor_snapshot/*.parquet 加载每日快照
    - RX 在调用时实时重算每个因子 (build-from-tushare), 因为:
        * RIAD 需要 ths/dc/stk_surv 融合
        * BGFD 是月频, MFD/LULR 是 event-based
        * THCC 是季频 (发布延迟敏感)
      没有"每日 snapshot"统一接口

输出格式兼容 factor_health_report (status: healthy/degraded/dead/insufficient_data/no_data),
方便未来集成 weekly_report.

使用:
    from pipeline.rx_factor_monitor import rx_factor_health_report
    report = rx_factor_health_report(window_days=120)
    # {"RIAD_LS_Q2Q3_minus_Q5": {"rolling_ic": -0.04, "sharpe": 0.5, ...}}

门槛:
    |IC| > 0.03 → healthy
    |IC| ∈ [0.02, 0.03] 且 |HAC t| ≥ 2 → degraded (仍可考虑)
    |IC| < 0.02 且 |HAC t| < 2 → dead
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"

IC_HEALTHY_THRESH = 0.03
IC_DEGRADED_THRESH = 0.02
HAC_T_THRESH = 2.0
MIN_OBS_FOR_VERDICT = 12  # 至少 12 个月频样本 (或 12 个采样点) 才下结论


def _to_ts(sym: str) -> str:
    if sym.startswith(("60", "68")):
        return f"{sym}.SH"
    if sym.startswith(("00", "30")):
        return f"{sym}.SZ"
    return f"{sym}.SZ"


@dataclass
class FactorSpec:
    """注册一个 RX 因子."""
    name: str                                   # 唯一名称, e.g. "RIAD_Q2Q3_minus_Q5"
    display: str                                # 人类可读描述
    build_fn: Callable[[str, str], pd.DataFrame]  # (start, end) -> wide factor df
    sign: int = -1                              # -1 表示"值越小越看好", +1 反之 (用于 IC 归一化 sanity)
    fwd_days: int = 20                          # 前向收益窗口
    sample_cadence_days: int = 5                # 评估采样间隔 (防 IC 强相关)
    earliest_start: str = "2023-10-01"          # 数据起点 (RIAD 受 stk_surv 限制)
    neutralize: bool = True                     # 是否 size+ind 中性化
    notes: str = ""
    tags: list[str] = field(default_factory=list)


def _newey_west_t(x: np.ndarray, lag: int = 4) -> float:
    """Newey-West HAC t-stat for mean.

    Sanity:
        - NW correction 可能让 s2 人为 collapse 到几乎 0, 造成虚假巨大 t.
          floor s2 不小于 gamma0 * 0.25 (防 correction 过度).
        - 若 |t| > 100, 返回 NaN (小样本下数字不可信).
    """
    n = len(x)
    if n < 4:
        return float("nan")
    mu = x.mean()
    e = x - mu
    gamma0 = float((e ** 2).mean())
    if gamma0 <= 0:
        return float("nan")
    s2 = gamma0
    for h in range(1, min(lag, n - 1) + 1):
        gamma = float((e[h:] * e[:-h]).mean())
        w = 1.0 - h / (lag + 1.0)
        s2 += 2.0 * w * gamma
    # floor: NW 不得 collapse 原方差 > 75%
    s2 = max(s2, gamma0 * 0.25)
    se = np.sqrt(s2 / n)
    if se <= 0:
        return float("nan")
    t = float(mu / se)
    if abs(t) > 100.0:  # 小样本极端值, 不可信
        return float("nan")
    return t


def compute_factor_ic_summary(
    factor_wide: pd.DataFrame,
    price: pd.DataFrame,
    start: str,
    end: str,
    fwd_days: int = 20,
    sample_cadence: int = 5,
    min_stocks: int = 30,
) -> dict:
    """
    在指定区间上计算因子的 IC summary.

    price: wide df with ts_code columns (6-digit → ts_code mapping already applied).
    min_stocks: 每日截面最少股票数 (事件 factor 可降到 3-5).
    """
    # 对齐价格 columns 到 ts_code
    fwd = price.shift(-fwd_days) / price - 1.0
    fwd.columns = [_to_ts(c) for c in fwd.columns]

    fac = factor_wide.loc[start:end]
    ret = fwd.loc[start:end]
    dates = fac.index.intersection(ret.index)
    if len(dates) == 0:
        return {"ic_mean": np.nan, "icir": np.nan, "t_hac": np.nan, "n_obs": 0, "status": "no_data"}

    sample_dates = dates[::sample_cadence]
    ic_list = []
    for d in sample_dates:
        f_row = fac.loc[d].dropna()
        r_row = ret.loc[d].dropna()
        common = f_row.index.intersection(r_row.index)
        if len(common) < min_stocks:
            continue
        # 事件 factor 在同一截面可能所有 value 相同, 跳过 constant
        if f_row[common].nunique() < 2:
            continue
        corr = f_row[common].corr(r_row[common], method="spearman")
        if pd.notna(corr):
            ic_list.append(corr)

    arr = np.array(ic_list)
    if len(arr) < 3:
        return {"ic_mean": np.nan, "icir": np.nan, "t_hac": np.nan, "n_obs": len(arr), "status": "no_data"}

    mu = float(arr.mean())
    sd = float(arr.std(ddof=1))
    icir = mu / sd if sd > 0 else np.nan
    t_hac = _newey_west_t(arr, lag=4)

    # 判读 status
    abs_ic = abs(mu)
    if len(arr) < MIN_OBS_FOR_VERDICT:
        status = "insufficient_data"
    elif abs_ic >= IC_HEALTHY_THRESH:
        status = "healthy"
    elif abs_ic >= IC_DEGRADED_THRESH and abs(t_hac) >= HAC_T_THRESH:
        status = "degraded"
    elif abs_ic < IC_DEGRADED_THRESH and abs(t_hac) < HAC_T_THRESH:
        status = "dead"
    else:
        status = "degraded"

    return {
        "ic_mean": mu,
        "ic_std": sd,
        "icir": float(icir) if not np.isnan(icir) else None,
        "t_hac": t_hac,
        "n_obs": len(arr),
        "status": status,
    }


def rx_factor_health_report(
    registry: list[FactorSpec] | None = None,
    window_days: int = 252,
    end_date: str | None = None,
) -> dict:
    """
    对 registry 里每个因子算最近 window_days 窗口的 IC summary.

    end_date: None → 用 price_wide 最新日; 否则传 YYYY-MM-DD.
    """
    if registry is None:
        registry = RX_REGISTRY
    price = pd.read_parquet(PRICE_PATH)
    if end_date is None:
        end_date = str(price.index.max().date())

    # 计算 window 起点
    end_ts = pd.Timestamp(end_date)
    start_ts = end_ts - pd.Timedelta(days=int(window_days * 1.4))  # 留出非交易日余量
    start_date = str(start_ts.date())

    report = {}
    for spec in registry:
        # 取 earliest_start 和 window start 中更晚的
        effective_start = max(start_date, spec.earliest_start)
        try:
            fw = spec.build_fn(effective_start, end_date)
        except Exception as e:
            log.warning("factor %s build failed: %s", spec.name, e)
            report[spec.name] = {
                "display": spec.display,
                "rolling_ic": np.nan, "icir": np.nan, "t_hac": np.nan,
                "n_obs": 0, "status": "no_data", "error": str(e),
            }
            continue

        if fw is None or fw.empty:
            report[spec.name] = {
                "display": spec.display,
                "rolling_ic": np.nan, "icir": np.nan, "t_hac": np.nan,
                "n_obs": 0, "status": "no_data",
            }
            continue

        summary = compute_factor_ic_summary(
            fw, price, effective_start, end_date,
            fwd_days=spec.fwd_days,
            sample_cadence=spec.sample_cadence_days,
        )
        report[spec.name] = {
            "display": spec.display,
            "rolling_ic": summary["ic_mean"],
            "icir": summary["icir"],
            "t_hac": summary["t_hac"],
            "n_obs": summary["n_obs"],
            "status": summary["status"],
            "earliest_start": effective_start,
            "end_date": end_date,
            "fwd_days": spec.fwd_days,
            "sign": spec.sign,
            "notes": spec.notes,
            "tags": spec.tags,
        }
    return report


# ─────────────────────────────────────────────────────────────────────
# Factor registry — 每个因子 build_fn 返回 wide DataFrame
#   index=trade_date, columns=ts_code (with .SZ/.SH/.BJ), values=factor value
# ─────────────────────────────────────────────────────────────────────

def _build_riad(start: str, end: str) -> pd.DataFrame:
    from research.factors.retail_inst_divergence.factor import (
        build_attention_panel, compute_riad_factor,
    )
    from research.factors.retail_inst_divergence.industry_eval import load_industry_series
    from research.factors.retail_inst_divergence.neutralize_eval import (
        load_circ_mv_wide, size_neutralize,
    )
    from utils.factor_analysis import industry_neutralize_fast

    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[start:end].index
    panels = build_attention_panel(start, end, cal)
    raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    circ_mv = load_circ_mv_wide(start, end)
    sn = size_neutralize(raw, circ_mv)
    ind = load_industry_series()
    return industry_neutralize_fast(sn, ind)


def _build_mfd(start: str, end: str) -> pd.DataFrame:
    from research.factors.moneyflow_divergence.factor import compute_mfd_factor
    # 让前面 20 日 warm-up
    effective_start = (pd.Timestamp(start) - pd.Timedelta(days=60)).strftime("%Y-%m-%d")
    return compute_mfd_factor(effective_start, end, window=20, min_coverage=500)


def _build_bgfd_daily(start: str, end: str) -> pd.DataFrame:
    """BGFD 原本月频, 这里按"最近月份 ffill 到日"返回."""
    from research.factors.broker_gold_fade.factor import (
        compute_bgfd_factor, compute_consensus_streak, load_broker_recommend,
    )
    sm = pd.Timestamp(start).strftime("%Y-%m")
    em = pd.Timestamp(end).strftime("%Y-%m")
    raw = load_broker_recommend(sm, em)
    if raw.empty:
        return pd.DataFrame()
    cons = compute_consensus_streak(raw)
    months = sorted(cons["month_i"].unique())
    wide_monthly = compute_bgfd_factor(cons, months)
    if wide_monthly.empty:
        return pd.DataFrame()
    # ffill 到日
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[start:end].index
    rows = []
    for d in cal:
        ym = d.year * 100 + d.month
        valid = [m for m in wide_monthly.index if m <= ym]
        if valid:
            rows.append(wide_monthly.loc[max(valid)].rename(d))
        else:
            rows.append(pd.Series(dtype=float, name=d))
    return pd.DataFrame(rows)


def _build_lulr_daily(start: str, end: str) -> pd.DataFrame:
    from research.factors.limit_up_ladder.factor import compute_lulr_factor, load_limit_list
    long = load_limit_list(start, end)
    if long.empty:
        return pd.DataFrame()
    return compute_lulr_factor(long)


def _build_thcc_daily(start: str, end: str) -> pd.DataFrame:
    from research.factors.top_holder_concentration.evaluate_thcc import ffill_with_staleness
    from research.factors.top_holder_concentration.factor import (
        compute_thcc_factors, load_top10_float,
    )
    sy = int(start[:4]) - 1
    ey = int(end[:4])
    raw = load_top10_float(sy, ey)
    if raw.empty:
        return pd.DataFrame()
    wide_event = compute_thcc_factors(raw)["thcc_inst"]
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[start:end].index
    return ffill_with_staleness(wide_event, cal)


def _build_sb(start: str, end: str) -> pd.DataFrame:
    from research.factors.survey_burst.factor import compute_sb_factor, load_survey_counts
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[start:end].index
    long = load_survey_counts(start, end)
    if long.empty:
        return pd.DataFrame()
    return compute_sb_factor(long, cal)


RX_REGISTRY: list[FactorSpec] = [
    FactorSpec(
        name="RIAD",
        display="散户-机构关注度背离 (size+ind neutral)",
        build_fn=_build_riad,
        sign=-1,
        fwd_days=20,
        earliest_start="2023-10-01",
        tags=["attention", "retail"],
        notes="Q2Q3-Q5 LS, 样本 2023-10 起",
    ),
    FactorSpec(
        name="MFD",
        display="超大单-小单资金流背离 (反转)",
        build_fn=_build_mfd,
        sign=-1,
        fwd_days=20,
        earliest_start="2020-06-01",
        tags=["moneyflow", "reversal"],
        notes="IC 反向 (派发伪 smart money)",
    ),
    FactorSpec(
        name="BGFD",
        display="券商金股共识度 (follow consensus)",
        build_fn=_build_bgfd_daily,
        sign=+1,
        fwd_days=20,
        earliest_start="2020-03-01",
        tags=["analyst", "sentiment"],
        notes="原 fade 假设被证伪, 反向 follow 有效",
    ),
    FactorSpec(
        name="LULR",
        display="连板反转 (高位涨停 → T+5 反转)",
        build_fn=_build_lulr_daily,
        sign=-1,
        fwd_days=5,
        sample_cadence_days=2,
        earliest_start="2019-01-01",
        tags=["event", "limit_up"],
        notes="小 universe (每日~100), 2024+ 有效",
    ),
    FactorSpec(
        name="THCC_inst",
        display="前十大流通股东机构口径环比 (反向)",
        build_fn=_build_thcc_daily,
        sign=-1,
        fwd_days=20,
        earliest_start="2018-06-01",
        tags=["ownership", "institutional"],
        notes="反向: 机构加仓反而 bearish (window-dressing)",
    ),
    FactorSpec(
        name="SB",
        display="机构调研 burst (7d / 91d median)",
        build_fn=_build_sb,
        sign=+1,
        fwd_days=20,
        earliest_start="2024-01-01",
        tags=["attention", "event"],
        notes="null effect, 短期 spike 无 alpha",
    ),
]


if __name__ == "__main__":
    print("=== RX factor health report (window_days=252) ===\n")
    report = rx_factor_health_report(window_days=252)
    for name, r in report.items():
        ic = r["rolling_ic"]
        icir = r["icir"]
        t = r["t_hac"]
        print(
            f"[{r['status']:<18}] {name:<12} "
            f"IC={(f'{ic:+.4f}' if pd.notna(ic) else 'n/a'):<9} "
            f"ICIR={(f'{icir:+.3f}' if icir is not None else 'n/a'):<8} "
            f"HAC t={(f'{t:+.2f}' if pd.notna(t) else 'n/a'):<7} "
            f"n={r['n_obs']:<4} "
            f"| {r['display']}"
        )
