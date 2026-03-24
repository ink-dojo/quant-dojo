"""
providers — 数据提供者模块

导出 BaseDataProvider 抽象基类、ProviderError 异常类和两个实现类。
AkShare 为默认数据源，BaoStock 为备选（AkShare 不可用时自动降级）。
"""

from providers.base import BaseDataProvider, ProviderError
from providers.akshare_provider import AkShareProvider
from providers.baostock_provider import BaoStockProvider

__all__ = ["BaseDataProvider", "AkShareProvider", "BaoStockProvider", "ProviderError"]
