"""分红方案 backfill 2018-2025 — 东财 stock_fhps_em.

date 参数是 报告期 (YYYYMMDD). 遍历年报 (1231) + 中报 (0630) 足以覆盖全部
主动分红预案. 每年 ~3000 行, 8 年 ~24000 行.
"""
from __future__ import annotations

import time
from pathlib import Path

import akshare as ak
import pandas as pd

OUT_DIR = Path(__file__).parent.parent / "data" / "raw" / "events" / "dividend"
OUT_DIR.mkdir(parents=True, exist_ok=True)
ALL_PATH = OUT_DIR.parent / "_all_dividend_2018_2025.parquet"


def main():
    reports = []
    for year in range(2018, 2026):
        for md in ["1231", "0630"]:  # 年报 + 中报
            reports.append(f"{year}{md}")

    frames = []
    for rpt in reports:
        out = OUT_DIR / f"fhps_{rpt}.parquet"
        if out.exists():
            df = pd.read_parquet(out)
            print(f"{rpt}: cache {df.shape}")
            frames.append(df)
            continue
        t0 = time.time()
        try:
            df = ak.stock_fhps_em(date=rpt)
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
