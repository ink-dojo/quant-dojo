"""
策略容量估算模块

根据组合内股票的历史成交量（ADV）和参与率限制，
估算策略可承受的最大 AUM（资金管理规模）。

所有金额以人民币（CNY）计。
"""

import numpy as np
import pandas as pd


class StrategyCapacity:
    """
    策略容量估算器。

    封装容量计算的中间状态和结果，支持调整参数后重新计算。

    参数:
        price_df          : 收盘价宽表 (date x symbol)
        volume_df         : 成交量宽表 (date x symbol)，单位：股
        universe          : 策略股票池列表
        n_stocks          : 组合目标持仓数
        participation_rate: 单只股票最大参与率（占 ADV 比例），默认 5%
        rebalance_days    : 调仓周期（天），默认 20
        turnover_fraction : 每次调仓换手比例，默认 0.3
    """

    def __init__(
        self,
        price_df: pd.DataFrame,
        volume_df: pd.DataFrame,
        universe: list[str],
        n_stocks: int = 30,
        participation_rate: float = 0.05,
        rebalance_days: int = 20,
        turnover_fraction: float = 0.3,
    ):
        self.price_df = price_df
        self.volume_df = volume_df
        self.universe = universe
        self.n_stocks = n_stocks
        self.participation_rate = participation_rate
        self.rebalance_days = rebalance_days
        self.turnover_fraction = turnover_fraction

        # 中间结果
        self._adv_20d = None
        self._daily_tradeable_value = None
        self._result = None

    def compute(self) -> dict:
        """
        执行容量估算，返回结果字典。

        计算逻辑:
            1. 对组合内每只股票计算 20 日平均成交量（ADV_20d）
            2. 每只股票日可交易量 = ADV_20d * participation_rate
            3. 日可交易金额 = 日可交易量 * 最新价格
            4. 总容量 = sum(日可交易金额) * (rebalance_days / turnover_fraction)

        返回:
            dict，键与 estimate_capacity 函数一致
        """
        # 取组合内存在的股票
        valid_syms = [s for s in self.universe if s in self.price_df.columns
                      and s in self.volume_df.columns]

        if not valid_syms:
            return {
                "capacity_cny": 0.0,
                "capacity_wan": 0.0,
                "median_adv_per_stock": 0.0,
                "binding_stocks": [],
                "participation_rate": self.participation_rate,
                "note": "组合内无有效股票，无法估算容量",
            }

        # 20 日平均成交量（股数）
        vol_sub = self.volume_df[valid_syms]
        self._adv_20d = vol_sub.rolling(window=20, min_periods=10).mean().iloc[-1]

        # 最新价格
        price_sub = self.price_df[valid_syms]
        latest_price = price_sub.iloc[-1]

        # 日可交易金额（CNY）= ADV_20d * participation_rate * price
        self._daily_tradeable_value = (
            self._adv_20d * self.participation_rate * latest_price
        )

        # 只取前 n_stocks 只（按可交易金额从大到小排序，取实际可用数量）
        actual_n = min(self.n_stocks, len(valid_syms))
        sorted_tradeable = self._daily_tradeable_value.dropna().sort_values(ascending=False)
        top_stocks = sorted_tradeable.head(actual_n)

        # 总容量 = sum(日可交易金额) * (rebalance_days / turnover_fraction)
        total_daily = top_stocks.sum()
        capacity_cny = total_daily * (self.rebalance_days / self.turnover_fraction)

        # 中位数日均成交额（万元）
        adv_value = self._adv_20d * latest_price  # 全组合
        median_adv_wan = adv_value.dropna().median() / 1e4

        # 流动性最差的 5 只股票（按日可交易金额升序排列，取前 5）
        all_tradeable_sorted = self._daily_tradeable_value.dropna().sort_values(ascending=True)
        binding_n = min(5, len(all_tradeable_sorted))
        binding_stocks = all_tradeable_sorted.head(binding_n).index.tolist()

        self._result = {
            "capacity_cny": float(capacity_cny),
            "capacity_wan": float(capacity_cny / 1e4),
            "median_adv_per_stock": float(median_adv_wan),
            "binding_stocks": binding_stocks,
            "participation_rate": self.participation_rate,
            "note": (
                f"策略最大 AUM 约 {capacity_cny / 1e8:.2f} 亿元 "
                f"({capacity_cny / 1e4:.0f} 万元)，"
                f"基于 {actual_n} 只股票、"
                f"参与率 {self.participation_rate:.0%}、"
                f"调仓 {self.rebalance_days} 天 / "
                f"换手 {self.turnover_fraction:.0%}"
            ),
        }
        return self._result


def estimate_capacity(
    price_df: pd.DataFrame,
    volume_df: pd.DataFrame,
    universe: list[str],
    n_stocks: int = 30,
    participation_rate: float = 0.05,
    rebalance_days: int = 20,
    turnover_fraction: float = 0.3,
) -> dict:
    """
    估算策略最大可承受 AUM。

    对组合内每只股票，基于 20 日平均成交量（ADV）和参与率上限，
    计算单只股票日可交易金额，再按调仓频率和换手率推算总容量。

    参数:
        price_df          : 收盘价宽表 (date x symbol)
        volume_df         : 成交量宽表 (date x symbol)，单位：股
        universe          : 策略股票池列表
        n_stocks          : 组合目标持仓数，默认 30
        participation_rate: 单只股票最大参与率（占 ADV 比例），默认 0.05（5%）
        rebalance_days    : 调仓周期（天），默认 20
        turnover_fraction : 每次调仓换手比例，默认 0.3（30%）

    返回:
        {
          "capacity_cny": float,          # 最大 AUM（人民币）
          "capacity_wan": float,          # 最大 AUM（万元）
          "median_adv_per_stock": float,  # 组合内股票中位数日均成交额（万元）
          "binding_stocks": list,         # 制约容量的流动性最差的股票列表（前5）
          "participation_rate": float,
          "note": str,                    # 人类可读的摘要
        }
    """
    estimator = StrategyCapacity(
        price_df=price_df,
        volume_df=volume_df,
        universe=universe,
        n_stocks=n_stocks,
        participation_rate=participation_rate,
        rebalance_days=rebalance_days,
        turnover_fraction=turnover_fraction,
    )
    return estimator.compute()


if __name__ == "__main__":
    np.random.seed(42)

    # 构造测试数据
    n_dates = 60
    symbols = [f"{i:06d}.SZ" for i in range(1, 51)]  # 50 只股票
    dates = pd.date_range("2025-01-01", periods=n_dates, freq="B")

    # 价格：10~100 元区间随机游走
    base_prices = np.random.uniform(10, 100, size=len(symbols))
    price_data = np.column_stack([
        base_prices[i] * np.cumprod(1 + np.random.randn(n_dates) * 0.02)
        for i in range(len(symbols))
    ])
    price_df = pd.DataFrame(price_data, index=dates, columns=symbols)

    # 成交量：日均 50 万 ~ 2000 万股
    base_volumes = np.random.uniform(5e5, 2e7, size=len(symbols))
    volume_data = np.column_stack([
        base_volumes[i] * (1 + np.random.randn(n_dates) * 0.3).clip(min=0.1)
        for i in range(len(symbols))
    ])
    volume_df = pd.DataFrame(volume_data, index=dates, columns=symbols)

    # 策略股票池：取前 30 只
    universe = symbols[:30]

    print("=== 策略容量估算 ===")
    result = estimate_capacity(
        price_df=price_df,
        volume_df=volume_df,
        universe=universe,
        n_stocks=30,
        participation_rate=0.05,
        rebalance_days=20,
        turnover_fraction=0.3,
    )
    print(f"最大 AUM (CNY) : {result['capacity_cny']:,.0f}")
    print(f"最大 AUM (万元): {result['capacity_wan']:,.0f}")
    print(f"中位数 ADV (万元): {result['median_adv_per_stock']:,.0f}")
    print(f"流动性瓶颈股票 : {result['binding_stocks']}")
    print(f"参与率         : {result['participation_rate']:.0%}")
    print(f"摘要: {result['note']}")
    print()

    # 基本断言
    assert result["capacity_cny"] > 0, "容量应大于 0"
    assert result["capacity_wan"] == result["capacity_cny"] / 1e4, "万元换算应一致"
    assert len(result["binding_stocks"]) <= 5, "瓶颈股票最多 5 只"
    assert result["participation_rate"] == 0.05

    # 测试 StrategyCapacity 类
    print("=== StrategyCapacity 类测试 ===")
    sc = StrategyCapacity(
        price_df=price_df,
        volume_df=volume_df,
        universe=universe,
        n_stocks=10,
        participation_rate=0.03,
    )
    result2 = sc.compute()
    print(f"容量 (n=10, rate=3%): {result2['capacity_wan']:,.0f} 万元")
    # 更少股票 + 更低参与率 → 容量应更小
    assert result2["capacity_cny"] < result["capacity_cny"], \
        "更少股票+更低参与率下容量应更小"

    print("\n✅ capacity 模块验证通过")
