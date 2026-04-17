"""
数据指纹工具 — 防止 v16 可重现性事故重演（2026-04-17）。

问题背景：
  A 股 qfq 前复权序列会随最新分红/送股回溯调整历史收盘价。
  日常数据拉取改写 2022-2025 全段历史，同一策略同一代码隔几天跑
  结果会出现 0.1+ sharpe 漂移。fresh v16 (4/17) sharpe=0.676 vs
  cached v16 (4/14) sharpe=0.801，诊断显示 95% parquet 被改写。

解决方案：
  每次回测把当时的数据指纹（sha256 + mtime 统计 + universe hash）
  dump 成 json 与 equity/metrics 一起归档。未来重跑对比时，若指纹
  不同可立刻判定"非同数据"，避免静默漂移误导决策。

用法：
    from utils.data_fingerprint import compute_data_fingerprint
    fp = compute_data_fingerprint(symbols, start="2022-01-01", end="2025-12-31")
    save_json(fp, "live/runs/xxx_fingerprint.json")
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import pandas as pd


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _universe_hash(symbols: Iterable[str]) -> str:
    """对符号列表排序后哈希，保证顺序无关。"""
    sorted_syms = sorted(str(s) for s in symbols)
    joined = ",".join(sorted_syms).encode("utf-8")
    return _sha256_bytes(joined)[:16]


def _scan_parquet_dir(data_dir: Path, pattern: str = "*.parquet") -> dict:
    """扫描 parquet 目录，汇总文件数/总大小/mtime 统计。不读内容，只看元数据。"""
    files = sorted(data_dir.glob(pattern))
    if not files:
        return {"n_files": 0, "total_bytes": 0, "mtime_min": None, "mtime_max": None}
    stats = [f.stat() for f in files]
    sizes = [s.st_size for s in stats]
    mtimes = [s.st_mtime for s in stats]
    return {
        "n_files": len(files),
        "total_bytes": int(sum(sizes)),
        "mtime_min": datetime.fromtimestamp(min(mtimes), tz=timezone.utc).isoformat(),
        "mtime_max": datetime.fromtimestamp(max(mtimes), tz=timezone.utc).isoformat(),
        "mtime_median": datetime.fromtimestamp(
            sorted(mtimes)[len(mtimes) // 2], tz=timezone.utc
        ).isoformat(),
    }


def _sample_price_hash(
    symbols: Iterable[str],
    start: str,
    end: str,
    n_sample: int = 10,
    field: str = "close",
) -> dict:
    """
    对 universe 采样 n_sample 只股票，加载其收盘价并做哈希。
    同一输入在同一数据下应返回相同 hash；若 parquet 被改写则 hash 变化。
    """
    from utils.local_data_loader import load_price_wide

    sorted_syms = sorted(str(s) for s in symbols)
    if not sorted_syms:
        return {"n_sample": 0, "hash": None, "symbols": []}
    # 确定性采样：等距抽取
    step = max(1, len(sorted_syms) // n_sample)
    picked = sorted_syms[::step][:n_sample]
    try:
        wide = load_price_wide(picked, start, end, field=field)
    except Exception as e:
        return {"n_sample": len(picked), "hash": None, "symbols": picked, "error": str(e)}
    if wide.empty:
        return {"n_sample": len(picked), "hash": None, "symbols": picked, "error": "empty"}
    # 按 (symbol, date) 排序后哈希数值，避免 column 顺序影响
    wide = wide.reindex(columns=sorted(wide.columns))
    # to_bytes via deterministic serialization
    buf = wide.round(6).to_csv(index=True).encode("utf-8")
    return {
        "n_sample": len(picked),
        "hash": _sha256_bytes(buf)[:16],
        "symbols": picked,
        "n_dates": int(wide.shape[0]),
        "n_cols": int(wide.shape[1]),
    }


def compute_data_fingerprint(
    symbols: Iterable[str],
    start: str,
    end: str,
    data_dir: Optional[Path] = None,
    cache_dir: Optional[Path] = None,
    sample_price_hash: bool = True,
    n_sample: int = 10,
) -> dict:
    """
    计算数据指纹，供回测 artifact 归档。

    参数:
        symbols     : universe 符号列表
        start / end : 回测日期范围
        data_dir    : 原始数据目录（CSV/parquet 源）；None 则读 _get_local_data_dir()
        cache_dir   : parquet cache 目录（真正被回测读取的位置）；
                      None 则使用 utils.local_data_loader._CACHE_DIR
        sample_price_hash : 是否跑采样价格哈希（慢但精确）；默认 True
        n_sample    : 采样股票数

    返回:
        dict，包含:
          - timestamp_utc        : 指纹生成时间
          - universe             : {n, hash}
          - source_dir           : 原始数据目录统计
          - cache_dir            : parquet cache 目录统计（含 mtime — 最重要）
          - sample_price_hash    : 采样价格 hash（可选）
          - date_range           : {start, end}
    """
    from utils.local_data_loader import _CACHE_DIR, _get_local_data_dir

    symbols = list(symbols)
    source = data_dir if data_dir is not None else _get_local_data_dir()
    cache = cache_dir if cache_dir is not None else _CACHE_DIR

    fp = {
        "timestamp_utc": datetime.now(tz=timezone.utc).isoformat(),
        "date_range": {"start": str(start), "end": str(end)},
        "universe": {
            "n_symbols": len(symbols),
            "hash": _universe_hash(symbols),
        },
        "source_dir": {
            "path": str(source),
            "exists": Path(source).exists(),
            "stats": _scan_parquet_dir(source, pattern="*.parquet") if Path(source).exists() else {},
        },
        "cache_dir": {
            "path": str(cache),
            "exists": Path(cache).exists(),
            "stats": _scan_parquet_dir(cache, pattern="*.parquet") if Path(cache).exists() else {},
        },
    }
    if sample_price_hash:
        fp["sample_price_hash"] = _sample_price_hash(symbols, start, end, n_sample)
    return fp


def save_fingerprint(fp: dict, path: Path) -> Path:
    """保存指纹为 json。"""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(fp, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def diff_fingerprints(fp_a: dict, fp_b: dict) -> dict:
    """
    对比两份指纹，列出关键字段差异。用于"为什么同策略跑出不同 sharpe"的即时诊断。

    返回 dict，同一字段不同则填 (a_val, b_val)，相同则跳过。
    """
    out: dict = {}

    def _cmp(key_path: str, a, b):
        if a != b:
            out[key_path] = {"a": a, "b": b}

    _cmp("universe.n_symbols", fp_a["universe"]["n_symbols"], fp_b["universe"]["n_symbols"])
    _cmp("universe.hash", fp_a["universe"]["hash"], fp_b["universe"]["hash"])
    for section in ("source_dir", "cache_dir"):
        a_stats = fp_a.get(section, {}).get("stats", {})
        b_stats = fp_b.get(section, {}).get("stats", {})
        for k in ("n_files", "total_bytes", "mtime_max"):
            _cmp(f"{section}.{k}", a_stats.get(k), b_stats.get(k))
    if "sample_price_hash" in fp_a and "sample_price_hash" in fp_b:
        _cmp(
            "sample_price_hash.hash",
            fp_a["sample_price_hash"].get("hash"),
            fp_b["sample_price_hash"].get("hash"),
        )
    return out


if __name__ == "__main__":
    # 最小验证：跑一次小 universe fingerprint
    from utils.local_data_loader import get_all_symbols

    syms = get_all_symbols()[:50]
    fp = compute_data_fingerprint(
        syms, "2024-01-01", "2024-12-31", sample_price_hash=True, n_sample=5
    )
    print(json.dumps(fp, indent=2, ensure_ascii=False))
    print("\n✅ compute_data_fingerprint OK")
