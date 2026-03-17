"""
数据加载模块
支持 akshare（免费，无需注册）和 tushare（需token）
"""
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import akshare as ak
from pathlib import Path
from tqdm import tqdm

RAW_DIR = Path(__file__).parent.parent / "data" / "raw"
PROCESSED_DIR = Path(__file__).parent.parent / "data" / "processed"


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
) -> pd.DataFrame:
    """
    获取指数日线数据

    常用指数代码:
        sh000300  沪深300
        sh000001  上证指数
        sz399001  深证成指
        sz399006  创业板指
    """
    df = ak.stock_zh_index_daily(symbol=symbol)
    df = df.rename(columns={"date": "date"})
    df["date"] = pd.to_datetime(df["date"])
    df = df.set_index("date").sort_index()
    return df.loc[start:end]


def get_hs300_stocks() -> pd.DataFrame:
    """获取沪深300成分股列表"""
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
        return None

    # 自动搜索
    pattern = f"price_wide_{col}_{start}_{end}_{adjust}_*.parquet"
    matches = sorted(PROCESSED_DIR.glob(pattern))
    if not matches:
        return None

    path = matches[-1]  # 取最新的
    print(f"加载缓存: {path.name}")
    return pd.read_parquet(path)
