"""股东增减持 backfill — 东财 stock_ggcg_em.

事件 T = 公告日, 增减方向 = 持股变动信息-增减 (增持/减持).
信号 = 持股变动信息-占总股本比例 (%).

data/raw/events/_all_ggcg_2018_2025.parquet 落盘一次, 后续过滤在 strategy 层.
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd

OUT = Path(__file__).parent.parent / "data" / "raw" / "events" / "_all_ggcg_2018_2025.parquet"


def main():
    t0 = time.time()
    df = ak.stock_ggcg_em(symbol="全部")
    print(f"raw shape: {df.shape}  in {time.time()-t0:.0f}s")
    print(f"cols: {list(df.columns)}")

    df["公告日"] = pd.to_datetime(df["公告日"], errors="coerce")
    df = df.dropna(subset=["公告日"])
    df_full = df[(df["公告日"] >= "2018-01-01") & (df["公告日"] <= "2025-12-31")].copy()
    print(f"2018-2025 shape: {df_full.shape}")
    print(f"date range: {df_full['公告日'].min().date()} ~ {df_full['公告日'].max().date()}")
    print(f"方向分布: {df_full['持股变动信息-增减'].value_counts().to_dict()}")

    df_full.to_parquet(OUT)
    print(f"保存: {OUT}")


if __name__ == "__main__":
    main()
