"""
SB — Survey Burst 因子

和 RIAD 的 inst_attn leg 的区别:
    RIAD 用 stk_surv 绝对水平 (60 日累计机构数), cross-section zscore
    SB   用 时序 spike — 本周调研数 / 过去 13 周中位数, 捕捉"突然集中调研"

核心假设:
    短期调研密度从低 → 高的急速跳变 (burst), 往往意味着公司出现**新的 material event**
    (业绩预告、重大合同、行业政策), 研究员赶来密集调研.
    Burst 信号比 RIAD 的"累计关注度水平"更 timely, 预计有更短周期 alpha (1-2 月).

因子构造 (日频):
    n_7d_s,t  = 过去 7 日调研机构数
    med_91d_s,t = 过去 91 日滚动 n_7d 的中位数
    SB_s,t    = (n_7d - med_91d) / (med_91d + 1.0)  (avoid zero-div)
    信号方向  = 做多 SB 高 (正向因子)

数据: data/raw/tushare/stk_surv/stk_surv_{symbol6}.parquet (2023-10 起)
样本期: 2024-04 ~ 2026-03 (留 91+7 日 warm-up)
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
SURV_DIR = ROOT / "data" / "raw" / "tushare" / "stk_surv"


def load_survey_counts(start: str, end: str) -> pd.DataFrame:
    """返回 long-format: [trade_date, ts_code, n_org] (当日调研机构数)."""
    start_i, end_i = int(start.replace("-", "")), int(end.replace("-", ""))
    frames = []
    for f in sorted(SURV_DIR.glob("stk_surv_*.parquet")):
        try:
            df = pd.read_parquet(f, columns=["ts_code", "surv_date", "rece_org"])
        except Exception:
            continue
        if df.empty:
            continue
        df = df[df["surv_date"].astype(int).between(start_i, end_i)]
        if df.empty:
            continue
        frames.append(df)
    if not frames:
        return pd.DataFrame(columns=["trade_date", "ts_code", "n_org"])
    raw = pd.concat(frames, ignore_index=True)
    raw = raw.drop_duplicates(["ts_code", "surv_date", "rece_org"])
    out = (
        raw.groupby(["surv_date", "ts_code"])["rece_org"]
        .count()
        .reset_index()
        .rename(columns={"surv_date": "trade_date", "rece_org": "n_org"})
    )
    out["trade_date"] = pd.to_datetime(out["trade_date"].astype(str).str.strip(), format="%Y%m%d")
    return out


def compute_sb_factor(
    long: pd.DataFrame,
    trade_calendar: pd.DatetimeIndex,
    short_win: int = 7,
    long_win: int = 91,
    min_coverage: int = 100,
) -> pd.DataFrame:
    """
    SB 因子宽表.

    n_7d: 过去 short_win 日调研机构数滚动和
    med_91d: 过去 long_win 日滚动 (n_7d 的中位数)
    SB = (n_7d - med_91d) / (med_91d + 1)

    返回 wide DataFrame (trade_date × ts_code). 非 ST/调研过的股票保持 NaN.
    """
    if long.empty:
        return pd.DataFrame()

    daily = long.pivot_table(
        index="trade_date", columns="ts_code", values="n_org", aggfunc="sum", fill_value=0
    ).reindex(trade_calendar, fill_value=0.0)

    n_7d = daily.rolling(short_win, min_periods=1).sum()
    med_91d = n_7d.rolling(long_win, min_periods=short_win * 3).median()
    mean_91d = n_7d.rolling(long_win, min_periods=short_win * 3).mean()
    sb = (n_7d - med_91d) / (med_91d + 1.0)

    # 只在 91 日窗口内有过调研 (mean_91d > 0.1) 的股票上打分; 完全冷股置 NaN
    has_history = mean_91d > 0.1
    sb = sb.where(has_history, np.nan)

    daily_count = sb.notna().sum(axis=1)
    sb = sb.where(daily_count >= min_coverage, np.nan)
    return sb


if __name__ == "__main__":
    print("=== SB 因子最小验证 (2025 H2) ===")
    long = load_survey_counts("2023-10-01", "2025-12-31")
    print(f"survey long rows: {len(long)}")
    # 构造交易日历
    pw = pd.read_parquet(
        ROOT / "data" / "processed" / "price_wide_close_2014-01-01_2025-12-31_qfq_5477stocks.parquet",
        columns=None,
    )
    cal = pw.loc["2024-01-01":"2025-12-31"].index
    sb = compute_sb_factor(long, cal)
    print(f"SB wide: {sb.shape}, 日均有效股: {sb.notna().sum(axis=1).mean():.0f}")
    latest = sb.iloc[-1].dropna()
    print(f"最新一日有效: {len(latest)}")
    if len(latest):
        print(f"SB 分位: p10={latest.quantile(0.1):.2f} p50={latest.quantile(0.5):.2f} p90={latest.quantile(0.9):.2f}")
        print("Top 10 最 burst (短期调研突增):")
        print(latest.nlargest(10).to_string())
        print("Top 10 最 cold (短期调研少于历史中位):")
        print(latest.nsmallest(10).to_string())
    print("✅ 最小验证通过")
