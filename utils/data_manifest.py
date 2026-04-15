"""
数据 vintage / 输入指纹模块 — 可重现性保障

目的
----
每次回测/日频信号运行，把输入数据的**当时状态**拍一张指纹，存到 RunRecord 里。
两周后同一条 run_id 被复查时，能回答：
  - 当时用了哪个数据目录？
  - 文件数、总字节数是否还一样？
  - 每个文件的 (size, mtime) 是否还一样？
  - 若不一样：是哪些股票的数据被重下过？

设计取舍
--------
- **不**每次 SHA256 所有 parquet：5000 只股票 * 几十 MB = I/O 太慢
- 用 `(size, mtime_ns)` 作为"文件指纹"——任何重写/覆盖都会触发变化
- 把所有文件指纹拼起来再 SHA256，得到整个数据集的 **aggregate_sha**
- 需要完整密码学校验时，调 `compute_data_manifest(full_hash=True)` 单独触发

产出格式
--------
```
{
  "data_dir": "/Users/karan/quant-data",
  "cache_dir": "data/cache/local",
  "snapshot_at": "2026-04-14T15:30:00",
  "n_files": 5477,
  "total_bytes": 1234567890,
  "aggregate_sha": "a1b2c3...",          # (path, size, mtime) 拼串后的 SHA256
  "full_content_sha": null,              # 仅 full_hash=True 时填
  "oldest_file_mtime": "2024-01-01T00:00:00",
  "newest_file_mtime": "2026-04-14T08:00:00",
  "symbols_sampled": ["000001", ...],    # 若传入 symbols，仅统计这些
  "listing_metadata_sha": "deadbeef...", # 上市元数据缓存的哈希（universe_at_date 依据）
}
```

放在哪里
--------
- `backtest/standardized.py`: 调 `compute_data_manifest(symbols, ...)` 存进
  `BacktestResult.metrics["data_manifest"]` 或 `artifacts["data_manifest"]`
- `pipeline/daily_signal.py`: 存进 signal JSON 的 `metadata.data_manifest`
- `pipeline/run_store.py`: 无需改动（artifacts 是开放 dict）
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    """流式计算文件 SHA256（1 MB chunk）。仅 full_hash=True 时使用。"""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def _stat_fingerprint(path: Path) -> tuple[str, int, int]:
    """(相对路径, size, mtime_ns)"""
    st = path.stat()
    return (path.name, st.st_size, st.st_mtime_ns)


def _aggregate_sha(fingerprints: list[tuple[str, int, int]]) -> str:
    """对排序后的指纹列表计算聚合 SHA256。"""
    fingerprints_sorted = sorted(fingerprints)
    blob = "\n".join(f"{name}|{size}|{mtime}" for name, size, mtime in fingerprints_sorted)
    return _sha256_bytes(blob.encode())


def compute_data_manifest(
    symbols: Optional[list[str]] = None,
    include_cache: bool = True,
    include_raw_csv: bool = True,
    full_hash: bool = False,
    listing_metadata_path: Optional[Path] = None,
) -> dict:
    """
    计算数据输入的指纹快照。

    Args:
        symbols: 只统计这些股票的文件；None 表示统计全部
        include_cache: 是否包含 data/cache/local/*.parquet
        include_raw_csv: 是否包含原始 CSV 目录（~/quant-data/*.csv）
        full_hash: True 则对每个文件跑完整 SHA256（慢，仅用于审计）
        listing_metadata_path: 上市元数据 parquet 路径；None 表示自动定位

    Returns:
        dict，见模块 docstring。若无数据文件，返回 status="no_data"。
    """
    # 懒加载数据目录路径
    try:
        from utils.local_data_loader import _get_local_data_dir, _CACHE_DIR
        raw_dir = _get_local_data_dir()
        cache_dir = Path(_CACHE_DIR)
    except Exception as exc:
        logger.warning("无法解析数据目录: %s", exc)
        return {"status": "error", "error": str(exc)}

    fingerprints: list[tuple[str, int, int]] = []
    total_bytes = 0
    mtimes_ns: list[int] = []
    n_cache = 0
    n_raw = 0

    symbol_set = set(symbols) if symbols else None

    def _collect(files: list[Path], label: str):
        nonlocal total_bytes
        for p in files:
            # 过滤到指定 symbols（文件名通常是 "sh.600000.csv" 或 "600000.parquet"）
            if symbol_set is not None:
                stem = p.stem
                code = stem.split(".", 1)[1] if "." in stem else stem
                if code not in symbol_set:
                    continue
            try:
                fp = _stat_fingerprint(p)
                fingerprints.append((f"{label}/{fp[0]}", fp[1], fp[2]))
                total_bytes += fp[1]
                mtimes_ns.append(fp[2])
            except OSError as exc:
                logger.debug("stat 失败 %s: %s", p, exc)

    if include_raw_csv and raw_dir.exists():
        raw_files = sorted(raw_dir.glob("*.csv"))
        _collect(raw_files, "raw")
        n_raw = len([p for p in raw_files
                     if symbol_set is None
                     or (p.stem.split(".", 1)[1] if "." in p.stem else p.stem) in symbol_set])

    if include_cache and cache_dir.exists():
        cache_files = sorted(cache_dir.glob("*.parquet"))
        _collect(cache_files, "cache")
        n_cache = len([p for p in cache_files
                       if symbol_set is None or p.stem in symbol_set])

    if not fingerprints:
        return {
            "status": "no_data",
            "data_dir": str(raw_dir),
            "cache_dir": str(cache_dir),
            "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        }

    aggregate = _aggregate_sha(fingerprints)

    full_content_sha = None
    if full_hash:
        # 慢路径：全内容哈希。对全部文件算 SHA256 后再拼串做 merkle。
        content_hashes = []
        for name, _, _ in sorted(fingerprints):
            label, fname = name.split("/", 1)
            path = (raw_dir if label == "raw" else cache_dir) / fname
            try:
                content_hashes.append((name, _sha256_file(path)))
            except OSError as exc:
                logger.debug("full hash 失败 %s: %s", path, exc)
        blob = "\n".join(f"{n}|{h}" for n, h in content_hashes)
        full_content_sha = _sha256_bytes(blob.encode())

    # 上市元数据指纹（universe_at_date 的依据）
    listing_sha = None
    if listing_metadata_path is None:
        try:
            from utils.listing_metadata import _CACHE_PATH as _META_PATH
            listing_metadata_path = _META_PATH
        except Exception:
            listing_metadata_path = None
    if listing_metadata_path and Path(listing_metadata_path).exists():
        try:
            listing_sha = _sha256_file(Path(listing_metadata_path))
        except OSError:
            pass

    oldest_ns = min(mtimes_ns)
    newest_ns = max(mtimes_ns)

    manifest = {
        "status": "ok",
        "data_dir": str(raw_dir),
        "cache_dir": str(cache_dir),
        "snapshot_at": datetime.now().isoformat(timespec="seconds"),
        "n_files": len(fingerprints),
        "n_raw_csv": n_raw,
        "n_parquet_cache": n_cache,
        "total_bytes": total_bytes,
        "aggregate_sha": aggregate,
        "full_content_sha": full_content_sha,
        "oldest_file_mtime": datetime.fromtimestamp(oldest_ns / 1e9).isoformat(timespec="seconds"),
        "newest_file_mtime": datetime.fromtimestamp(newest_ns / 1e9).isoformat(timespec="seconds"),
        "listing_metadata_sha": listing_sha,
        "n_symbols_requested": len(symbol_set) if symbol_set else None,
    }
    return manifest


def verify_data_manifest(manifest: dict, tolerate_cache_change: bool = True) -> dict:
    """
    校验当前数据状态是否与 manifest 匹配。

    Args:
        manifest: compute_data_manifest() 的返回值
        tolerate_cache_change: 若 True，只比较 raw CSV 的聚合量（n_raw_csv/
            total_bytes 等），忽略 parquet 缓存变化（缓存从 CSV 重建无损）

    Returns:
        {"match": bool, "reason": str, "drift": {...}}
    """
    if manifest.get("status") != "ok":
        return {"match": False, "reason": "原 manifest 无效", "drift": {}}

    current = compute_data_manifest(
        include_cache=True,  # 两边都包含，保证对称比较
        include_raw_csv=True,
        full_hash=manifest.get("full_content_sha") is not None,
    )

    if current["status"] != "ok":
        return {"match": False, "reason": "当前无数据", "drift": current}

    drift = {}
    # 选择比较字段：tolerate_cache_change 时只比较 raw 侧
    if tolerate_cache_change:
        if current.get("n_raw_csv") != manifest.get("n_raw_csv"):
            drift["n_raw_csv"] = (manifest.get("n_raw_csv"), current.get("n_raw_csv"))
        # raw 层 mtime 边界
        if current.get("oldest_file_mtime") != manifest.get("oldest_file_mtime"):
            drift["oldest_file_mtime"] = (manifest["oldest_file_mtime"],
                                          current["oldest_file_mtime"])
    else:
        if current["n_files"] != manifest["n_files"]:
            drift["n_files"] = (manifest["n_files"], current["n_files"])
        if current["total_bytes"] != manifest["total_bytes"]:
            drift["total_bytes"] = (manifest["total_bytes"], current["total_bytes"])
        if current["aggregate_sha"] != manifest["aggregate_sha"]:
            drift["aggregate_sha"] = (manifest["aggregate_sha"][:16],
                                      current["aggregate_sha"][:16])

    if current.get("listing_metadata_sha") != manifest.get("listing_metadata_sha"):
        drift["listing_metadata_sha"] = (
            (manifest.get("listing_metadata_sha") or "")[:16],
            (current.get("listing_metadata_sha") or "")[:16],
        )

    return {
        "match": len(drift) == 0,
        "reason": "数据未变" if not drift else f"漂移字段: {list(drift.keys())}",
        "drift": drift,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    import time
    t0 = time.time()
    m = compute_data_manifest()
    elapsed = time.time() - t0
    print(f"=== 数据 manifest（{elapsed:.2f}s）===")
    print(json.dumps(m, indent=2, ensure_ascii=False, default=str))

    # 再跑一次验证
    t0 = time.time()
    v = verify_data_manifest(m)
    print(f"\n=== 校验（{time.time()-t0:.2f}s）===")
    print(json.dumps(v, indent=2, ensure_ascii=False))
