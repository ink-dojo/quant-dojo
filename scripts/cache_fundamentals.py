"""
批量拉取 BaoStock 财务数据并缓存为 parquet。

生成文件：
  data/cache/roe_wide.parquet     — ROE 宽表（季度 × 股票）
  data/cache/growth_wide.parquet  — 净利润增速宽表

用法：
  python scripts/cache_fundamentals.py
"""
import sys, os, time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pandas as pd
import baostock as bs

CACHE_DIR = Path(__file__).parent.parent / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# 查询年份范围
YEARS = range(2015, 2026)
QUARTERS = [1, 2, 3, 4]


def fetch_all_financial_data():
    """批量拉取所有 A 股的 ROE 和成长数据"""
    bs.login()

    roe_records = []
    growth_records = []
    total = len(list(YEARS)) * len(QUARTERS)
    done = 0

    for year in YEARS:
        for quarter in QUARTERS:
            done += 1
            date_label = f"{year}Q{quarter}"

            # ROE
            try:
                rs = bs.query_profit_data(code="", year=year, quarter=quarter)
                while rs.error_code == "0" and rs.next():
                    row = rs.get_row_data()
                    code = row[0].split(".")[-1] if "." in row[0] else row[0]
                    try:
                        roe = float(row[3]) if row[3] else None
                    except (ValueError, IndexError):
                        roe = None
                    if roe is not None:
                        roe_records.append({"date": date_label, "symbol": code, "roe": roe})
            except Exception:
                pass

            # 成长
            try:
                rs = bs.query_growth_data(code="", year=year, quarter=quarter)
                while rs.error_code == "0" and rs.next():
                    row = rs.get_row_data()
                    code = row[0].split(".")[-1] if "." in row[0] else row[0]
                    try:
                        yoy_ni = float(row[4]) if row[4] else None
                    except (ValueError, IndexError):
                        yoy_ni = None
                    if yoy_ni is not None:
                        growth_records.append({"date": date_label, "symbol": code, "yoy_ni": yoy_ni})
            except Exception:
                pass

            print(f"  [{done}/{total}] {date_label}: ROE {len(roe_records)} 条, Growth {len(growth_records)} 条",
                  flush=True)

    bs.logout()

    # 转宽表
    if roe_records:
        df = pd.DataFrame(roe_records)
        roe_wide = df.pivot_table(index="date", columns="symbol", values="roe")
        roe_wide.to_parquet(CACHE_DIR / "roe_wide.parquet")
        print(f"\nROE 宽表: {roe_wide.shape}")

    if growth_records:
        df = pd.DataFrame(growth_records)
        growth_wide = df.pivot_table(index="date", columns="symbol", values="yoy_ni")
        growth_wide.to_parquet(CACHE_DIR / "growth_wide.parquet")
        print(f"Growth 宽表: {growth_wide.shape}")


if __name__ == "__main__":
    print("批量拉取 BaoStock 财务数据...\n")
    t0 = time.time()
    fetch_all_financial_data()
    print(f"\n完成! 耗时 {time.time()-t0:.0f}s")
