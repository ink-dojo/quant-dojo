"""
providers/akshare_provider.py — AkShare 数据提供者实现

封装 akshare 的 A 股日行情接口，对外统一返回英文列名 DataFrame。
后复权（hfq）日行情，日期升序。
"""

import logging
from typing import List

import pandas as pd

from providers.base import BaseDataProvider, ProviderError

logger = logging.getLogger(__name__)

# ak.stock_zh_a_hist 返回的中文列 → 英文列名映射
_COLUMN_MAP = {
    "日期": "date",
    "开盘": "open",
    "最高": "high",
    "最低": "low",
    "收盘": "close",
    "成交量": "volume",
    "成交额": "amount",
}

_REQUIRED_COLS = ["date", "open", "high", "low", "close", "volume", "amount"]


class AkShareProvider(BaseDataProvider):
    """
    基于 akshare 的 A 股数据提供者。

    使用 ak.stock_zh_a_hist 获取后复权日行情，
    ak.stock_info_a_code_name 获取全量股票列表。
    """

    def get_stock_list(self) -> List[str]:
        """
        获取全量 A 股代码列表。

        使用 ak.stock_info_a_code_name() 获取所有 A 股信息。

        返回:
            List[str]: 6 位股票代码列表，例如 ['000001', '600000', ...]

        Raises:
            ProviderError: akshare 调用失败时
        """
        try:
            import akshare as ak
            df = ak.stock_info_a_code_name()
        except Exception as e:
            raise ProviderError(f"ak.stock_info_a_code_name() 失败: {e}") from e

        # 找代码列（优先包含 "code" 或 "代码" 的列）
        code_col = None
        for col in df.columns:
            if "code" in col.lower() or "代码" in col:
                code_col = col
                break
        if code_col is None:
            code_col = df.columns[0]

        codes = df[code_col].astype(str).str.zfill(6).tolist()
        return codes

    def fetch_daily_history(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指定股票的完整历史日行情（后复权）。

        参数:
            symbol (str): 6 位股票代码，例如 '000001'
            start_date (str): 开始日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date (str): 结束日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'

        返回:
            pd.DataFrame: 包含 date, open, high, low, close, volume, amount，
                          按日期升序排列，date 列为 datetime 类型

        Raises:
            ProviderError: akshare 调用或数据解析失败时
        """
        # AkShare 要求 YYYYMMDD 格式
        start_fmt = start_date.replace("-", "")
        end_fmt = end_date.replace("-", "")

        try:
            import akshare as ak
            df = ak.stock_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_fmt,
                end_date=end_fmt,
                adjust="hfq",
            )
        except Exception as e:
            raise ProviderError(f"ak.stock_zh_a_hist({symbol}) 失败: {e}") from e

        if df is None or df.empty:
            return pd.DataFrame(columns=_REQUIRED_COLS)

        return self._normalize(df, symbol)

    def incremental_update(
        self, symbol: str, since_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指定股票从 since_date 开始的增量日行情。

        直接调用 fetch_daily_history 实现，since_date 即 start_date。

        参数:
            symbol (str): 6 位股票代码
            since_date (str): 起始日期（含）
            end_date (str): 结束日期（含）

        返回:
            pd.DataFrame: 与 fetch_daily_history 相同格式

        Raises:
            ProviderError: 数据源失败时
        """
        return self.fetch_daily_history(symbol, since_date, end_date)

    def _normalize(self, df: pd.DataFrame, symbol: str) -> pd.DataFrame:
        """
        标准化 AkShare 返回的 DataFrame：重命名列、解析日期、保留必要列、升序排序。

        参数:
            df (pd.DataFrame): AkShare 原始返回数据
            symbol (str): 股票代码（用于日志）

        返回:
            pd.DataFrame: 标准化后的 DataFrame，包含 _REQUIRED_COLS

        Raises:
            ProviderError: 找不到日期列时
        """
        # 重命名中文列 → 英文列
        df = df.rename(columns={k: v for k, v in _COLUMN_MAP.items() if k in df.columns})

        if "date" not in df.columns:
            raise ProviderError(
                f"{symbol}: 返回数据中找不到日期列，实际列: {list(df.columns)}"
            )

        # 解析日期为 datetime
        df["date"] = pd.to_datetime(df["date"], errors="coerce")

        # 补全缺失的必要列（不抛错，用 NaN 填充并记录警告）
        missing = [c for c in _REQUIRED_COLS if c not in df.columns]
        if missing:
            logger.warning("%s: AkShare 返回数据缺少列 %s，用 NaN 填充", symbol, missing)
            for col in missing:
                df[col] = float("nan")

        df = df[_REQUIRED_COLS].copy()

        # 按日期升序排列
        df = df.sort_values("date").reset_index(drop=True)

        return df


if __name__ == "__main__":
    p = AkShareProvider()
    print("✅ AkShareProvider 实例化正常")
    print("  调用 get_stock_list() 需要 akshare 网络连接，此处跳过")
