"""
示例策略：双均线交叉（MA Cross）

假设：短期均线上穿长期均线时，代表趋势上升，买入；下穿时卖出。
这是最经典的趋势跟踪策略，作为入门练手。

注意：这个策略在A股实际表现一般，仅作为学习框架使用。
"""
import pandas as pd
from strategies.base import BaseStrategy, StrategyConfig


class DualMACrossStrategy(BaseStrategy):

    description = "双均线交叉策略"
    hypothesis = (
        "短期均线上穿长期均线（金叉）时市场处于上升趋势，做多；"
        "下穿（死叉）时趋势反转，清仓。"
    )
    references = ["Faber (2007) - A Quantitative Approach to Tactical Asset Allocation"]

    def generate_signals(self, data: pd.DataFrame) -> pd.Series:
        close = data["close"]
        fast = self.config.params.get("fast_period", 20)
        slow = self.config.params.get("slow_period", 60)

        ma_fast = close.rolling(fast).mean()
        ma_slow = close.rolling(slow).mean()

        signal = pd.Series(0, index=close.index)
        signal[ma_fast > ma_slow] = 1    # 多头
        signal[ma_fast <= ma_slow] = 0   # 空仓

        # 去掉均线计算前的 NaN 期
        signal.iloc[:slow] = 0
        return signal

    def run(self, data: pd.DataFrame) -> pd.DataFrame:
        signals = self.generate_signals(data)

        # 信号在第二天开盘执行（避免未来函数）
        position = signals.shift(1).fillna(0)

        # 计算策略收益
        raw_returns = data["close"].pct_change()

        # 扣除交易成本（换手时收取）
        turnover = position.diff().abs()
        costs = turnover * (self.config.commission + self.config.slippage)

        strategy_returns = position * raw_returns - costs
        equity = self.config.initial_capital * (1 + strategy_returns).cumprod()

        self.results = pd.DataFrame({
            "returns": strategy_returns,
            "positions": position,
            "equity": equity,
            "signal": signals,
        })

        return self.results


if __name__ == "__main__":
    # 快速测试
    from utils.data_loader import get_stock_history, calc_returns
    from utils.metrics import performance_summary

    data = get_stock_history("000001", "2018-01-01", "2024-12-31")
    config = StrategyConfig(
        name="双均线_20_60",
        params={"fast_period": 20, "slow_period": 60},
    )
    strategy = DualMACrossStrategy(config)
    results = strategy.run(data)

    benchmark_returns = calc_returns(data["close"])
    print(performance_summary(results["returns"], name="双均线策略"))
    print(performance_summary(benchmark_returns, name="买入持有"))
