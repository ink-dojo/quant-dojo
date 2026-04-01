"""
数据加载模块
支持 akshare（免费，无需注册）和 tushare（需token）
"""
import logging
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
from pathlib import Path
from tqdm import tqdm

logger = logging.getLogger(__name__)

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"
INDEX_CACHE_DIR = RAW_DIR / "indices"


def get_stock_history(
    symbol: str,
    start: str,
    end: str,
    adjust: str = "qfq",  # qfq=前复权, hfq=后复权, ""=不复权
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取单只股票日线数据

    参数:
        symbol: 股票代码，如 "000001" （不带后缀）
        start:  开始日期，如 "2020-01-01"
        end:    结束日期，如 "2024-12-31"
        adjust: 复权方式
        use_cache: 是否使用本地缓存

    返回:
        DataFrame，列：date, open, high, low, close, volume, amount
    """
    cache_path = RAW_DIR / f"{symbol}_{start}_{end}_{adjust}.parquet"
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    if use_cache and cache_path.exists():
        return pd.read_parquet(cache_path)

    import akshare as ak
    df = ak.stock_zh_a_hist(
        symbol=symbol,
        period="daily",
        start_date=start.replace("-", ""),
        end_date=end.replace("-", ""),
        adjust=adjust,
    )
    df = df.rename(columns={
        "日期": "date", "开盘": "open", "最高": "high",
        "最低": "low", "收盘": "close", "成交量": "volume",
        "成交额": "amount", "涨跌幅": "pct_change",
    })
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()

    df.to_parquet(cache_path)
    return df


def get_index_history(
    symbol: str = "sh000300",  # 沪深300
    start: str = "2020-01-01",
    end: str = "2024-12-31",
    use_cache: bool = True,
) -> pd.DataFrame:
    """
    获取指数日线数据

    常用指数代码:
        sh000300  沪深300
        sh000001  上证指数
        sz399001  深证成指
        sz399006  创业板指
    """
    INDEX_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    cache_path = INDEX_CACHE_DIR / f"{symbol}.parquet"

    if use_cache:
        cached = _read_index_cache(cache_path)
        if cached is not None and _cache_covers(cached, start_ts, end_ts):
            return cached.loc[start:end]

    errors = []
    for fetcher in (_fetch_index_history_akshare, _fetch_index_history_baostock):
        try:
            df = fetcher(symbol)
            if df is None or df.empty:
                continue
            df = _normalize_index_history(df)
            subset = df.loc[start:end]
            if subset.empty:
                continue
            _write_index_cache(cache_path, df)
            return subset
        except Exception as exc:
            errors.append(f"{fetcher.__name__}: {exc}")

    cached = _read_index_cache(cache_path)
    if cached is not None:
        subset = cached.loc[start:end]
        if not subset.empty:
            logger.warning("指数在线获取失败，回退到本地缓存: %s", "; ".join(errors))
            return subset

    raise RuntimeError(
        f"无法获取指数 {symbol} {start}~{end} 数据；已尝试 AkShare 和 BaoStock。"
        + (f" 错误: {'; '.join(errors)}" if errors else "")
    )


def _cache_covers(df: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp) -> bool:
    if df.empty:
        return False
    return df.index.min() <= start and df.index.max() >= end


def _read_index_cache(path: Path) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        return _normalize_index_history(pd.read_parquet(path))
    except Exception as exc:
        logger.warning("读取指数缓存失败 %s: %s", path, exc)
        return None


def _write_index_cache(path: Path, df: pd.DataFrame) -> None:
    if path.exists():
        cached = _read_index_cache(path)
        if cached is not None and not cached.empty:
            df = pd.concat([cached, df]).sort_index()
            df = df[~df.index.duplicated(keep="last")]
    df.to_parquet(path)


def _normalize_index_history(df: pd.DataFrame) -> pd.DataFrame:
    if "date" in df.columns:
        df = df.copy()
        df["date"] = pd.to_datetime(df["date"])
        df = df.set_index("date")
    df = df.sort_index()
    df.index = pd.to_datetime(df.index)
    numeric_cols = [c for c in ["open", "high", "low", "close", "volume", "amount"] if c in df.columns]
    for col in numeric_cols:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df


def _fetch_index_history_akshare(symbol: str) -> pd.DataFrame:
    import akshare as ak

    df = ak.stock_zh_index_daily(symbol=symbol)
    return df.rename(columns={"date": "date"})


def _fetch_index_history_baostock(symbol: str) -> pd.DataFrame:
    import baostock as bs

    code = _to_baostock_code(symbol)
    login = bs.login()
    if login.error_code != "0":
        raise RuntimeError(f"BaoStock 登录失败: {login.error_msg}")
    try:
        rs = bs.query_history_k_data_plus(
            code,
            "date,code,open,high,low,close,volume,amount",
            frequency="d",
            adjustflag="3",
        )
        if rs.error_code != "0":
            raise RuntimeError(f"BaoStock 查询失败: {rs.error_msg}")
        rows = []
        while rs.next():
            rows.append(rs.get_row_data())
        if not rows:
            return pd.DataFrame()
        return pd.DataFrame(rows, columns=rs.fields)
    finally:
        bs.logout()


def _to_baostock_code(symbol: str) -> str:
    if symbol.startswith("sh"):
        return f"sh.{symbol[2:]}"
    if symbol.startswith("sz"):
        return f"sz.{symbol[2:]}"
    raise ValueError(f"不支持的指数代码格式: {symbol}")


def get_hs300_stocks() -> pd.DataFrame:
    """获取沪深300成分股列表"""
    import akshare as ak
    return ak.index_stock_cons_weight_csindex(symbol="000300")


def calc_returns(prices: pd.Series) -> pd.Series:
    """从价格序列计算日收益率"""
    return prices.pct_change().dropna()


# ─────────────────────────────────────────────
# 批量下载
# ─────────────────────────────────────────────

def batch_download(
    symbols: list,
    start: str,
    end: str,
    adjust: str = "qfq",
    max_workers: int = 4,
    retry: int = 2,
    show_progress: bool = True,
) -> dict:
    """
    批量下载多只股票历史数据

    参数:
        symbols     : 股票代码列表
        start, end  : 日期范围
        adjust      : 复权方式
        max_workers : 并发线程数（akshare 请求有限速，建议 ≤ 5）
        retry       : 失败重试次数
        show_progress: 是否显示进度条

    返回:
        {symbol: DataFrame}，失败的股票会跳过
    """
    results = {}
    errors = []

    def _fetch(sym):
        for attempt in range(retry + 1):
            try:
                df = get_stock_history(sym, start, end, adjust=adjust)
                return sym, df
            except Exception:
                if attempt < retry:
                    time.sleep(0.5)
        return sym, None

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {executor.submit(_fetch, s): s for s in symbols}
        iter_ = as_completed(futures)
        if show_progress:
            iter_ = tqdm(iter_, total=len(symbols), desc="下载中", ncols=80)
        for future in iter_:
            sym, df = future.result()
            if df is not None and not df.empty:
                results[sym] = df
            else:
                errors.append(sym)

    if errors:
        warnings.warn(
            f"{len(errors)} 只股票下载失败: "
            f"{errors[:5]}{'...' if len(errors) > 5 else ''}"
        )

    print(f"✅ 成功: {len(results)}/{len(symbols)} 只")
    return results


# ─────────────────────────────────────────────
# 宽表构建（date × symbol）
# ─────────────────────────────────────────────

def build_price_matrix(
    symbols: list,
    start: str,
    end: str,
    adjust: str = "qfq",
    col: str = "close",
    use_cache: bool = True,
    max_workers: int = 4,
) -> pd.DataFrame:
    """
    构建价格宽表（date × symbol），因子研究的基础数据

    参数:
        symbols     : 股票代码列表
        start, end  : 日期范围
        col         : 提取的列，默认 'close'（收盘价）
        use_cache   : 是否读本地缓存
        max_workers : 并发线程数

    返回:
        DataFrame，index=日期，columns=股票代码
    """
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    n = len(symbols)
    cache_name = f"price_wide_{col}_{start}_{end}_{adjust}_{n}stocks.parquet"
    cache_path = PROCESSED_DIR / cache_name

    if use_cache and cache_path.exists():
        print(f"读取缓存: {cache_name}")
        return pd.read_parquet(cache_path)

    stock_data = batch_download(symbols, start, end, adjust=adjust, max_workers=max_workers)

    price_dict = {
        sym: df[col]
        for sym, df in stock_data.items()
        if col in df.columns
    }
    price_wide = pd.DataFrame(price_dict).sort_index()
    price_wide.index = pd.to_datetime(price_wide.index)

    price_wide.to_parquet(cache_path)
    print(f"✅ 价格宽表已缓存: {cache_name}  形状: {price_wide.shape}")
    return price_wide


def build_return_matrix(price_wide: pd.DataFrame) -> pd.DataFrame:
    """
    从价格宽表计算日收益率宽表（date × symbol）

    使用方法:
        price_wide = build_price_matrix(symbols, start, end)
        ret_wide   = build_return_matrix(price_wide)
    """
    return price_wide.pct_change().iloc[1:]


def load_price_matrix(
    start: str,
    end: str,
    n_stocks: int = None,
    col: str = "close",
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    从缓存加载价格宽表（不重新下载）

    参数:
        n_stocks: 当初下载时的股票数量，用于匹配缓存文件名
                  为 None 时自动搜索最新的匹配缓存

    返回:
        DataFrame 或 None（未找到缓存时）
    """
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

    if n_stocks is not None:
        path = PROCESSED_DIR / f"price_wide_{col}_{start}_{end}_{adjust}_{n_stocks}stocks.parquet"
        if path.exists():
            return pd.read_parquet(path)
        logger.info("未找到宽表缓存: %s，尝试从本地 CSV 构建", path.name)
        return _build_price_matrix_from_local_csv(start, end, n_stocks=n_stocks, col=col)

    # 自动搜索
    pattern = f"price_wide_{col}_{start}_{end}_{adjust}_*.parquet"
    matches = sorted(PROCESSED_DIR.glob(pattern))
    if not matches:
        logger.info("未找到匹配缓存 %s，尝试从本地 CSV 构建", pattern)
        return _build_price_matrix_from_local_csv(start, end, n_stocks=n_stocks, col=col)

    path = matches[-1]  # 取最新的
    print(f"加载缓存: {path.name}")
    return pd.read_parquet(path)


def _build_price_matrix_from_local_csv(
    start: str,
    end: str,
    n_stocks: int = None,
    col: str = "close",
) -> pd.DataFrame:
    """
    从本地 CSV 数据目录直接构建价格宽表，作为旧 notebook 的兜底路径。

    这条路径依赖 utils.local_data_loader 的运行时配置，不触发网络下载。
    成功后会写入 data/processed，方便后续 notebook 直接命中缓存。
    """
    try:
        from utils.local_data_loader import get_all_symbols, load_price_wide
    except Exception as exc:
        logger.warning("无法导入 local_data_loader，无法从本地 CSV 构建宽表: %s", exc)
        return None

    symbols = get_all_symbols()
    if not symbols:
        logger.warning("本地 CSV 目录未发现任何股票文件，无法构建宽表")
        return None

    if n_stocks is not None:
        symbols = symbols[:n_stocks]

    wide = load_price_wide(symbols, start, end, field=col)
    if wide is None or wide.empty:
        logger.warning("从本地 CSV 构建宽表失败或结果为空: %s ~ %s", start, end)
        return None

    cache_name = f"price_wide_{col}_{start}_{end}_qfq_{len(wide.columns)}stocks.parquet"
    cache_path = PROCESSED_DIR / cache_name
    try:
        wide.to_parquet(cache_path)
        logger.info("本地 CSV 宽表已缓存: %s", cache_path.name)
    except Exception as exc:
        logger.warning("写入宽表缓存失败: %s", exc)

    return wide
