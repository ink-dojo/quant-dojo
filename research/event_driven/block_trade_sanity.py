"""大宗交易折价因子 — 快速 IC sanity check.

目的: 先验证假设方向, 再决定是否全量 backtest.

### 假设 (pre-registered)
H1: discount_rate = (close - block_price) / close 与未来 21 日收益率负相关
    (折价越大 → 卖方急 → 后续跑输)
H2: buyer == "机构专用" 与未来 21 日收益率正相关
    (机构接盘 → 有信息 → 后续跑赢)
H3: -discount × institutional = 最强 alpha

### 方法
事件层面 (每笔 block trade) 算 discount + fwd 21d return,
cross-sectional rank IC (Spearman).

### 输出
- IC by hypothesis (H1/H2/H3)
- IC by buyer type (机构 vs 游资)
- IC by year (decay check)
- IC by holding window (5/21/60 day)
"""
from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

EVENTS_DIR = Path("data/raw/tushare/events")
# raw close panel built from daily_basic (same basis as block_price)
PRICE_PATH = Path("data/processed/raw_close_panel.parquet")
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")

# 统一 symbol 格式: block_trade 用 "000001.SZ", price_wide 用 "000001"
def ts_to_symbol(ts_code: str) -> str:
    return ts_code.split(".")[0]


def load_all_block_trades(start: str = "2015-02-01", end: str = "2025-12-31") -> pd.DataFrame:
    files = sorted(EVENTS_DIR.glob("block_trade_*.parquet"))
    dfs = []
    for f in files:
        yyyymm = f.stem.split("_")[-1]
        if yyyymm < start[:4] + start[5:7] or yyyymm > end[:4] + end[5:7]:
            continue
        dfs.append(pd.read_parquet(f))
    df = pd.concat(dfs, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["trade_date", "price", "amount", "ts_code"])
    df["symbol"] = df["ts_code"].apply(ts_to_symbol)
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
    # 过滤极端坏数据
    df = df[(df["price"] > 0) & (df["amount"] > 0) & (df["vol"] > 0)]
    df["is_institutional_buyer"] = (df["buyer"] == "机构专用").astype(int)
    df["is_institutional_seller"] = (df["seller"] == "机构专用").astype(int)
    logger.info(f"block trades loaded: {len(df):,} events")
    return df


def attach_price_and_fwd_returns(events: pd.DataFrame, px: pd.DataFrame,
                                   windows: list[int] = [5, 21, 60]) -> pd.DataFrame:
    """对每笔事件, 附加当日 close + fwd N 日收益率."""
    px = px.copy()
    px.index = pd.to_datetime(px.index)
    events = events.copy()
    events["trade_date"] = pd.to_datetime(events["trade_date"])

    # 对齐交易日: trade_date 若非交易日, 用 <=trade_date 的最近交易日
    trading_days = px.index.values
    td_arr = np.asarray(trading_days)

    def find_idx(d):
        i = np.searchsorted(td_arr, np.datetime64(d), side="right") - 1
        return i if i >= 0 else -1

    events["td_idx"] = events["trade_date"].apply(find_idx)
    events = events[events["td_idx"] >= 0].reset_index(drop=True)

    # 逐行拿 close + fwd — 向量化
    syms = events["symbol"].values
    tdi = events["td_idx"].values
    close_today = np.full(len(events), np.nan)
    for i, (s, ti) in enumerate(zip(syms, tdi)):
        if s in px.columns:
            close_today[i] = px.iloc[ti][s]
    events["close"] = close_today

    # 去掉 close 缺失
    events = events.dropna(subset=["close"]).reset_index(drop=True)

    # 折价率: 正值 = 折价 (block 低于市价)
    events["discount_rate"] = (events["close"] - events["price"]) / events["close"]

    # fwd returns
    syms = events["symbol"].values
    tdi = events["td_idx"].values
    close_t = events["close"].values
    n_td = len(td_arr)
    for w in windows:
        fwd = np.full(len(events), np.nan)
        for i, (s, ti) in enumerate(zip(syms, tdi)):
            if s not in px.columns:
                continue
            # 用 T+1 开始, T+w close 作为退出价格 (signal shift avoid look-ahead)
            i_open = ti + 1
            i_close = ti + 1 + w
            if i_close >= n_td:
                continue
            p_open = px.iloc[i_open][s]
            p_close = px.iloc[i_close][s]
            if pd.notna(p_open) and pd.notna(p_close) and p_open > 0:
                fwd[i] = p_close / p_open - 1
        events[f"fwd_{w}d"] = fwd
    return events


def rank_ic(x: np.ndarray, y: np.ndarray) -> tuple[float, float, int]:
    mask = ~(np.isnan(x) | np.isnan(y))
    if mask.sum() < 30:
        return np.nan, np.nan, int(mask.sum())
    rho, pval = spearmanr(x[mask], y[mask])
    return rho, pval, int(mask.sum())


def main():
    logger.info("loading price panel")
    px = pd.read_parquet(PRICE_PATH)
    logger.info(f"px shape: {px.shape}")

    logger.info("loading block trades")
    events = load_all_block_trades()

    logger.info("attaching prices + fwd returns")
    events = attach_price_and_fwd_returns(events, px)
    logger.info(f"events after price merge: {len(events):,}")

    # 大宗交易法规允许折价幅度: 交易所规定最大 30% 折价, 实际观测 -20% ~ +10%
    # 超过 |30%| 基本是数据噪音 (停牌/除权日附近)
    events = events[events["discount_rate"].abs() < 0.30].reset_index(drop=True)
    logger.info(f"events after outlier trim: {len(events):,}")

    # 按月份 groupby cross-sectionally 算 IC (避免 pooled time-series bias)
    events["month"] = events["trade_date"].dt.to_period("M")

    print("\n=== H1: discount_rate vs fwd return (event-level, pooled) ===")
    for w in [5, 21, 60]:
        rho, p, n = rank_ic(events["discount_rate"].values, events[f"fwd_{w}d"].values)
        print(f"  fwd_{w:2d}d  rho={rho:+.4f}  p={p:.3e}  n={n:,}")

    print("\n=== H2: institutional_buyer vs fwd return ===")
    for w in [5, 21, 60]:
        rho, p, n = rank_ic(events["is_institutional_buyer"].values.astype(float),
                             events[f"fwd_{w}d"].values)
        print(f"  fwd_{w:2d}d  rho={rho:+.4f}  p={p:.3e}  n={n:,}")

    print("\n=== H3: composite -discount + institutional ===")
    events["composite"] = -events["discount_rate"] + 0.05 * events["is_institutional_buyer"]
    for w in [5, 21, 60]:
        rho, p, n = rank_ic(events["composite"].values, events[f"fwd_{w}d"].values)
        print(f"  fwd_{w:2d}d  rho={rho:+.4f}  p={p:.3e}  n={n:,}")

    print("\n=== Split: institutional buyer vs 游资 (fwd_21d) ===")
    for label, mask in [("机构接盘 (buyer=机构专用)", events["is_institutional_buyer"] == 1),
                         ("非机构接盘 (游资/营业部)", events["is_institutional_buyer"] == 0)]:
        sub = events[mask]
        rho, p, n = rank_ic(sub["discount_rate"].values, sub["fwd_21d"].values)
        mean_fwd = sub["fwd_21d"].mean()
        print(f"  {label:28s}  n={n:,}  mean_fwd_21d={mean_fwd:+.4f}  IC={rho:+.4f}  p={p:.3e}")

    print("\n=== Year-by-year IC (discount vs fwd_21d) [decay check] ===")
    events["year"] = events["trade_date"].dt.year
    for yr in sorted(events["year"].unique()):
        sub = events[events["year"] == yr]
        rho, p, n = rank_ic(sub["discount_rate"].values, sub["fwd_21d"].values)
        print(f"  {yr}  n={n:6,}  IC={rho:+.4f}  p={p:.3e}")

    # Monthly cross-section IC (classic IR)
    print("\n=== Monthly cross-sectional IC (fwd_21d) ===")
    mics = []
    for m, grp in events.groupby("month"):
        if len(grp) < 30:
            continue
        rho, p, n = rank_ic(grp["discount_rate"].values, grp["fwd_21d"].values)
        if not np.isnan(rho):
            mics.append(rho)
    mics = np.array(mics)
    print(f"  n months: {len(mics)}  mean IC: {mics.mean():+.4f}  std: {mics.std():.4f}  ICIR: {mics.mean()/mics.std():+.3f}")
    t_stat = mics.mean() / (mics.std() / np.sqrt(len(mics)))
    print(f"  t-stat (monthly IC mean): {t_stat:+.3f}")

    # bucket decile analysis
    print("\n=== Discount decile mean fwd_21d (pooled across all events) ===")
    events["dec"] = pd.qcut(events["discount_rate"], 10, labels=False, duplicates="drop")
    dec_stats = events.groupby("dec").agg(
        n=("discount_rate", "size"),
        mean_disc=("discount_rate", "mean"),
        mean_fwd21=("fwd_21d", "mean"),
        winrate=("fwd_21d", lambda x: (x > 0).mean()),
    )
    print(dec_stats.round(4))

    # 保存 enriched 事件表
    out = Path("research/event_driven/block_trade_events_enriched.parquet")
    events.to_parquet(out)
    logger.info(f"saved enriched events to {out}")


if __name__ == "__main__":
    main()
