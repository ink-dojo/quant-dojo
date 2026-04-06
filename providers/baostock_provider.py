"""
providers/baostock_provider.py — BaoStock 数据提供者实现

使用 baostock 免费接口获取 A 股日线数据。
BaoStock 无需注册，直接 login() 即可使用，适合 AkShare 不可用时的备选。

会话管理：实例创建时 login，销毁时 logout，避免每次请求重连。
"""

import atexit
import logging
from typing import List

import pandas as pd

from providers.base import BaseDataProvider, ProviderError

logger = logging.getLogger(__name__)


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


_FIELDS = "date,open,high,low,close,preclose,volume,amount,turn,peTTM,pbMRQ,psTTM,pcfNcfTTM,isST"
_NUMERIC_COLS = ["open", "high", "low", "close", "preclose", "volume", "amount",
                 "turn", "peTTM", "pbMRQ", "psTTM", "pcfNcfTTM", "isST"]
# BaoStock 字段 → 本地 CSV 英文列名
_RENAME_MAP = {
    "preclose": "prev_close",
    "turn": "turnover",
    "peTTM": "pe_ttm",
    "pbMRQ": "pb",
    "psTTM": "ps_ttm",
    "pcfNcfTTM": "pcf",
    "isST": "is_st",
}


class BaoStockProvider(BaseDataProvider):
    """
    BaoStock 数据提供者。

    特点：
    - 免费、无需注册
    - 数据延迟约 1 个交易日
    - 支持后复权 (adjustflag='2')
    - 实例级会话复用，避免每次请求 login/logout
    """

    def __init__(self):
        """初始化并登录 baostock 会话。"""
        import baostock as bs
        self._bs = bs
        self._logged_in = False
        self._login()

    def _login(self):
        """登录 baostock，如果已登录则跳过。"""
        if not self._logged_in:
            try:
                lg = self._bs.login()
                if lg.error_code != "0":
                    raise ProviderError(f"baostock login 失败: {lg.error_msg}")
                self._logged_in = True
                atexit.register(self._logout)
            except ProviderError:
                raise
            except Exception as e:
                raise ProviderError(f"baostock login 异常: {e}") from e

    def _logout(self):
        """登出 baostock 会话。"""
        if self._logged_in:
            try:
                self._bs.logout()
            except Exception:
                pass
            self._logged_in = False

    def _query(self, bs_code: str, start_date: str, end_date: str) -> list:
        """
        执行一次 baostock 查询，自动重连。

        参数:
            bs_code: baostock 格式代码（sh.600000）
            start_date: YYYY-MM-DD
            end_date: YYYY-MM-DD

        返回:
            list: 行数据列表
        """
        self._login()  # 确保已登录
        rs = self._bs.query_history_k_data_plus(
            bs_code, _FIELDS,
            start_date=start_date,
            end_date=end_date,
            frequency="d",
            adjustflag="2",
        )
        if rs.error_code != "0":
            # 可能会话断了，尝试重连一次
            logger.warning("baostock 查询失败 (%s)，尝试重连", rs.error_msg)
            self._logged_in = False
            self._login()
            rs = self._bs.query_history_k_data_plus(
                bs_code, _FIELDS,
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="2",
            )
            if rs.error_code != "0":
                raise ProviderError(f"baostock 查询 {bs_code} 失败: {rs.error_msg}")

        rows = []
        while (rs.error_code == "0") and rs.next():
            rows.append(rs.get_row_data())
        return rows

    def get_stock_list(self) -> List[str]:
        """
        获取全量 A 股代码列表。

        返回:
            List[str]: 6 位股票代码列表

        Raises:
            ProviderError: baostock 调用失败时
        """
        self._login()
        try:
            rs = self._bs.query_stock_basic()
            rows = []
            while (rs.error_code == "0") and rs.next():
                rows.append(rs.get_row_data())
        except Exception as e:
            raise ProviderError(f"baostock query_stock_basic 失败: {e}") from e

        if not rows:
            raise ProviderError("baostock 返回空股票列表")

        symbols = []
        for row in rows:
            code = row[0]
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
            rows = self._query(bs_code, start_date, end_date)
        except ProviderError:
            raise
        except Exception as e:
            raise ProviderError(f"baostock query {symbol} 失败: {e}") from e

        if not rows:
            return pd.DataFrame(columns=["date"] + _NUMERIC_COLS)

        df = pd.DataFrame(rows, columns=_FIELDS.split(","))

        for col in _NUMERIC_COLS:
            df[col] = pd.to_numeric(df[col], errors="coerce")

        df = df.dropna(subset=["close"])
        df = df.rename(columns=_RENAME_MAP)
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
