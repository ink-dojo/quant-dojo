"""
#53 — tushare daily_basic.close + adj_factor → qlib bin (project-controlled 数据基线)

输出: /Volumes/Crucial X10/quant-dojo-data/qlib_bin/cn_data_tushare_close/
覆盖: tushare 缓存里所有股票 (~5277 只), 区间由各股票 daily_basic 自身决定.
universe: csi300 PIT-correct (来自 tushare index_weight_399300)

只产出 close-only feature; 想跑 Alpha158 全特征请用 #52 的 akshare OHLCV 或 qlib 官方 cn_data.

跑法:
    python research/qlib_baseline/dump_tushare_close.py [--limit N] [--smoke]

    --limit N   只处理前 N 只股票 (调试用)
    --smoke     5 只股票 + 验证读回一致, 不写 universe / 全量
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from research.qlib_baseline.qlib_bin_writer import (  # noqa: E402
    read_feature,
    to_qlib_symbol,
    write_calendar,
    write_feature,
    write_instruments,
)

SSD_ROOT = Path("/Volumes/Crucial X10/quant-dojo-data")
OUT_DIR = SSD_ROOT / "qlib_bin" / "cn_data_tushare_close"
TUSHARE_CACHE = PROJECT_ROOT / "data" / "raw" / "tushare"


def _check_ssd_mounted():
    assert SSD_ROOT.exists(), (
        f"SSD 没挂上 ({SSD_ROOT}); 数据规则禁止写本地, 先挂 SSD"
    )


def load_csi300_pit_universe() -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    """从 tushare index_weight_399300 推导 CSI300 PIT-correct universe.

    每只股票存在多个 [start, end] 区间 (被踢出又回来时); 单 trade_date 行存在 = 那天在 universe.
    简化: 把每只股票的 trade_date 集合 → 连续区间合并 (允许 ≤ 90 天 gap 视为同一区间).
    """
    df = pd.read_parquet(TUSHARE_CACHE / "index_weight_399300.parquet")
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")
    df = df.sort_values(["con_code", "trade_date"])

    members = {}
    for con_code, group in df.groupby("con_code"):
        sym = to_qlib_symbol(con_code.split(".")[0])
        dates = group["trade_date"].sort_values()
        ranges = []
        cur_start = dates.iloc[0]
        prev = dates.iloc[0]
        for d in dates.iloc[1:]:
            if (d - prev).days > 90:
                ranges.append((cur_start, prev))
                cur_start = d
            prev = d
        ranges.append((cur_start, prev))
        members[sym] = ranges
    return members


def load_close_with_factor(symbol: str) -> pd.Series:
    """读 tushare daily_basic.close 与 adj_factor 拼前复权 close."""
    db_path = TUSHARE_CACHE / "daily_basic" / f"{symbol}.parquet"
    af_path = TUSHARE_CACHE / "adj_factor" / f"{symbol}.parquet"
    if not db_path.exists():
        return pd.Series(dtype=np.float32)

    db = pd.read_parquet(db_path)
    db["trade_date"] = pd.to_datetime(db["trade_date"], format="%Y%m%d")
    db = db.set_index("trade_date").sort_index()

    if af_path.exists():
        af = pd.read_parquet(af_path)
        af["trade_date"] = pd.to_datetime(af["trade_date"], format="%Y%m%d")
        af = af.set_index("trade_date").sort_index()
        # 前复权: close * adj_factor / latest_adj_factor
        latest = float(af["adj_factor"].iloc[-1])
        adj = af["adj_factor"].reindex(db.index).ffill().bfill()
        close_adj = db["close"] * adj / latest
    else:
        close_adj = db["close"]

    return close_adj.astype(np.float32).rename("close")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--smoke", action="store_true")
    args = parser.parse_args()

    _check_ssd_mounted()
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        symbols = ["000001", "000002", "600000", "600519", "300750"]
        print(f"[smoke] {len(symbols)} 只股票")
    else:
        symbols = sorted(p.stem for p in (TUSHARE_CACHE / "daily_basic").glob("*.parquet"))
        if args.limit:
            symbols = symbols[: args.limit]
        print(f"[full] tushare daily_basic 共 {len(symbols)} 只 (limit={args.limit})")

    # 1. 读全部 close 拼 panel 推 calendar (所有股票交易日的并集)
    print("[1/4] loading close panels...")
    panels = {}
    t0 = time.time()
    for i, sym in enumerate(symbols):
        if i % 500 == 0 and i > 0:
            print(f"   {i}/{len(symbols)} ({time.time()-t0:.0f}s)")
        s = load_close_with_factor(sym)
        if len(s) > 0:
            panels[sym] = s
    print(f"   loaded {len(panels)}/{len(symbols)} ({time.time()-t0:.0f}s)")

    print("[2/4] building calendar...")
    all_dates = sorted(set().union(*(s.index for s in panels.values())))
    calendar = pd.DatetimeIndex(all_dates)
    write_calendar(OUT_DIR, calendar)
    print(f"   calendar: {calendar[0].date()} ~ {calendar[-1].date()} ({len(calendar)} days)")

    print("[3/4] writing close.day.bin per symbol...")
    t0 = time.time()
    for i, (sym, s) in enumerate(panels.items()):
        if i % 500 == 0 and i > 0:
            print(f"   {i}/{len(panels)} ({time.time()-t0:.0f}s)")
        qsym = to_qlib_symbol(sym)
        write_feature(OUT_DIR, qsym, "close", s, calendar)
    print(f"   wrote {len(panels)} symbols ({time.time()-t0:.0f}s)")

    print("[4/4] writing csi300 PIT instruments...")
    if args.smoke:
        # smoke 模式不需要 universe (没有数据), 用空文件占位 + 验证读回
        write_instruments(OUT_DIR, "smoke_test", {
            to_qlib_symbol(s): [(panels[s].index.min(), panels[s].index.max())]
            for s in panels
        })
    else:
        members = load_csi300_pit_universe()
        # 过滤掉 panel 里没有的 sym (delisted 或缓存未覆盖)
        members_filtered = {k: v for k, v in members.items() if k.lower() in
                            (qs.lower() for qs in (to_qlib_symbol(s) for s in panels))}
        write_instruments(OUT_DIR, "csi300", members_filtered)
        print(f"   csi300 PIT universe: {len(members_filtered)} symbols")

    # 验证读回 (smoke 必做)
    print("\n[verify] reading back 1 symbol...")
    sample_sym = to_qlib_symbol(list(panels.keys())[0])
    sample_orig = panels[list(panels.keys())[0]].dropna()
    sample_read = read_feature(OUT_DIR, sample_sym, "close", calendar).dropna()
    common_idx = sample_orig.index.intersection(sample_read.index)
    diff = (sample_orig[common_idx] - sample_read[common_idx]).abs().max()
    print(f"   {sample_sym}: orig {len(sample_orig)}, read {len(sample_read)}, max abs diff = {diff:.6e}")
    assert diff < 1e-3, "读回与源数据差异过大"
    print(f"\n✓ done. output: {OUT_DIR}")


if __name__ == "__main__":
    main()
