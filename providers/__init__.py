"""
providers — 数据提供者模块

导出 BaseDataProvider 抽象基类、ProviderError 异常类和 AkShareProvider 实现类。
"""

from providers.base import BaseDataProvider, ProviderError
from providers.akshare_provider import AkShareProvider

__all__ = ["BaseDataProvider", "AkShareProvider", "ProviderError"]
