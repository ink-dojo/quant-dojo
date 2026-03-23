"""
回测引擎
封装常用回测逻辑，提供统一的回测入口和报告输出
"""
import pandas as pd
import matplotlib.pyplot as plt
from strategies.base import BaseStrategy
from utils.metrics import performance_summary
from utils.plotting import plot_cumulative_returns, plot_drawdown, plot_monthly_returns_heatmap


class BacktestEngine:
    """
    回测引擎

    使用示例:
        engine = BacktestEngine(strategy, data, benchmark_returns)
        report = engine.run()
        engine.plot()
    """

    def __init__(
        self,
        strategy: BaseStrategy,
        data: pd.DataFrame,
        benchmark_returns: pd.Series = None,
    ):
        self.strategy = strategy
        self.data = data
        self.benchmark_returns = benchmark_returns
        self.results = None

    def run(self) -> pd.DataFrame:
        """执行回测，返回绩效报告"""
        self.results = self.strategy.run(self.data)

        if "returns" in self.results.columns:
            strategy_returns = self.results["returns"]
        elif "portfolio_return" in self.results.columns:
            strategy_returns = self.results["portfolio_return"]
        else:
            strategy_returns = self.strategy.get_returns()

        returns_dict = {"策略": strategy_returns}
        if self.benchmark_returns is not None:
            returns_dict["基准（买入持有）"] = self.benchmark_returns.reindex(
                strategy_returns.index
            ).fillna(0)

        summaries = []
        for name, ret in returns_dict.items():
            summaries.append(performance_summary(ret, name=name))

        report = pd.concat(summaries, axis=1)
        print("\n" + "=" * 50)
        print(f"  回测报告：{self.strategy.config.name}")
        print("=" * 50)
        print(report.to_string())
        print("=" * 50 + "\n")

        return report

    def plot(self):
        """生成标准图表集"""
        if self.results is None:
            raise RuntimeError("请先调用 run()")

        if "returns" in self.results.columns:
            strategy_returns = self.results["returns"]
        elif "portfolio_return" in self.results.columns:
            strategy_returns = self.results["portfolio_return"]
        else:
            strategy_returns = self.strategy.get_returns()

        returns_dict = {"策略": strategy_returns}
        if self.benchmark_returns is not None:
            returns_dict["基准"] = self.benchmark_returns.reindex(
                strategy_returns.index
            ).fillna(0)

        fig1 = plot_cumulative_returns(returns_dict, title=f"累计收益 — {self.strategy.config.name}")
        fig2 = plot_drawdown(strategy_returns, title=f"回撤 — {self.strategy.config.name}")
        fig3 = plot_monthly_returns_heatmap(strategy_returns)

        plt.show()
        return fig1, fig2, fig3
