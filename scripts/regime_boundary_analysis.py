"""
跨因子 Regime 边界分析 — Issue #37

把 5 个 differentiation 轨道因子的月度 IC 汇成一张面板, 叠加 HS300 宏观特征,
用于回答:
  1. 2024→2025 regime shift 的时间边界在哪个月?
  2. 是一步跳 (event-driven) 还是渐变 (decay)?
  3. 哪个宏观特征 (HS300 6M return / 实现波动率) 有领先关系?

输出:
  logs/regime_boundary/factor_panel.parquet     月度 IC 面板
  logs/regime_boundary/macro_panel.parquet      月度宏观特征
  logs/regime_boundary/lag_corr.json            滞后互相关结果
  logs/regime_boundary/regime_boundary.png      可视化图

复用方法 (季度 review):
  python scripts/regime_boundary_analysis.py --start 2023-10-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from pipeline.rx_factor_monitor import RX_REGISTRY, _to_ts  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("regime_boundary")

OUT_DIR = ROOT / "logs" / "regime_boundary"
OUT_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR = OUT_DIR / "_cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PRICE_PATH = ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet"
HS300_PATH = ROOT / "data" / "raw" / "indices" / "sh000300.parquet"

# 主分析: 五个有效或翻转的因子, 跳过稳定 dead 的 (BGFD/THCC_inst/SB)
TARGET_FACTORS = ["RIAD", "MFD", "LULR", "SRR", "MCHG"]


def get_spec(name: str):
    for s in RX_REGISTRY:
        if s.name == name:
            return s
    raise ValueError(f"factor {name} not in RX_REGISTRY")


def build_factor_wide_cached(name: str, start: str, end: str) -> pd.DataFrame:
    """构建因子宽表, 命中 cache 直接读, 否则 rebuild + 落 cache."""
    cache_path = CACHE_DIR / f"{name}_{start}_{end}.parquet"
    if cache_path.exists():
        log.info(f"[{name}] cache hit: {cache_path.name}")
        return pd.read_parquet(cache_path)

    spec = get_spec(name)
    actual_start = max(spec.earliest_start, start)
    log.info(f"[{name}] building factor wide df {actual_start} ~ {end} ...")
    wide = spec.build_fn(actual_start, end)
    if not isinstance(wide.index, pd.DatetimeIndex):
        wide.index = pd.to_datetime(wide.index)
    wide = wide.sort_index()
    wide.to_parquet(cache_path)
    log.info(f"[{name}] built shape={wide.shape}, cached → {cache_path.name}")
    return wide


def compute_monthly_ic(
    name: str,
    factor_wide: pd.DataFrame,
    price: pd.DataFrame,
    start: str,
    end: str,
) -> pd.DataFrame:
    """
    按月度聚合 IC.
      - 在每月内取若干采样点 (cadence = fwd_days // 4, 至少 5 天)
      - 每个采样点算 cross-section spearman IC
      - 月内 IC 取均值, 同时记录 n_samples / n_obs

    返回 DataFrame: index=月初, columns=[ic, n_samples, n_obs_avg]
    """
    spec = get_spec(name)
    fwd_days = spec.fwd_days
    cadence = max(spec.sample_cadence_days, fwd_days // 4)

    # 计算前向收益, 列名对齐到 ts_code
    fwd = price.shift(-fwd_days) / price - 1.0
    fwd.columns = [_to_ts(c) for c in fwd.columns]

    fac = factor_wide.loc[start:end]
    ret = fwd.loc[start:end]
    common_dates = fac.index.intersection(ret.index)

    # 月内采样 + 算 IC
    rows = []
    for month_ts, dates_in_month in pd.Series(common_dates).groupby(common_dates.to_period("M")):
        # 月内按 cadence 采样
        sample_dates = dates_in_month.iloc[::cadence]
        ic_list, n_obs_list = [], []
        for d in sample_dates:
            f_row = fac.loc[d].dropna()
            r_row = ret.loc[d].dropna()
            common = f_row.index.intersection(r_row.index)
            if len(common) < spec.min_stocks:
                continue
            if f_row[common].nunique() < 2:
                continue
            corr = f_row[common].corr(r_row[common], method="spearman")
            if pd.notna(corr):
                ic_list.append(corr)
                n_obs_list.append(len(common))

        if ic_list:
            month_start = month_ts.to_timestamp()
            rows.append({
                "month": month_start,
                "ic": float(np.mean(ic_list)),
                "n_samples": len(ic_list),
                "n_obs_avg": float(np.mean(n_obs_list)),
            })

    df = pd.DataFrame(rows).set_index("month")
    log.info(f"[{name}] monthly IC: {len(df)} months, mean IC = {df['ic'].mean():+.4f}")
    return df


def build_factor_panel(start: str, end: str, factor_names: list[str]) -> pd.DataFrame:
    """
    构造月度因子 IC 面板.
      - rows = month
      - cols = {factor}_ic_raw, {factor}_ic_eff
      - ic_eff = ic_raw * sign  (使 + = 因子按假设方向工作)
    """
    price = pd.read_parquet(PRICE_PATH)

    panels = {}
    for name in factor_names:
        try:
            wide = build_factor_wide_cached(name, start, end)
            mic = compute_monthly_ic(name, wide, price, start, end)
            panels[name] = mic
        except Exception as e:
            log.error(f"[{name}] failed: {e}")
            raise

    # 拼接
    out = pd.DataFrame()
    for name, mic in panels.items():
        spec = get_spec(name)
        out[f"{name}_ic_raw"] = mic["ic"]
        out[f"{name}_ic_eff"] = mic["ic"] * spec.sign
        out[f"{name}_n_samples"] = mic["n_samples"]

    out = out.sort_index()
    return out


def compute_aggregate_health(panel: pd.DataFrame, factor_names: list[str]) -> pd.Series:
    """
    跨因子聚合健康指数:
      - 用 ic_eff (方向已对齐, + = working)
      - 每月对当月有 IC 的因子取均值
      - 返回 0~1 之间也可以, 但用原始均值更可读
    """
    eff_cols = [f"{n}_ic_eff" for n in factor_names if f"{n}_ic_eff" in panel.columns]
    return panel[eff_cols].mean(axis=1, skipna=True).rename("aggregate_eff_ic")


def build_macro_panel(start: str, end: str, panel_index: pd.DatetimeIndex) -> pd.DataFrame:
    """
    宏观特征面板 (月频):
      - hs300_ret_6m: HS300 过去 6 月累计收益率
      - hs300_ret_3m: HS300 过去 3 月累计收益率
      - hs300_vol_60d: HS300 60 日实现波动率 (年化)
      - hs300_vol_ratio: 60d vol / 250d vol  (波动率压缩/扩张)
    """
    hs = pd.read_parquet(HS300_PATH)
    hs.index = pd.to_datetime(hs.index)
    hs = hs.sort_index()

    daily_ret = hs["close"].pct_change()
    # 月频 close (取每月最后一个交易日)
    monthly_close = hs["close"].resample("ME").last()

    monthly_ret_3m = monthly_close.pct_change(3)
    monthly_ret_6m = monthly_close.pct_change(6)

    # 60d 实现波动率 (年化), 取月末值
    vol_60d = daily_ret.rolling(60).std() * np.sqrt(252)
    vol_60d_monthly = vol_60d.resample("ME").last()

    vol_250d = daily_ret.rolling(250).std() * np.sqrt(252)
    vol_250d_monthly = vol_250d.resample("ME").last()

    macro = pd.DataFrame({
        "hs300_ret_3m": monthly_ret_3m,
        "hs300_ret_6m": monthly_ret_6m,
        "hs300_vol_60d": vol_60d_monthly,
        "hs300_vol_ratio": vol_60d_monthly / vol_250d_monthly,
    })

    # 把月末对齐到月初 (和 panel 一致)
    macro.index = macro.index.to_period("M").to_timestamp()
    macro = macro.reindex(panel_index)
    return macro


def lagged_corr(x: pd.Series, y: pd.Series, lags: list[int]) -> pd.DataFrame:
    """
    x leads y by `lag` months 的相关系数 (lag >0 表示 x 领先 y).
    返回 DataFrame: lag, pearson, n.
    """
    rows = []
    for lag in lags:
        # x 领先 lag 个月 → 比较 x.shift(lag) vs y
        x_shifted = x.shift(lag)
        joined = pd.concat([x_shifted, y], axis=1).dropna()
        if len(joined) < 4:
            rows.append({"lag": lag, "pearson": np.nan, "n": len(joined)})
            continue
        rho = joined.iloc[:, 0].corr(joined.iloc[:, 1])
        rows.append({"lag": lag, "pearson": float(rho), "n": len(joined)})
    return pd.DataFrame(rows).set_index("lag")


def find_breakpoint(agg: pd.Series) -> dict:
    """
    简易断点诊断:
      - first_negative_month: 聚合指数首次 < 0 的月份
      - first_sustained_negative: 连续 3 月 < 0 的起点 (确认 shift 不是噪音)
      - max_to_min_ratio: peak 月 / trough 月 落差
    """
    s = agg.dropna()
    if len(s) == 0:
        return {}
    first_neg = s[s < 0].index.min() if (s < 0).any() else None
    # 滚动 3 月均值首次 < 0
    roll3 = s.rolling(3).mean()
    sustained = roll3[roll3 < 0].index.min() if (roll3 < 0).any() else None

    return {
        "first_negative_month": str(first_neg.date()) if first_neg is not None else None,
        "first_sustained_negative_month": str(sustained.date()) if sustained is not None else None,
        "peak_month": str(s.idxmax().date()),
        "peak_value": float(s.max()),
        "trough_month": str(s.idxmin().date()),
        "trough_value": float(s.min()),
        "delta": float(s.max() - s.min()),
    }


def make_chart(
    panel: pd.DataFrame,
    agg: pd.Series,
    macro: pd.DataFrame,
    factor_names: list[str],
    out_path: Path,
):
    """三联图: (1) 因子 IC 网格 (2) 聚合健康 + HS300 6M ret (3) 滞后相关条形图."""
    fig, axes = plt.subplots(2, 1, figsize=(14, 9), sharex=True,
                              gridspec_kw={"height_ratios": [1.4, 1]})

    # ========== 顶部: 各因子 ic_eff ==========
    ax1 = axes[0]
    colors = plt.cm.tab10.colors
    for i, name in enumerate(factor_names):
        col = f"{name}_ic_eff"
        if col not in panel.columns:
            continue
        ax1.plot(panel.index, panel[col], marker="o", markersize=3,
                 linewidth=1.0, alpha=0.55, color=colors[i], label=name)
    ax1.axhline(0, color="black", linewidth=0.4, linestyle="--", alpha=0.5)
    ax1.axvline(pd.Timestamp("2024-09-24"), color="red", linewidth=1.0,
                linestyle=":", alpha=0.7, label="9·24 政策")
    ax1.set_ylabel("Effective IC (+ = factor working)")
    ax1.set_title("Per-factor monthly effective IC (sign-aligned)")
    ax1.legend(loc="upper right", ncol=3, fontsize=8)
    ax1.grid(True, alpha=0.25)

    # ========== 底部: 聚合健康 + HS300 6M return (双轴) ==========
    ax2 = axes[1]
    ax2.plot(agg.index, agg.values, marker="s", markersize=4,
             linewidth=2.0, color="black", label="Aggregate factor health")
    ax2.fill_between(agg.index, 0, agg.values,
                     where=(agg.values > 0), alpha=0.15, color="green")
    ax2.fill_between(agg.index, 0, agg.values,
                     where=(agg.values < 0), alpha=0.15, color="red")
    ax2.axhline(0, color="black", linewidth=0.4, linestyle="--", alpha=0.5)
    ax2.axvline(pd.Timestamp("2024-09-24"), color="red", linewidth=1.0,
                linestyle=":", alpha=0.7)
    ax2.set_ylabel("Aggregate effective IC", color="black")
    ax2.set_xlabel("Month")
    ax2.legend(loc="upper left", fontsize=9)
    ax2.grid(True, alpha=0.25)

    ax2b = ax2.twinx()
    if "hs300_ret_6m" in macro.columns:
        ax2b.plot(macro.index, macro["hs300_ret_6m"] * 100, marker="^",
                  markersize=3, linewidth=1.2, color="navy", alpha=0.7,
                  label="HS300 6M return (%)")
        ax2b.set_ylabel("HS300 6M return (%)", color="navy")
        ax2b.tick_params(axis="y", labelcolor="navy")
        ax2b.legend(loc="upper right", fontsize=9)

    # X 轴格式
    ax2.xaxis.set_major_locator(mdates.MonthLocator(interval=3))
    ax2.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.setp(ax2.xaxis.get_majorticklabels(), rotation=30, ha="right")

    plt.tight_layout()
    plt.savefig(out_path, dpi=130, bbox_inches="tight")
    log.info(f"chart saved → {out_path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2023-10-01")
    ap.add_argument("--end", default="2025-12-31")
    ap.add_argument("--factors", default=",".join(TARGET_FACTORS),
                    help="逗号分隔的因子名 (来自 RX_REGISTRY)")
    args = ap.parse_args()

    factor_names = [s.strip() for s in args.factors.split(",")]
    log.info(f"Factors: {factor_names}, period {args.start} ~ {args.end}")

    # 1. 因子月度 IC 面板
    panel = build_factor_panel(args.start, args.end, factor_names)
    panel_path = OUT_DIR / "factor_panel.parquet"
    panel.to_parquet(panel_path)
    log.info(f"factor panel → {panel_path}, shape={panel.shape}")

    # 2. 聚合健康
    agg = compute_aggregate_health(panel, factor_names)
    agg.to_frame().to_parquet(OUT_DIR / "aggregate_health.parquet")

    # 3. 宏观特征
    macro = build_macro_panel(args.start, args.end, panel.index)
    macro.to_parquet(OUT_DIR / "macro_panel.parquet")
    log.info(f"macro panel → shape={macro.shape}")

    # 4. 滞后互相关
    lags = list(range(-3, 4))
    lag_results = {}
    for col in macro.columns:
        lc = lagged_corr(macro[col], agg, lags)
        lag_results[col] = lc.to_dict(orient="index")
    with open(OUT_DIR / "lag_corr.json", "w") as f:
        json.dump(lag_results, f, indent=2, default=str)

    # 5. 断点诊断
    bp = find_breakpoint(agg)
    with open(OUT_DIR / "breakpoint.json", "w") as f:
        json.dump(bp, f, indent=2)

    # 6. 可视化
    make_chart(panel, agg, macro, factor_names, OUT_DIR / "regime_boundary.png")

    # 7. 控制台摘要
    print("\n========== 结果摘要 ==========")
    print(f"\n[Aggregate health 时间序列]")
    print(agg.round(4).to_string())
    print(f"\n[断点诊断]")
    for k, v in bp.items():
        print(f"  {k}: {v}")
    print(f"\n[滞后相关 (macro leads agg by k months)]")
    for col, lc in lag_results.items():
        best_lag = max(lc.items(), key=lambda kv: abs(kv[1]["pearson"]) if kv[1]["pearson"] is not None else 0)
        print(f"  {col}: best lag={best_lag[0]} pearson={best_lag[1]['pearson']:+.3f} (n={best_lag[1]['n']})")


if __name__ == "__main__":
    main()
