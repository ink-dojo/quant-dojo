"""
A 股上市/退市元数据 — 修复幸存者偏差。

问题
----
原先 `get_all_symbols()` 扫本地数据目录返回**当前**所有股票，拿去做整段历史
回测 → 历史上根本还没上市 / 已经退市的股票都被算进去，导致 Sharpe 系统性高估
（幸存者偏差）。

本模块提供 `universe_at_date(d)` 返回**在日期 d 当日实际存活的**股票清单。

数据来源
--------
- 上市日期：akshare `stock_info_sh_name_code` + `stock_info_sz_name_code` +
  `stock_info_bj_name_code`（主板/科创板/创业板/北交所上市日期）
- 退市清单：akshare `stock_zh_a_stop_em`（仅给出代码，不给退市日期）
- 退市日期：akshare 未直接提供，用本地 parquet 的 `last_valid_index()` 作为
  代理（conservative：真实退市日一般晚于最后一根 K 线）

元数据缓存到 `data/raw/listing_metadata.parquet`，TTL 7 天，过期自动刷新。
"""

from __future__ import annotations

import logging
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CACHE_PATH = _PROJECT_ROOT / "data" / "raw" / "listing_metadata.parquet"
_CACHE_TTL = timedelta(days=7)


# ────────────────────────────────────────────────
# 抓取
# ────────────────────────────────────────────────

def _fetch_sh() -> pd.DataFrame:
    """抓沪市：主板 + 科创板。"""
    import akshare as ak
    frames = []
    for board in ("主板A股", "科创板"):
        try:
            df = ak.stock_info_sh_name_code(symbol=board)
            df = df.rename(columns={
                "证券代码": "symbol",
                "证券简称": "name",
                "上市日期": "list_date",
            })
            df["exchange"] = "SH"
            df["board"] = board
            frames.append(df[["symbol", "name", "list_date", "exchange", "board"]])
        except Exception as exc:
            logger.warning("akshare SH %s 抓取失败: %s", board, exc)
    if not frames:
        return pd.DataFrame(columns=["symbol", "name", "list_date", "exchange", "board"])
    return pd.concat(frames, ignore_index=True)


def _fetch_sz() -> pd.DataFrame:
    """抓深市：A 股列表（主板 / 创业板）。"""
    import akshare as ak
    try:
        df = ak.stock_info_sz_name_code(symbol="A股列表")
        df = df.rename(columns={
            "A股代码": "symbol",
            "A股简称": "name",
            "A股上市日期": "list_date",
            "板块": "board",
        })
        df["exchange"] = "SZ"
        return df[["symbol", "name", "list_date", "exchange", "board"]]
    except Exception as exc:
        logger.warning("akshare SZ 抓取失败: %s", exc)
        return pd.DataFrame(columns=["symbol", "name", "list_date", "exchange", "board"])


def _fetch_bj() -> pd.DataFrame:
    """抓北交所。"""
    import akshare as ak
    try:
        df = ak.stock_info_bj_name_code()
        # 字段可能为 证券代码 / 证券简称 / 上市日期 或变体
        col_map = {}
        for col in df.columns:
            if "代码" in col:
                col_map[col] = "symbol"
            elif "简称" in col:
                col_map[col] = "name"
            elif "上市日期" in col or "挂牌日期" in col:
                col_map[col] = "list_date"
        df = df.rename(columns=col_map)
        if "symbol" not in df.columns or "list_date" not in df.columns:
            logger.warning("BJ 字段映射失败，跳过")
            return pd.DataFrame(columns=["symbol", "name", "list_date", "exchange", "board"])
        df["exchange"] = "BJ"
        df["board"] = "北交所"
        if "name" not in df.columns:
            df["name"] = ""
        return df[["symbol", "name", "list_date", "exchange", "board"]]
    except Exception as exc:
        logger.warning("akshare BJ 抓取失败: %s", exc)
        return pd.DataFrame(columns=["symbol", "name", "list_date", "exchange", "board"])


def _fetch_delisted() -> set[str]:
    """当前已退市股票代码集合（6 位）。"""
    import akshare as ak
    try:
        df = ak.stock_zh_a_stop_em()
        codes = df["代码"].astype(str).str.zfill(6).tolist()
        return set(codes)
    except Exception as exc:
        logger.warning("akshare 退市清单抓取失败: %s", exc)
        return set()


def _fetch_from_akshare() -> pd.DataFrame:
    warnings.filterwarnings("ignore")
    parts = [_fetch_sh(), _fetch_sz(), _fetch_bj()]
    meta = pd.concat(parts, ignore_index=True)
    meta["symbol"] = meta["symbol"].astype(str).str.zfill(6)
    meta["list_date"] = pd.to_datetime(meta["list_date"], errors="coerce")
    meta = meta.dropna(subset=["list_date"])
    meta = meta.drop_duplicates(subset=["symbol"], keep="first")

    delisted = _fetch_delisted()
    meta["is_delisted"] = meta["symbol"].isin(delisted)
    meta["delist_date"] = pd.NaT

    return meta.sort_values("symbol").reset_index(drop=True)


def _infer_delist_dates(meta: pd.DataFrame) -> pd.DataFrame:
    """对 is_delisted=True 的股票用本地 parquet 的 last_valid_index 推断退市日期。"""
    try:
        from utils.local_data_loader import load_local_stock
    except Exception as exc:
        logger.warning("无法 import local_data_loader，跳过退市日期推断: %s", exc)
        return meta

    delisted_idx = meta.index[meta["is_delisted"]]
    for idx in delisted_idx:
        sym = meta.at[idx, "symbol"]
        try:
            df = load_local_stock(sym)
            if not df.empty:
                meta.at[idx, "delist_date"] = df.index.max()
        except FileNotFoundError:
            pass
        except Exception as exc:
            logger.debug("推断 %s 退市日期失败: %s", sym, exc)
    return meta


def _merge_local_only_symbols(meta: pd.DataFrame) -> pd.DataFrame:
    """本地有 parquet 但 akshare 当前列表没有的股票（通常是已退市），从
    parquet 的首末日期反推 list_date / delist_date，并入 meta 并标记 is_delisted=True。

    覆盖逻辑：这些股票在 akshare 当前上市列表里已被移除 → 视为**已退市**；
    退市日用最后一根 K 线日期代理。
    """
    try:
        from utils.local_data_loader import get_all_symbols, load_local_stock
    except Exception as exc:
        logger.warning("无法枚举本地股票: %s", exc)
        return meta

    known = set(meta["symbol"].tolist())
    local = set(get_all_symbols())
    missing = sorted(local - known)
    if not missing:
        return meta

    logger.info("补齐 %d 只本地独有（疑似退市）股票的元数据...", len(missing))
    new_rows = []
    for sym in missing:
        try:
            df = load_local_stock(sym)
            if df.empty:
                continue
            new_rows.append({
                "symbol": sym,
                "name": "",
                "list_date": df.index.min(),
                "exchange": "SH" if sym.startswith(("6", "9")) else "SZ" if sym.startswith(("0", "3")) else "BJ",
                "board": "local_inferred",
                "is_delisted": True,
                "delist_date": df.index.max(),
            })
        except Exception as exc:
            logger.debug("推断 %s 首末日期失败: %s", sym, exc)

    if new_rows:
        extra = pd.DataFrame(new_rows)
        extra["list_date"] = pd.to_datetime(extra["list_date"])
        extra["delist_date"] = pd.to_datetime(extra["delist_date"])
        meta = pd.concat([meta, extra], ignore_index=True)
        meta = meta.drop_duplicates(subset=["symbol"], keep="first")
        meta = meta.sort_values("symbol").reset_index(drop=True)
    return meta


# ────────────────────────────────────────────────
# 缓存
# ────────────────────────────────────────────────

def refresh_listing_metadata(force: bool = False) -> pd.DataFrame:
    """抓 akshare → 推断退市日期 → 写 parquet 缓存 → 返回 DataFrame。"""
    if _CACHE_PATH.exists() and not force:
        mtime = datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
        if datetime.now() - mtime < _CACHE_TTL:
            logger.debug("使用缓存: %s", _CACHE_PATH)
            return pd.read_parquet(_CACHE_PATH)

    logger.info("抓取 akshare 上市元数据（全量）...")
    meta = _fetch_from_akshare()
    meta = _infer_delist_dates(meta)
    meta = _merge_local_only_symbols(meta)

    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    meta.to_parquet(_CACHE_PATH, index=False)
    logger.info(
        "已缓存 %d 只股票上市元数据（退市 %d 只）到 %s",
        len(meta), int(meta["is_delisted"].sum()), _CACHE_PATH,
    )
    return meta


def load_listing_metadata() -> pd.DataFrame:
    """读缓存；不存在则抓取。"""
    if not _CACHE_PATH.exists():
        return refresh_listing_metadata()
    return pd.read_parquet(_CACHE_PATH)


# ────────────────────────────────────────────────
# 公共 API
# ────────────────────────────────────────────────

def universe_at_date(
    date: str | pd.Timestamp,
    require_local_data: bool = True,
) -> list[str]:
    """返回在 date 当日**已上市且尚未退市**的 A 股代码列表。

    Args:
        date: 目标日期（'YYYY-MM-DD' 或 Timestamp）
        require_local_data: True 时仅返回 data/cache/local/ 中有数据的股票
            （默认，否则下游 load_price_wide 会大量 WARN）

    Returns:
        6 位代码列表，已排序

    筛选条件:
        list_date <= date
        AND (is_delisted = False OR delist_date IS NULL OR delist_date > date)
        AND (require_local_data 时) symbol 在本地数据目录中存在

    注意:
        delist_date 为 NaT 的退市股票会被排除（保守：宁可漏算，不可错算）
    """
    d = pd.Timestamp(date)
    meta = load_listing_metadata()

    mask_listed = meta["list_date"].notna() & (meta["list_date"] <= d)
    # 存活条件：未退市 OR 退市日期晚于 d
    mask_alive = (~meta["is_delisted"]) | (
        meta["delist_date"].notna() & (meta["delist_date"] > d)
    )
    symbols = set(meta.loc[mask_listed & mask_alive, "symbol"].tolist())

    if require_local_data:
        try:
            from utils.local_data_loader import get_all_symbols
            local = set(get_all_symbols())
            symbols = symbols & local
        except Exception as exc:
            logger.warning("本地 symbol 交集失败，返回全量 akshare 结果: %s", exc)

    return sorted(symbols)


def universe_alive_during(
    start: str | pd.Timestamp,
    end: str | pd.Timestamp,
    require_local_data: bool = True,
) -> list[str]:
    """返回在 [start, end] 区间**任一时刻存活过**的股票并集。

    用于回测启动时一次性 load_price_wide：必须覆盖整个区间内可能被选中的所有股票，
    逐日 rebalance 时再用 universe_at_date(rebalance_date) 过滤。

    筛选条件：
        list_date <= end
        AND (is_delisted = False OR delist_date IS NULL OR delist_date > start)
    """
    s = pd.Timestamp(start)
    e = pd.Timestamp(end)
    meta = load_listing_metadata()

    mask_listed_by_end = meta["list_date"].notna() & (meta["list_date"] <= e)
    mask_alive_at_start = (~meta["is_delisted"]) | (
        meta["delist_date"].notna() & (meta["delist_date"] > s)
    )
    symbols = set(meta.loc[mask_listed_by_end & mask_alive_at_start, "symbol"].tolist())

    if require_local_data:
        try:
            from utils.local_data_loader import get_all_symbols
            local = set(get_all_symbols())
            symbols = symbols & local
        except Exception as exc:
            logger.warning("本地 symbol 交集失败: %s", exc)

    return sorted(symbols)


def metadata_summary() -> dict:
    """返回当前缓存的元数据摘要（给 dashboard/CLI 展示用）。"""
    if not _CACHE_PATH.exists():
        return {"status": "no_cache", "path": str(_CACHE_PATH)}
    meta = load_listing_metadata()
    mtime = datetime.fromtimestamp(_CACHE_PATH.stat().st_mtime)
    return {
        "status": "ok",
        "path": str(_CACHE_PATH),
        "updated_at": mtime.isoformat(),
        "age_days": (datetime.now() - mtime).days,
        "total": len(meta),
        "listed_alive": int((~meta["is_delisted"]).sum()),
        "delisted_with_date": int(meta["is_delisted"].sum() & meta["delist_date"].notna().sum()),
        "delisted_without_date": int(
            meta["is_delisted"].sum() - (meta["is_delisted"] & meta["delist_date"].notna()).sum()
        ),
        "earliest_list_date": str(meta["list_date"].min().date()) if len(meta) else None,
        "latest_list_date": str(meta["list_date"].max().date()) if len(meta) else None,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    print("刷新上市元数据...")
    meta = refresh_listing_metadata(force=True)
    print(f"共 {len(meta)} 只股票，退市 {int(meta['is_delisted'].sum())} 只")
    print()
    print("Summary:", metadata_summary())
    print()
    for d in ("2010-01-04", "2015-06-30", "2020-03-20", "2026-04-14"):
        u = universe_at_date(d, require_local_data=False)
        local_u = universe_at_date(d, require_local_data=True)
        print(f"  {d}: 全市场 {len(u):>5d}  本地可用 {len(local_u):>5d}")
