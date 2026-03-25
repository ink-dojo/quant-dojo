"""
providers — 数据提供者模块

数据源层级：
  - AkShare: 日线主力（东方财富后端，偶尔不可用）
  - BaoStock: 日线/分钟线/财务备选（免费、无限制、但慢）
  - Sina Finance: 实时行情（无 key、毫秒级、800只/请求）
"""

from providers.base import BaseDataProvider, ProviderError
from providers.akshare_provider import AkShareProvider
from providers.baostock_provider import BaoStockProvider
from providers.sina_provider import fetch_realtime_quotes, get_portfolio_valuation

__all__ = [
    "BaseDataProvider", "ProviderError",
    "AkShareProvider", "BaoStockProvider",
    "fetch_realtime_quotes", "get_portfolio_valuation",
]
