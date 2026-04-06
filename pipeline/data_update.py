"""
pipeline/data_update.py — 本地数据增量更新入口

run_update() 函数：扫描本地数据目录，对每只股票调用
provider.incremental_update() 补全缺失日期的行情数据，
并以追加模式写入 CSV。

CSV 文件命名规则：{sh|sz}.{symbol}.csv
  - 上海（6 开头）: sh.600000.csv
  - 深圳（0/3 开头）: sz.000001.csv
"""

import logging
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import pandas as pd

logger = logging.getLogger(__name__)

# 中文列名 → 英文列名（覆盖多种数据源格式）
_ZH_TO_EN = {
    "日期": "date",
    "交易所行情日期": "date",
    "trade_date": "date",
    "开盘": "open",
    "开盘价": "open",
    "最高": "high",
    "最高价": "high",
    "最低": "low",
    "最低价": "low",
    "收盘": "close",
    "收盘价": "close",
    "前收盘价": "prev_close",
    "成交量": "volume",
    "成交额": "amount",
    "换手率": "turnover",
    "涨跌幅": "pct_change",
    "滚动市盈率": "pe_ttm",
    "市净率": "pb",
    "滚动市销率": "ps_ttm",
    "滚动市现率": "pcf",
    "是否ST": "is_st",
}

# 必要列（英文）
_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


def _get_csv_path(data_dir: Path, symbol: str) -> Optional[Path]:
    """
    查找股票对应的本地 CSV 文件路径（sh/sz 前缀）。

    参数:
        data_dir (Path): 本地数据目录
        symbol (str): 6 位股票代码

    返回:
        Path 或 None（文件不存在时）
    """
    data_dir = Path(data_dir) if not isinstance(data_dir, Path) else data_dir
    for prefix in ("sh", "sz"):
        p = data_dir / f"{prefix}.{symbol}.csv"
        if p.exists():
            return p
    # 宽松匹配，防止命名规则不一致
    matches = list(data_dir.glob(f"*.{symbol}.csv"))
    return matches[0] if matches else None


def _new_csv_path(data_dir: Path, symbol: str) -> Path:
    """
    为新股票生成 CSV 文件路径，根据代码推断 sh/sz 前缀。

    参数:
        data_dir (Path): 本地数据目录
        symbol (str): 6 位股票代码

    返回:
        Path 对象
    """
    prefix = "sh" if symbol.startswith("6") else "sz"
    return data_dir / f"{prefix}.{symbol}.csv"


def _read_latest_date(csv_path: Path) -> Optional[pd.Timestamp]:
    """
    读取 CSV 文件中的最新日期。

    参数:
        csv_path (Path): CSV 文件路径

    返回:
        最新日期的 Timestamp，或 None（读取失败或文件为空）
    """
    try:
        header_df = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=0)
        # 找日期列（支持多种列名）
        date_col = None
        date_candidates = {"date", "日期", "交易所行情日期", "trade_date"}
        for col in header_df.columns:
            if col in date_candidates:
                date_col = col
                break
        if date_col is None:
            logger.warning("找不到 %s 的日期列，已有列: %s", csv_path.name, list(header_df.columns))
            return None

        df = pd.read_csv(csv_path, encoding="utf-8-sig", usecols=[date_col])
        dates = pd.to_datetime(df[date_col], errors="coerce").dropna()
        return dates.max() if not dates.empty else None
    except Exception as e:
        logger.warning("读取 %s 最新日期失败: %s", csv_path, e)
        return None


def _append_rows(csv_path: Path, new_df: pd.DataFrame, is_new_file: bool) -> int:
    """
    将新行情数据写入 CSV（追加模式，绝不覆盖已有行）。

    - 新文件：写入完整 CSV（含表头），英文列名
    - 已有文件：读取现有表头，将新数据列名适配后追加（无表头行）

    参数:
        csv_path (Path): CSV 文件路径
        new_df (pd.DataFrame): 英文列名的新数据（date, open, high, low, close, volume, amount）
        is_new_file (bool): 是否为新建文件

    返回:
        int: 实际写入的行数
    """
    if new_df.empty:
        return 0

    # date 列统一格式化为 YYYY-MM-DD 字符串
    write_df = new_df.copy()
    write_df["date"] = pd.to_datetime(write_df["date"]).dt.strftime("%Y-%m-%d")

    if is_new_file:
        csv_path.parent.mkdir(parents=True, exist_ok=True)
        write_df.to_csv(csv_path, index=False, encoding="utf-8-sig")
        return len(write_df)

    # 已有文件：读取表头，适配列名后追加
    try:
        existing_cols = pd.read_csv(csv_path, encoding="utf-8-sig", nrows=0).columns.tolist()
    except Exception as e:
        logger.warning("读取 %s 表头失败，跳过追加: %s", csv_path, e)
        return 0

    # 构建 英文名 → 原始列名 的映射（支持中文列已有文件）
    en_to_orig: Dict[str, str] = {}
    for orig_col in existing_cols:
        en_name = _ZH_TO_EN.get(orig_col, orig_col)
        en_to_orig[en_name] = orig_col

    # 将新数据列名映射到原始文件的列名
    rename_map = {en: orig for en, orig in en_to_orig.items() if en in write_df.columns}
    adapted = write_df.rename(columns=rename_map)

    # 写入原文件所有列，缺失列填空值（避免行列数不匹配导致数据错位）
    cols_to_write = existing_cols
    for col in cols_to_write:
        if col not in adapted.columns:
            adapted[col] = ""

    adapted[cols_to_write].to_csv(
        csv_path, mode="a", header=False, index=False, encoding="utf-8-sig"
    )
    return len(adapted)


def _run_batch_update(
    provider, symbols: List[str], end_date: str,
    data_dir: Path, dry_run: bool
) -> Dict:
    """
    批量模式更新（Tushare 专用）。

    按日期拉取全市场数据，然后分发到各股票 CSV。
    一天的数据 = 2~3 次 API 调用，比逐只 5477 次快 1000x。
    """
    # 找到全局最新日期（所有 CSV 中的最早"最新日期"）
    latest_dates = []
    for symbol in symbols[:100]:  # 抽样检查
        csv_path = _get_csv_path(data_dir, symbol)
        if csv_path:
            ld = _read_latest_date(csv_path)
            if ld is not None:
                latest_dates.append(ld)

    if latest_dates:
        global_latest = min(latest_dates)  # 保守：取最旧的
        since_date = (global_latest + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        since_date = "2020-01-01"

    if pd.Timestamp(since_date) > pd.Timestamp(end_date):
        print(f"数据已是最新（最新日期 >= {end_date}）")
        return {"updated": [], "skipped": symbols, "failed": [], "end_date": end_date}

    print(f"批量更新: {since_date} → {end_date}")

    if dry_run:
        print(f"[DRY RUN] 将拉取 {since_date} 到 {end_date} 的全市场数据")
        return {"updated": symbols, "skipped": [], "failed": [], "end_date": end_date}

    # 拉取全市场日期范围数据
    try:
        all_data = provider.batch_daily_range(since_date, end_date)
    except Exception as e:
        logger.error("批量拉取失败: %s", e)
        return {"updated": [], "skipped": [], "failed": symbols, "end_date": end_date}

    if all_data.empty:
        print("无新数据（可能是非交易日）")
        return {"updated": [], "skipped": symbols, "failed": [], "end_date": end_date}

    print(f"拉取完成: {len(all_data)} 条记录，{all_data['symbol'].nunique()} 只股票")

    # 分发到各股票 CSV
    updated = []
    skipped = []
    failed = []
    symbol_set = set(symbols)

    for symbol, group in all_data.groupby("symbol"):
        if symbol not in symbol_set:
            continue

        csv_path = _get_csv_path(data_dir, symbol)
        is_new = csv_path is None

        # 构造写入 DataFrame（英文列名）
        write_df = group[["date", "open", "high", "low", "close", "volume", "amount"]].copy()
        for extra in ["prev_close", "turnover", "pct_change", "pe_ttm", "pb", "ps_ttm", "is_st"]:
            if extra in group.columns:
                write_df[extra] = group[extra].values

        dest = csv_path if not is_new else _new_csv_path(data_dir, symbol)
        try:
            n = _append_rows(dest, write_df, is_new_file=is_new)
            updated.append(symbol)
        except Exception as e:
            logger.warning("写入 %s 失败: %s", symbol, e)
            failed.append(symbol)

    # 清除 parquet 缓存（数据已更新）
    cache_dir = data_dir.parent / "quant-dojo" / "data" / "cache" / "local"
    if not cache_dir.exists():
        cache_dir = Path(__file__).parent.parent / "data" / "cache" / "local"
    if cache_dir.exists():
        for pf in cache_dir.glob("*.parquet"):
            sym = pf.stem
            if sym in updated:
                pf.unlink(missing_ok=True)
        print(f"已清除 {len(updated)} 个缓存文件")

    print(f"\n批量更新完成: 更新 {len(updated)} | 跳过 {len(skipped)} | 失败 {len(failed)}")
    return {"updated": updated, "skipped": skipped, "failed": failed, "end_date": end_date}


def run_update(
    symbols: Optional[List[str]] = None,
    end_date: Optional[str] = None,
    dry_run: bool = False,
    provider=None,
) -> Dict:
    """
    增量更新本地 A 股日行情数据。

    对每只股票：
    1. 检查本地 CSV 是否存在
    2. 读取已有数据的最新日期
    3. 调用 provider.incremental_update() 拉取缺口数据
    4. 追加写入 CSV（不覆盖已有行）

    参数:
        symbols (List[str], optional): 要更新的股票代码列表；
                                       None 表示全量（先读本地目录，再 fallback 到 provider）
        end_date (str, optional): 更新截止日期（含），格式 'YYYY-MM-DD' 或 'YYYYMMDD'；
                                  None 表示今天
        dry_run (bool): True 时只打印计划，不写文件
        provider: 数据提供者实例；None 时默认使用 AkShareProvider()

    返回:
        dict: {
            'updated': [更新成功的代码列表],
            'skipped': [已是最新跳过的代码列表],
            'failed':  [更新失败的代码列表],
            'end_date': str  # 实际使用的截止日期（YYYY-MM-DD）
        }
    """
    from providers.base import ProviderError
    from utils.runtime_config import get_local_data_dir

    if provider is None:
        # 优先 Tushare → AkShare → BaoStock
        try:
            from providers.tushare_provider import TushareProvider
            provider = TushareProvider()
            logger.info("使用 TushareProvider（批量模式）")
        except Exception:
            try:
                from providers.akshare_provider import AkShareProvider
                provider = AkShareProvider()
                provider.fetch_daily_history("000001", "20260101", "20260102")
                logger.info("使用 AkShareProvider")
            except Exception:
                logger.warning("Tushare/AkShare 均不可用，降级到 BaoStockProvider")
                from providers.baostock_provider import BaoStockProvider
                provider = BaoStockProvider()

    # 统一截止日期格式
    if end_date is None:
        end_date = datetime.today().strftime("%Y-%m-%d")
    else:
        end_date = str(pd.to_datetime(end_date).date())

    data_dir = get_local_data_dir()

    # 确定待更新股票列表
    if symbols is None:
        from utils.local_data_loader import get_all_symbols
        symbols = get_all_symbols()
        if not symbols:
            logger.info("本地无数据，从 provider 获取全量股票列表...")
            try:
                symbols = provider.get_stock_list()
            except ProviderError as e:
                logger.error("获取股票列表失败: %s", e)
                return {"updated": [], "skipped": [], "failed": [], "end_date": end_date}

    updated: List[str] = []
    skipped: List[str] = []
    failed: List[str] = []
    total = len(symbols)
    end_ts = pd.Timestamp(end_date)

    # ── Tushare 批量模式：按日期批量拉取，不逐只遍历 ──────────
    if hasattr(provider, "batch_daily"):
        return _run_batch_update(provider, symbols, end_date, data_dir, dry_run)

    for idx, symbol in enumerate(symbols, 1):
        tag = f"[{idx}/{total}]"
        csv_path = _get_csv_path(data_dir, symbol)
        is_new = csv_path is None

        # 计算 since_date
        since_date: Optional[str] = None
        if not is_new:
            latest = _read_latest_date(csv_path)
            if latest is not None:
                since_date = (latest + timedelta(days=1)).strftime("%Y-%m-%d")

        # 已是最新
        if since_date is not None and pd.Timestamp(since_date) > end_ts:
            print(f"{tag} 更新 {symbol} ... SKIP (up to date)")
            skipped.append(symbol)
            continue

        # 新文件从 2000-01-01 开始
        if since_date is None:
            since_date = "2000-01-01"

        if dry_run:
            action = "新建" if is_new else f"追加 since {since_date}"
            print(f"{tag} [DRY RUN] 更新 {symbol} — {action} → {end_date}")
            updated.append(symbol)
            continue

        # 拉取数据
        try:
            new_data = provider.incremental_update(symbol, since_date, end_date)
        except Exception as e:
            print(f"{tag} 更新 {symbol} ... FAIL ({e})")
            logger.warning("更新 %s 失败: %s", symbol, e)
            failed.append(symbol)
            continue

        if new_data.empty:
            print(f"{tag} 更新 {symbol} ... SKIP (up to date)")
            skipped.append(symbol)
            continue

        # 写入 CSV
        dest_path = csv_path if not is_new else _new_csv_path(data_dir, symbol)
        try:
            n_rows = _append_rows(dest_path, new_data, is_new_file=is_new)
            print(f"{tag} 更新 {symbol} ... OK (+{n_rows} rows)")
            updated.append(symbol)
        except Exception as e:
            print(f"{tag} 更新 {symbol} ... FAIL (写入失败: {e})")
            logger.warning("写入 %s 失败: %s", dest_path, e)
            failed.append(symbol)

        # 请求间隔（BaoStock 不需要限流，保留最小间隔防止 CPU 占满）
        if not dry_run and idx < total:
            time.sleep(0.05)

    return {
        "updated": updated,
        "skipped": skipped,
        "failed": failed,
        "end_date": end_date,
    }


if __name__ == "__main__":
    import sys
    symbols_arg = sys.argv[1:] if len(sys.argv) > 1 else None
    result = run_update(symbols=symbols_arg, dry_run=True)
    total = len(result["updated"]) + len(result["skipped"]) + len(result["failed"])
    print(
        f"\n汇总 (dry_run): 更新 {len(result['updated'])} | "
        f"跳过 {len(result['skipped'])} | 失败 {len(result['failed'])} | 共 {total}"
    )
