"""业绩预告 backfill 2018-2025 — 东财 stock_yjyg_em.

公告日期 = 事件 T 日, 预告类型为信号方向, 业绩变动幅度为 magnitude.
遍历每年 4 个 报告期 (0331/0630/0930/1231) × 8 yr = 32 calls.
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd

OUT_DIR = Path(__file__).parent.parent / "data" / "raw" / "events" / "earnings_preview"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ALL_PATH = OUT_DIR.parent / "_all_earnings_preview_2018_2025.parquet"


def main():
    reports = []
    for year in range(2018, 2026):
        for md in ["1231", "0930", "0630", "0331"]:
            reports.append(f"{year}{md}")

    frames = []
    for rpt in reports:
        out = OUT_DIR / f"yjyg_{rpt}.parquet"
        if out.exists():
            df = pd.read_parquet(out)
            print(f"{rpt}: cache {df.shape}")
            frames.append(df)
            continue
        t0 = time.time()
        try:
            df = ak.stock_yjyg_em(date=rpt)
            df["报告期"] = rpt
            df.to_parquet(out)
            print(f"{rpt}: {df.shape} in {time.time()-t0:.0f}s")
            frames.append(df)
        except Exception as e:
            print(f"{rpt} FAIL: {e}")
        time.sleep(0.3)

    all_df = pd.concat(frames, ignore_index=True)
    all_df.to_parquet(ALL_PATH)
    print(f"total: {all_df.shape} → {ALL_PATH}")


if __name__ == "__main__":
    main()
