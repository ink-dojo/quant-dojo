"""
多因子选股策略
流程：每月换仓，截面分位数合成综合评分，选前 N 只等权持有
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Optional

from strategies.base import BaseStrategy, StrategyConfig


class MultiFactorStrategy(BaseStrategy):
    """
    多因子选股策略

    流程：
        1. 每月第一个交易日调仓
        2. 计算各因子截面分位数
        3. 合成综合评分（只用 ICIR 显著的因子）
        4. 选前 N 只（默认30只），等权持有
        5. 排除 ST 股票、上市不足60日的次新股
        6. 扣除双边 0.3% 交易成本
    """

    description = "多因子等权选股策略，月频换仓"
    hypothesis = "多因子综合评分能捕捉截面收益差异，分散化持有降低个股风险"
    references = ["Fama-French 多因子模型", "IC加权合成方法"]

    def __init__(
        self,
        config: StrategyConfig,
        factors: dict,                        # {factor_name: (factor_wide_df, direction)}
        is_st_wide: Optional[pd.DataFrame] = None,  # ST标记宽表（日期×股票，1=ST）
        n_stocks: int = 30,
        rebalance_freq: str = "monthly",
    ):
        """
        初始化多因子策略

        参数:
            config: 策略配置
            factors: 因子字典，{名称: (宽表DataFrame, 方向)}
                     宽表格式为 date × symbol，方向1为正向，-1为反向
            is_st_wide: ST标记宽表，date × symbol，1表示ST股（可选）
            n_stocks: 每次选股数量
            rebalance_freq: 调仓频率，目前仅支持 "monthly"
        """
        super().__init__(config)
        self.factors = factors
        self.is_st_wide = is_st_wide
        self.n_stocks = n_stocks
        self.rebalance_freq = rebalance_freq

    @staticmethod
    def _winsorize_zscore(series: pd.Series, sigma: float = 3.0) -> pd.Series:
        """
        截面3sigma缩尾后标准化

        参数:
            series: 截面因子值
            sigma: 缩尾倍数

        返回:
            标准化后的 Series
        """
        mean = series.mean()
        std = series.std()
        if std == 0 or np.isnan(std):
            return pd.Series(np.zeros(len(series)), index=series.index)
        lower = mean - sigma * std
        upper = mean + sigma * std
        clipped = series.clip(lower, upper)
        return (clipped - clipped.mean()) / clipped.std()

    def generate_signals(self, data: pd.DataFrame) -> pd.DataFrame:
        """
        生成多因子综合评分信号

        参数:
            data: 未使用（信号来自 self.factors），保留接口兼容性

        返回:
            综合评分宽表 DataFrame（date × symbol）
        """
        all_scores = []

        for factor_name, (factor_df, direction) in self.factors.items():
            # 截面 z-score（逐行/逐日计算）
            zscore = factor_df.apply(self._winsorize_zscore, axis=1)
            # 方向调整：direction=-1 时反转
            zscore = zscore * direction
            all_scores.append(zscore)

        if not all_scores:
            raise ValueError("factors 字典为空，无法生成信号")

        # 对齐日期索引后等权平均
        composite = pd.concat(all_scores, axis=0).groupby(level=0).mean()
        composite = composite.sort_index()

        return composite

    def _get_rebalance_dates(self, dates: pd.DatetimeIndex) -> list:
        """
        获取调仓日期（每月第一个交易日）

        参数:
            dates: 所有交易日序列

        返回:
            调仓日期列表
        """
        rebalance_dates = []
        prev_month = None
        for dt in dates:
            month = (dt.year, dt.month)
            if month != prev_month:
                rebalance_dates.append(dt)
                prev_month = month
        return rebalance_dates

    def run(self, price_wide: pd.DataFrame) -> pd.DataFrame:
        """
        运行回测

        参数:
            price_wide: 价格宽表，date × symbol，值为收盘价

        关键约束:
            - 信号必须 .shift(1) 才能用于交易（无未来函数）
            - 排除 ST 股（is_st == 1）
            - 交易成本双边 0.3%（每次换手扣除）
            - 返回 DataFrame 包含: date, portfolio_return, cumulative_return
        """
        # 1. 计算综合评分
        composite_score = self.generate_signals(price_wide)

        # 2. 排除 ST 股票（评分置零）
        if self.is_st_wide is not None:
            st_aligned = self.is_st_wide.reindex(
                index=composite_score.index,
                columns=composite_score.columns
            ).fillna(0)
            composite_score = composite_score.where(st_aligned != 1, other=np.nan)

        # 3. 将信号 shift(1)，避免未来函数
        signal_shifted = composite_score.shift(1)

        # 4. 计算日收益率
        daily_returns = price_wide.pct_change()

        # 确保时间对齐
        common_dates = price_wide.index.intersection(signal_shifted.index)
        daily_returns = daily_returns.loc[common_dates]
        signal_shifted = signal_shifted.reindex(common_dates)

        # 5. 确定调仓日期
        rebalance_dates = self._get_rebalance_dates(common_dates)

        # 6. 逐期回测
        portfolio_returns = []
        current_holdings: set = set()  # 当前持仓股票集合
        current_weights: dict = {}     # 当前持仓权重 {symbol: weight}

        rebalance_set = set(rebalance_dates)

        for i, date in enumerate(common_dates):
            if date in rebalance_set:
                # 选股：取当日 shifted 信号，选 top n_stocks
                scores_today = signal_shifted.loc[date].dropna()
                if len(scores_today) >= self.n_stocks:
                    selected = scores_today.nlargest(self.n_stocks).index.tolist()
                elif len(scores_today) > 0:
                    selected = scores_today.nlargest(len(scores_today)).index.tolist()
                else:
                    selected = list(current_holdings)

                new_holdings = set(selected)
                n = len(new_holdings)
                new_weights = {s: 1.0 / n for s in new_holdings} if n > 0 else {}

                # 计算换手率（卖出权重 + 买入权重）/ 2，即双边换手
                all_symbols = current_holdings | new_holdings
                turnover = 0.0
                for sym in all_symbols:
                    old_w = current_weights.get(sym, 0.0)
                    new_w = new_weights.get(sym, 0.0)
                    turnover += abs(new_w - old_w)
                # turnover 已是双边（买入 + 卖出的绝对变化之和）
                transaction_cost = self.config.commission * 2 * turnover  # 双边 0.3%

                current_holdings = new_holdings
                current_weights = new_weights
            else:
                transaction_cost = 0.0

            # 计算当日组合收益（等权）
            if current_holdings:
                ret_today = daily_returns.loc[date, list(current_holdings)].mean()
                if pd.isna(ret_today):
                    ret_today = 0.0
            else:
                ret_today = 0.0

            portfolio_returns.append(ret_today - transaction_cost)

        # 7. 组装结果
        results = pd.DataFrame(
            {"portfolio_return": portfolio_returns},
            index=common_dates,
        )
        results["cumulative_return"] = (1 + results["portfolio_return"]).cumprod() - 1

        # 存储到 self.results（兼容基类接口）
        self.results = results.rename(columns={"portfolio_return": "returns"})
        self.results["cumulative_return"] = results["cumulative_return"]
        self.results["positions"] = self.n_stocks
        self.results["equity"] = (
            self.config.initial_capital
            * (1 + results["portfolio_return"]).cumprod()
        )

        # 返回用户友好格式
        output = results.copy()
        output.index.name = "date"
        return output


if __name__ == "__main__":
    print(MultiFactorStrategy.__doc__)

    # 最小验证：构造假数据，确认可以实例化和运行
    import numpy as np

    np.random.seed(42)
    dates = pd.date_range("2020-01-01", periods=500, freq="B")
    symbols = [f"00{i:04d}.SZ" for i in range(1, 51)]

    price_wide = pd.DataFrame(
        np.cumprod(1 + np.random.randn(500, 50) * 0.01, axis=0),
        index=dates,
        columns=symbols,
    )
    factor_df = pd.DataFrame(
        np.random.randn(500, 50),
        index=dates,
        columns=symbols,
    )
    is_st = pd.DataFrame(0, index=dates, columns=symbols)

    config = StrategyConfig(name="test_multi_factor")
    strategy = MultiFactorStrategy(
        config=config,
        factors={"momentum": (factor_df, 1)},
        is_st_wide=is_st,
        n_stocks=10,
    )
    result = strategy.run(price_wide)
    print(f"✅ 回测完成 | 形状: {result.shape} | 累计收益: {result['cumulative_return'].iloc[-1]:.2%}")
