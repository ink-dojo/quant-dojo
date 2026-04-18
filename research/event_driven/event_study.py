"""
PEAD 描述性 event study — 预注册 spec 前的 sanity check.

目标:
  - 对 2018-2025 A 股财报事件, 按 net_profit_yoy 分 quintile
  - 画平均 abnormal return 路径 T-5 ~ T+30
  - 看是否有可观察的 drift (正 surprise vs 负 surprise)

这一步 **不用于 tune 参数**, 只用于判断 PEAD 现象是否在数据里存在.
如果 top - bottom spread 肉眼看不到 → 策略跑了也 FAIL, 但仍按预注册执行.

用法:
    python -m research.event_driven.event_study
输出:
    research/event_driven/event_study_plot.png
    stdout: quintile × relative-day 平均 abn return 表
"""
from __future__ import annotations

import logging
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from utils.local_data_loader import load_adj_price_wide

logger = logging.getLogger(__name__)

EVENTS_PARQUET = Path(__file__).parent.parent.parent / "data" / "raw" / "events" / "_all_events_2018_2025.parquet"
PLOT_PATH = Path(__file__).parent / "event_study_plot.png"

PRE_DAYS = 5
POST_DAYS = 30
N_QUINTILES = 5


def compute_abn_returns(
    events: pd.DataFrame, prices: pd.DataFrame
) -> pd.DataFrame:
    """
    对每个事件, 计算 T-5 ~ T+30 相对日的个股收益 - 同日市场等权均值 (简单 market-adj).

    返回 long DataFrame:
        event_id, symbol, announce_date, surprise, rel_day, abn_ret
    """
    daily_ret = prices.pct_change().where(lambda x: x.abs() < 0.25)
    mkt = daily_ret.mean(axis=1)  # 等权市场收益
    abn = daily_ret.sub(mkt, axis=0)  # 超额收益 (简化)

    td = daily_ret.index
    td_arr = td.values
    rows = []

    for _, e in events.dropna(subset=["announce_date", "net_profit_yoy"]).iterrows():
        sym = e["symbol"]
        if sym not in abn.columns:
            continue
        ad = np.datetime64(e["announce_date"])
        i0 = int(np.searchsorted(td_arr, ad, side="left"))
        if i0 < PRE_DAYS or i0 + POST_DAYS >= len(td_arr):
            continue

        for rd in range(-PRE_DAYS, POST_DAYS + 1):
            idx = i0 + rd
            val = abn.iloc[idx][sym]
            if pd.isna(val):
                continue
            rows.append({
                "symbol": sym,
                "announce_date": pd.Timestamp(e["announce_date"]),
                "surprise": float(e["net_profit_yoy"]),
                "rel_day": rd,
                "abn_ret": float(val),
            })

    return pd.DataFrame(rows)


def plot_event_study(long_df: pd.DataFrame) -> pd.DataFrame:
    """按 surprise quintile 分组, 画累计 abn return 曲线. 返回 pivot 表."""
    # 每个事件的 surprise 做 cross-sectional rank (同一季度事件内分组, 避免时间偏差)
    # 简化: 全样本分 quintile 亦可; 这里用 full-sample quintile
    long_df["quintile"] = pd.qcut(
        long_df.groupby(["symbol", "announce_date"])["surprise"].transform("first"),
        N_QUINTILES,
        labels=[f"Q{i}" for i in range(1, N_QUINTILES + 1)],
        duplicates="drop",
    )

    # 每个事件每个 rel_day 一行 → 先对 event 平均不需要, rel_day 级别聚合
    agg = long_df.groupby(["quintile", "rel_day"], observed=True)["abn_ret"].mean().unstack("quintile")
    cum = agg.cumsum()

    plt.figure(figsize=(10, 6))
    for q in cum.columns:
        plt.plot(cum.index, cum[q] * 100, label=str(q), linewidth=1.8)
    plt.axvline(0, color="k", linestyle="--", alpha=0.5, label="announce_day")
    plt.axhline(0, color="gray", linewidth=0.5)
    plt.xlabel("Relative trading day (0 = announce_date)")
    plt.ylabel("Cumulative abnormal return (%)")
    plt.title("PEAD event study — A股 2018-2025, 按净利润 YoY 分 quintile")
    plt.legend(title="Surprise quintile")
    plt.grid(alpha=0.3)
    plt.tight_layout()
    plt.savefig(PLOT_PATH, dpi=120)
    logger.info(f"图保存: {PLOT_PATH}")

    # 打印关键区间的 spread
    print("\n=== Q5 (top surprise) - Q1 (bottom) 累计 abn return ===")
    q_top = cum[cum.columns[-1]]
    q_bot = cum[cum.columns[0]]
    spread = q_top - q_bot
    for d in [-5, 0, 1, 5, 10, 20, 30]:
        if d in spread.index:
            print(f"  rel_day={d:+d}: {spread.loc[d]*100:.2f}%")

    return cum


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    events = pd.read_parquet(EVENTS_PARQUET)
    events["announce_date"] = pd.to_datetime(events["announce_date"])
    logger.info(f"events: {len(events)} 行, {events['symbol'].nunique()} symbols")

    universe = sorted(events["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(
        universe,
        start=str(events["announce_date"].min().date()),
        end=str((events["announce_date"].max() + pd.Timedelta(days=45)).date()),
    )
    logger.info(f"prices: {prices.shape}")

    long_df = compute_abn_returns(events, prices)
    logger.info(f"abn returns long: {len(long_df)} 行")

    cum = plot_event_study(long_df)
    print("\n=== 各 quintile 在 T+20 累计 abn return ===")
    if 20 in cum.index:
        print(cum.loc[20].apply(lambda x: f"{x*100:.2f}%"))


if __name__ == "__main__":
    main()
