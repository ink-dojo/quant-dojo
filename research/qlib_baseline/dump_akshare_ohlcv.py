"""
#52 — akshare OHLCV → qlib bin (扩 baseline 到 2024 含完整 regime)

输出: /Volumes/Crucial X10/quant-dojo-data/qlib_bin/cn_data_akshare_ohlc/
universe: csi300 PIT-correct (来自 tushare index_weight_399300, 共 657 只历史成分)
adjust: qfq (前复权), period: daily

Alpha158 需要 open/high/low/close/volume/amount/factor (factor=1 since qfq) 七个 features.

成本估算:
    657 只 × ~12 年 × 250 日/年 ≈ 200 万 row, akshare 每只 ~1-2s,
    串行 ~20 分钟; 失败重试 ~30 分钟封顶. 增量缓存到 SSD parquet, 失败可继续.

跑法:
    # 调试: 5 只
    python research/qlib_baseline/dump_akshare_ohlcv.py --smoke

    # 全量 (后台跑):
    nohup python research/qlib_baseline/dump_akshare_ohlcv.py > /tmp/akshare_ohlcv.log 2>&1 &

    # 增量恢复 (已下的跳过):
    python research/qlib_baseline/dump_akshare_ohlcv.py --resume
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
OUT_DIR = SSD_ROOT / "qlib_bin" / "cn_data_akshare_ohlc"
PARQUET_CACHE = SSD_ROOT / "akshare_ohlcv_cache"  # 增量缓存
TUSHARE_CACHE = PROJECT_ROOT / "data" / "raw" / "tushare"

START_DATE = "20140101"
END_DATE = "20241231"
ADJUST = "qfq"

FEATURE_MAP = {
    "开盘": "open",
    "收盘": "close",
    "最高": "high",
    "最低": "low",
    "成交量": "volume",
    "成交额": "amount",
}


def _check_ssd_mounted():
    assert SSD_ROOT.exists(), f"SSD 没挂上 ({SSD_ROOT})"


def csi300_historical_symbols() -> list[str]:
    """从 tushare index_weight 拿 CSI300 全部曾入选的股票 (657 只)."""
    df = pd.read_parquet(TUSHARE_CACHE / "index_weight_399300.parquet")
    return sorted(set(df["con_code"].str.split(".").str[0]))


def csi300_pit_ranges() -> dict[str, list[tuple[pd.Timestamp, pd.Timestamp]]]:
    """复用 dump_tushare_close 同样的 PIT 区间逻辑."""
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


def fetch_one(symbol: str, retries: int = 6, throttle_s: float = 3.0) -> pd.DataFrame | None:
    import akshare as ak
    cache_path = PARQUET_CACHE / f"{symbol}.parquet"
    if cache_path.exists():
        try:
            return pd.read_parquet(cache_path)
        except Exception:
            cache_path.unlink()
    PARQUET_CACHE.mkdir(parents=True, exist_ok=True)
    time.sleep(throttle_s)  # 限流, 每 call 之间 sleep 避免 akshare 拒连
    for attempt in range(retries):
        try:
            df = ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=START_DATE, end_date=END_DATE, adjust=ADJUST,
                timeout=15,
            )
            if df is None or df.empty:
                return None
            df["日期"] = pd.to_datetime(df["日期"])
            df = df.set_index("日期").sort_index()
            df.to_parquet(cache_path)
            return df
        except Exception as e:
            if attempt == retries - 1:
                print(f"  [skip {symbol}] {e}")
                return None
            # 指数退避: 1s, 2s, 4s, 8s
            time.sleep(2 ** attempt)
    return None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true",
                        help="跳过 OUT_DIR/features 已存在的股票")
    parser.add_argument("--from-cache-only", action="store_true",
                        help="不调 akshare, 只从已有 SSD parquet cache 写 bin (akshare 限流时使用)")
    args = parser.parse_args()

    _check_ssd_mounted()
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    PARQUET_CACHE.mkdir(parents=True, exist_ok=True)

    if args.smoke:
        symbols = ["600000", "600519", "000001", "000002", "300750"]
    else:
        symbols = csi300_historical_symbols()
    if args.limit:
        symbols = symbols[: args.limit]
    print(f"[symbols] {len(symbols)} 只 (smoke={args.smoke}, resume={args.resume})")

    # Resume: 跳过 SSD parquet cache 已有的股票 (cache 是真实下载完成标记;
    # OUT_DIR/features 大小写不可靠且会被 --from-cache-only 重写)
    if args.resume:
        cached = {p.stem for p in PARQUET_CACHE.glob("*.parquet")}
        before = len(symbols)
        symbols = [s for s in symbols if s not in cached]
        print(f"[resume] {before - len(symbols)} 只已 cache, {len(symbols)} 只待下", flush=True)

    if args.from_cache_only:
        print("[1/3] loading panels from SSD cache only (akshare 不调)")
        panels: dict[str, pd.DataFrame] = {}
        for sym in symbols:
            cache_path = PARQUET_CACHE / f"{sym}.parquet"
            if cache_path.exists():
                try:
                    panels[sym] = pd.read_parquet(cache_path)
                except Exception:
                    pass
        print(f"   loaded {len(panels)}/{len(symbols)} from cache")
    else:
        print("[1/3] fetching OHLCV...", flush=True)
        panels: dict[str, pd.DataFrame] = {}
        t0 = time.time()
        for i, sym in enumerate(symbols):
            if i % 50 == 0 and i > 0:
                elapsed = time.time() - t0
                eta = elapsed * (len(symbols) - i) / i
                print(f"   {i}/{len(symbols)} ({elapsed:.0f}s, ETA {eta:.0f}s)", flush=True)
            df = fetch_one(sym)
            if df is not None and not df.empty:
                panels[sym] = df
        print(f"   loaded {len(panels)}/{len(symbols)} ({time.time()-t0:.0f}s)", flush=True)

    if not panels:
        print("没下到数据, 退出")
        return

    print("[2/3] building calendar + writing features...")
    all_dates = sorted(set().union(*(df.index for df in panels.values())))
    calendar = pd.DatetimeIndex(all_dates)
    write_calendar(OUT_DIR, calendar)
    print(f"   calendar: {calendar[0].date()} ~ {calendar[-1].date()} ({len(calendar)} days)")

    t0 = time.time()
    for i, (sym, df) in enumerate(panels.items()):
        if i % 100 == 0 and i > 0:
            print(f"   {i}/{len(panels)} ({time.time()-t0:.0f}s)")
        qsym = to_qlib_symbol(sym)
        for cn, en in FEATURE_MAP.items():
            if cn not in df.columns:
                continue
            write_feature(OUT_DIR, qsym, en, df[cn].astype(np.float32), calendar)
        # qlib factor convention: qfq adjusted prices → factor 始终 = 1
        write_feature(
            OUT_DIR, qsym, "factor",
            pd.Series(1.0, index=df.index, dtype=np.float32),
            calendar,
        )
    print(f"   wrote {len(panels)} symbols × 7 features ({time.time()-t0:.0f}s)")

    print("[3/3] writing csi300 PIT instruments...")
    if args.smoke:
        write_instruments(OUT_DIR, "smoke_test", {
            to_qlib_symbol(s): [(panels[s].index.min(), panels[s].index.max())]
            for s in panels
        })
    else:
        members = csi300_pit_ranges()
        # 过滤掉本次没下到的股票
        downloaded_qsyms = {to_qlib_symbol(s) for s in panels}
        members_filtered = {k: v for k, v in members.items() if k in downloaded_qsyms}
        write_instruments(OUT_DIR, "csi300", members_filtered)
        print(f"   csi300 PIT universe: {len(members_filtered)} symbols")

    # 验证读回
    print("\n[verify] reading back 1 symbol close + open...")
    sample_sym_orig = list(panels.keys())[0]
    sample_qsym = to_qlib_symbol(sample_sym_orig)
    for feat_cn, feat_en in [("收盘", "close"), ("开盘", "open")]:
        orig = panels[sample_sym_orig][feat_cn].astype(np.float32).dropna()
        read = read_feature(OUT_DIR, sample_qsym, feat_en, calendar).dropna()
        common = orig.index.intersection(read.index)
        diff = (orig[common] - read[common]).abs().max()
        print(f"   {sample_qsym}.{feat_en}: orig {len(orig)}, read {len(read)}, max diff {diff:.6e}")
        assert diff < 1e-3, f"{feat_en} 读回不一致"

    print(f"\n✓ done. output: {OUT_DIR}")


if __name__ == "__main__":
    main()
