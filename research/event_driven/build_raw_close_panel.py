"""从 daily_basic/ 的 close 列构建 raw close panel.

大宗交易 block_price 是未复权真实成交价, 用 tushare daily_basic.close
(也是 raw close) 直接对齐. 分红除权在短窗口内 (21 day) 影响很小.

输出: data/processed/raw_close_panel.parquet (date × symbol)
"""
from __future__ import annotations
import logging
from pathlib import Path

import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

DAILY_BASIC_DIR = Path("data/raw/tushare/daily_basic")
OUT_PATH = Path("data/processed/raw_close_panel.parquet")


def main():
    files = sorted(DAILY_BASIC_DIR.glob("*.parquet"))
    logger.info(f"loading {len(files)} daily_basic files")

    frames = []
    for i, f in enumerate(files):
        if i % 500 == 0:
            logger.info(f"  {i}/{len(files)}")
        try:
            df = pd.read_parquet(f, columns=["ts_code", "trade_date", "close"])
        except Exception as e:
            logger.warning(f"  skip {f.name}: {e}")
            continue
        frames.append(df)

    df = pd.concat(frames, ignore_index=True)
    logger.info(f"total rows: {len(df):,}")
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df["symbol"] = df["ts_code"].str.split(".").str[0]
    df = df.dropna(subset=["close"])

    wide = df.pivot_table(index="trade_date", columns="symbol", values="close", aggfunc="last")
    wide = wide.sort_index()
    logger.info(f"wide shape: {wide.shape}")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    wide.to_parquet(OUT_PATH)
    logger.info(f"saved → {OUT_PATH} ({OUT_PATH.stat().st_size / 1024**2:.1f} MB)")


if __name__ == "__main__":
    main()
