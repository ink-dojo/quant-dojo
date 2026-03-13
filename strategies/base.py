"""
策略基类
所有策略继承自 BaseStrategy，实现统一接口
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional
import pandas as pd


@dataclass
class StrategyConfig:
    """策略配置"""
    name: str
    initial_capital: float = 1_000_000
    commission: float = 0.0003          # 单边手续费
    slippage: float = 0.001             # 滑点
    benchmark: str = "000300"           # 基准指数
    max_position_pct: float = 1.0       # 单只股票最大仓位比例
    params: dict = field(default_factory=dict)  # 策略特定参数


class BaseStrategy(ABC):
    """
    策略基类

    子类必须实现：
        generate_signals()  — 生成交易信号
        run()               — 执行回测逻辑

    子类应当填写：
        description         — 策略描述
        hypothesis          — 策略假设（为什么能赚钱）
        references          — 参考文献或来源
    """

    description: str = ""
    hypothesis: str = ""
    references: list = []

    def __init__(self, config: StrategyConfig):
        self.config = config
        self.results: Optional[pd.DataFrame] = None

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        """
        生成交易信号

        参数:
            data: 价格数据 DataFrame

        返回:
            signal Series，值域：
                1  = 买入/持有多头
                0  = 空仓
               -1  = 卖出/持有空头（如支持做空）
        """
        raise NotImplementedError

    @abstractmethod
    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        执行回测

        参数:
            data: 价格数据

        返回:
            results DataFrame，至少包含：
                returns       日收益率
                positions     持仓
                equity        账户净值
        """
        raise NotImplementedError

    def get_returns(self) -> pd.Series:
        """获取策略日收益率"""
        if self.results is None:
            raise RuntimeError("请先调用 run() 方法")
        return self.results["returns"]

    def __repr__(self):
        return f"<Strategy: {self.config.name}>"
