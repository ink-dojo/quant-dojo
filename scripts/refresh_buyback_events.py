"""每日刷新 `data/raw/events/_all_buyback.parquet` (DSR #30 paper-trade 核心依赖).

Tushare 的 `repurchase` 端点需要高积分, 120 积分账号无权限. 改用 akshare
`stock_repurchase_em` (东方财富 免费, 无需 token), schema 与原 parquet 完全一致.

从 2005-06-16 ~ 今全量抓取 (akshare 不支持增量), 覆盖老文件. 实际每次拉取约 60 秒
(~5000 行, 东财返回整页). 幂等; 失败不破坏旧 parquet (先写 .tmp 再 rename).

被 `scripts/paper_trade_cron.sh` 在 step 1 后调用.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

import akshare as ak
import pandas as pd

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent
OUT_PATH = PROJECT_ROOT / "data" / "raw" / "events" / "_all_buyback.parquet"


def refresh() -> dict:
    t0 = time.time()
    logger.info("拉取 akshare stock_repurchase_em ...")
    df = ak.stock_repurchase_em()
    logger.info(f"raw shape: {df.shape}, 耗时 {time.time()-t0:.1f}s")
    # schema 断言 — 若 akshare 改字段, 及时报警
    required = {
        "股票代码", "股票简称", "回购起始时间", "实施进度",
        "占公告前一日总股本比例-上限", "最新公告日期",
    }
    missing = required - set(df.columns)
    if missing:
        raise RuntimeError(f"akshare schema 变更, 缺失字段: {missing}")
    # 转日期
    df["回购起始时间"] = pd.to_datetime(df["回购起始时间"], errors="coerce")
    df["最新公告日期"] = pd.to_datetime(df["最新公告日期"], errors="coerce")

    # 写入 — atomic (先 .tmp 再 rename)
    tmp_path = OUT_PATH.with_suffix(".parquet.tmp")
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(tmp_path, index=False)
    tmp_path.replace(OUT_PATH)

    return {
        "rows": len(df),
        "date_min": str(df["回购起始时间"].min().date()) if df["回购起始时间"].notna().any() else None,
        "date_max": str(df["回购起始时间"].max().date()) if df["回购起始时间"].notna().any() else None,
        "path": str(OUT_PATH),
        "elapsed_s": round(time.time() - t0, 1),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        summary = refresh()
        print(f"✅ 刷新完成: {summary['rows']} 行 · "
              f"{summary['date_min']} ~ {summary['date_max']} · "
              f"{summary['elapsed_s']}s → {summary['path']}")
        return 0
    except Exception as e:
        print(f"❌ 失败: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
