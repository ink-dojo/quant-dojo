"""
providers/baostock_provider.py — BaoStock 数据提供者实现

使用 baostock 免费接口获取 A 股日线数据。
BaoStock 无需注册，直接 login() 即可使用，适合 AkShare 不可用时的备选。

字段映射：baostock 返回 date/open/high/low/close/volume/amount，与 provider contract 一致。
"""

import logging
from typing import List

import pandas as pd

from providers.base import BaseDataProvider, ProviderError

logger = logging.getLogger(__name__)

# baostock 的 symbol 格式是 sh.600000 / sz.000001
def _to_bs_code(symbol: str) -> str:
    """6 位代码转 baostock 格式"""
    if symbol.startswith("6"):
        return f"sh.{symbol}"
    return f"sz.{symbol}"


def _normalize_date(d: str) -> str:
    """确保日期格式为 YYYY-MM-DD"""
    d = d.replace("/", "-")
    if len(d) == 8 and "-" not in d:
        return f"{d[:4]}-{d[4:6]}-{d[6:8]}"
    return d


_FIELDS = "date,open,high,low,close,volume,amount"
_NUMERIC_COLS = ["open", "high", "low", "close", "volume", "amount"]


class BaoStockProvider(BaseDataProvider):
    """
    BaoStock 数据提供者。

    特点：
    - 免费、无需注册
    - 数据延迟约 1 个交易日
    - 支持后复权 (adjustflag='2')
    """

    def get_stock_list(self) -> List[str]:
        """
        获取全量 A 股代码列表。

        返回:
            List[str]: 6 位股票代码列表

        Raises:
            ProviderError: baostock 调用失败时
        """
        try:
            import baostock as bs
            bs.login()
            rs = bs.query_stock_basic()
            rows = []
            while (rs.error_code == "0") and rs.next():
                rows.append(rs.get_row_data())
            bs.logout()
        except Exception as e:
            raise ProviderError(f"baostock query_stock_basic 失败: {e}") from e

        if not rows:
            raise ProviderError("baostock 返回空股票列表")

        # 提取 6 位代码（code 列格式为 sh.600000）
        symbols = []
        for row in rows:
            code = row[0]  # 第一列是 code
            if "." in code:
                code = code.split(".")[-1]
            if len(code) == 6 and code.isdigit():
                symbols.append(code)

        return sorted(set(symbols))

    def fetch_daily_history(
        self, symbol: str, start_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        获取指定股票的历史日行情（后复权）。

        参数:
            symbol: 6 位股票代码
            start_date: 开始日期
            end_date: 结束日期

        返回:
            DataFrame: date/open/high/low/close/volume/amount

        Raises:
            ProviderError: 数据获取失败时
        """
        start_date = _normalize_date(start_date)
        end_date = _normalize_date(end_date)
        bs_code = _to_bs_code(symbol)

        try:
            import baostock as bs
            bs.login()
            rs = bs.query_history_k_data_plus(
                bs_code, _FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",  # 后复权
            )
            rows = []
            while (rs.error_code == "0") and rs.next():
                rows.append(rs.get_row_data())
            bs.logout()
        except Exception as e:
            raise ProviderError(f"baostock query {symbol} 失败: {e}") from e

        if not rows:
            return pd.DataFrame(columns=["date"] + _NUMERIC_COLS)

        df = pd.DataFrame(rows, columns=_FIELDS.split(","))

        # 转数值类型（baostock 返回字符串）
        for col in _NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # 去掉全空行
        df = df.dropna(subset=["close"])

        return df

    def incremental_update(
        self, symbol: str, since_date: str, end_date: str
    ) -> pd.DataFrame:
        """
        增量更新：获取 since_date 到 end_date 的日行情。

        参数:
            symbol: 6 位股票代码
            since_date: 起始日期（含）
            end_date: 结束日期（含）

        返回:
            DataFrame: 与 fetch_daily_history 格式一致
        """
        return self.fetch_daily_history(symbol, since_date, end_date)


if __name__ == "__main__":
    provider = BaoStockProvider()
    df = provider.fetch_daily_history("000001", "2026-03-20", "2026-03-24")
    print(f"平安银行 3/20-3/24: {len(df)} 行")
    print(df)
    print("✅ BaoStockProvider import ok")
