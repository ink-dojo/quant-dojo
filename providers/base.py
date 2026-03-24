"""
providers/base.py — 数据提供者抽象基类

定义数据提供者的统一接口，所有 provider 实现必须继承 BaseDataProvider。
"""

from abc import ABC, abstractmethod
from typing import List

import pandas as pd


class ProviderError(Exception):
    """数据源异常基类，source failure 时抛出。"""
    pass


class BaseDataProvider(ABC):
    """
    数据提供者抽象基类。

    所有 provider 必须实现以下三个方法：
    - get_stock_list: 获取全量 A 股代码列表
    - fetch_daily_history: 获取指定股票完整历史日行情
    - incremental_update: 增量更新指定股票的日行情

    所有方法返回的 DataFrame 均包含以下列（英文）：
        date, open, high, low, close, volume, amount
    """

    @abstractmethod
    def get_stock_list(self) -> List[str]:
        """
        获取全量 A 股代码列表。

        返回:
            List[str]: 6 位股票代码列表，例如 ['000001', '600000', ...]

        Raises:
            ProviderError: 数据源获取失败时
        """
        ...

    @abstractmethod
    def fetch_daily_history(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指定股票的完整历史日行情。

        参数:
            symbol (str): 6 位股票代码，例如 '000001'
            start_date (str): 开始日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date (str): 结束日期，格式 'YYYYMMDD' 或 'YYYY-MM-DD'

        返回:
            pd.DataFrame: 包含 date, open, high, low, close, volume, amount 列，
                          按日期升序排列，date 列为 datetime 类型

        Raises:
            ProviderError: 数据源返回异常时
        """
        ...

    @abstractmethod
    def incremental_update(
        self, symbol: str, since_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指定股票从 since_date 开始的增量日行情。

        参数:
            symbol (str): 6 位股票代码
            since_date (str): 起始日期（含），格式 'YYYYMMDD' 或 'YYYY-MM-DD'
            end_date (str): 结束日期（含），格式 'YYYYMMDD' 或 'YYYY-MM-DD'

        返回:
            pd.DataFrame: 与 fetch_daily_history 相同格式

        Raises:
            ProviderError: 数据源返回异常时
        """
        ...


if __name__ == "__main__":
    print("✅ providers.base 定义正常 | BaseDataProvider, ProviderError")
