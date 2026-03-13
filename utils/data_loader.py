"""
数据加载模块
支持 akshare（免费，无需注册）和 tushare（需token）
"""
import pandas as pd
import akshare as ak
from pathlib import Path

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
