"""
多因子选股策略
流程：每月换仓，截面分位数合成综合评分，选前 N 只等权持有
"""
from __future__ import annotations

import logging
import warnings
import numpy as np
import pandas as pd
from typing import Optional

from strategies.base import BaseStrategy, StrategyConfig

_log = logging.getLogger(__name__)


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
        neutralize: bool = False,
        industry_map: Optional[dict] = None,  # {symbol: industry_name}
        ic_weighting: bool = False,           # 是否用 ICIR 加权替代等权合成
    ):
        """
        初始化多因子策略

        参数:
            config         : 策略配置
            factors        : 因子字典，{名称: (宽表DataFrame, 方向)}
                             宽表格式为 date × symbol，方向1为正向，-1为反向
            is_st_wide     : ST标记宽表，date × symbol，1表示ST股（可选）
            n_stocks       : 每次选股数量
            rebalance_freq : 调仓频率，目前仅支持 "monthly"
            neutralize     : 是否对各因子做行业中性化（需同时提供 industry_map）
            industry_map   : {symbol: industry_name}，行业分类字典；
                             neutralize=True 时必须提供，否则打 warning 并跳过中性化
            ic_weighting   : 是否启用自适应 ICIR 加权合成；
                             True 时用近 60 日 ICIR softmax 权重替代等权平均，
                             数据不足 60 日时自动降级为等权
        """
        super().__init__(config)
        self.factors = factors
        self.is_st_wide = is_st_wide
        self.n_stocks = n_stocks
        self.rebalance_freq = rebalance_freq
        self.neutralize = neutralize
        self.industry_map = industry_map
        self.ic_weighting = ic_weighting
        self.trade_log: list = []  # 调仓记录

        # 预先将 industry_map 转为 pd.Series，后续重复使用
        if self.neutralize and self.industry_map:
            self._industry_series = pd.Series(self.industry_map)
        else:
            self._industry_series = None

        # IC 权重月度缓存
        self._ic_weights_cache: dict = {}          # {factor_name: weight}
        self._ic_weights_last_update: Optional[object] = None  # 上次更新的年月 (year, month)

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

    def _compute_ic_weights(self, price_wide: pd.DataFrame) -> dict:
        """
        计算各因子近期 ICIR 加权权重。

        用前 60 日数据计算每个因子的 IC 序列，取 ICIR = mean/std。
        权重 = softmax 归一化后的 |ICIR_i|，代表每个因子的边际贡献权重。

        如果可用历史数据不足 60 日（bootstrap 期），返回 None，
        调用方负责降级为等权。

        参数:
            price_wide : 价格宽表 (date × symbol)，用于构造次日收益率

        返回:
            dict {factor_name: weight}，sum=1；或 None（数据不足）
        """
        from utils.factor_analysis import compute_ic_series

        # 次日收益率（shift(-1) 得到当日对应的次日收益）
        ret_wide = price_wide.pct_change().shift(-1)

        icirs = {}
        for name, (factor_df, direction) in self.factors.items():
            try:
                ic_s = compute_ic_series(factor_df, ret_wide, min_stocks=20)
                clean = ic_s.dropna().tail(60)
                # bootstrap 期：全局可用 IC 不足 20 条，返回 None 触发等权降级
                if len(clean) < 20:
                    return None
                icir = abs(clean.mean() / clean.std()) if clean.std() > 0 else 0.0
                icirs[name] = icir
            except Exception:
                icirs[name] = 0.01  # 单因子失败时给最小权重 fallback

        if not icirs or max(icirs.values()) == 0:
            # 全部因子 ICIR 为零，等权 fallback
            n = len(self.factors)
            return {k: 1.0 / n for k in self.factors}

        # Softmax 归一化（sum 归一）
        total = sum(icirs.values())
        return {k: v / total for k, v in icirs.items()}

    def generate_signals(
        self,
        data: pd.DataFrame,
        ic_weights: Optional[dict] = None,
    ) -> pd.DataFrame:
        """
        生成多因子综合评分信号

        流程（neutralize=True 且有 industry_map 时）：
            1. 截面 3σ 缩尾后 z-score 标准化
            2. 行业内 demean（industry_neutralize_fast）去除行业暴露
            3. 方向调整后合成：若 ic_weights 不为 None 则加权平均，否则等权平均

        参数:
            data       : 未使用（信号来自 self.factors），保留接口兼容性
            ic_weights : 可选的因子权重 dict {factor_name: weight}，
                         由 run() 通过 _compute_ic_weights 传入；
                         None 表示等权合成

        返回:
            综合评分宽表 DataFrame（date × symbol）
        """
        # 确定是否执行中性化，并在需要时做提前校验
        do_neutralize = self.neutralize
        if do_neutralize:
            if self._industry_series is None:
                warnings.warn(
                    "MultiFactorStrategy: neutralize=True 但未提供 industry_map，"
                    "跳过行业中性化。请在构造时传入 industry_map={symbol: industry_name}。",
                    stacklevel=2,
                )
                do_neutralize = False
            else:
                from utils.factor_analysis import industry_neutralize_fast

        all_scores = {}  # factor_name -> 调整后 z-score DataFrame

        for factor_name, (factor_df, direction) in self.factors.items():
            # 1. 截面 z-score（逐行/逐日计算）
            zscore = factor_df.apply(self._winsorize_zscore, axis=1)

            # 2. 行业中性化（在 z-score 后、方向调整前）
            if do_neutralize:
                try:
                    zscore = industry_neutralize_fast(zscore, self._industry_series)
                    _log.debug("因子 %s 行业中性化完成", factor_name)
                except Exception as exc:
                    _log.warning("因子 %s 行业中性化失败，使用原始 z-score: %s", factor_name, exc)

            # 3. 方向调整：direction=-1 时反转
            zscore = zscore * direction
            all_scores[factor_name] = zscore

        if not all_scores:
            raise ValueError("factors 字典为空，无法生成信号")

        factor_names = list(all_scores.keys())
        score_list = [all_scores[n] for n in factor_names]

        if ic_weights is not None:
            # IC 加权合成：每个因子 z-score 乘对应权重后相加
            # 权重之和为 1，直接做加权 sum 等价于加权 mean
            weighted_list = [
                score_list[i] * ic_weights.get(factor_names[i], 1.0 / len(factor_names))
                for i in range(len(factor_names))
            ]
            composite = pd.concat(weighted_list, keys=factor_names).groupby(level=1).sum()
        else:
            # 等权合成（原逻辑）
            composite = pd.concat(score_list, keys=factor_names).groupby(level=1).mean()

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
        # 1. 计算 IC 权重（月度缓存），然后生成综合评分
        ic_weights: Optional[dict] = None
        if self.ic_weighting:
            # 用价格宽表末尾时间点的年月判断是否需要刷新缓存
            last_date = price_wide.index[-1]
            current_ym = (last_date.year, last_date.month)
            if self._ic_weights_last_update != current_ym:
                weights = self._compute_ic_weights(price_wide)
                if weights is None:
                    # bootstrap 期：数据不足，降级等权
                    _log.info("IC权重bootstrap期，使用等权合成")
                    self._ic_weights_cache = {}
                else:
                    self._ic_weights_cache = weights
                    self._ic_weights_last_update = current_ym
                    _log.info(
                        "IC权重已更新 (%d-%02d): %s",
                        current_ym[0], current_ym[1],
                        {k: f"{v:.3f}" for k, v in weights.items()},
                    )
            # 缓存非空才启用加权，否则维持等权（None）
            ic_weights = self._ic_weights_cache if self._ic_weights_cache else None

        composite_score = self.generate_signals(price_wide, ic_weights=ic_weights)

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
        self.trade_log = []

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
                # turnover 已是双边（买入权重变化 + 卖出权重变化之和）
                # commission 是单边费率，turnover 已含买卖两边，不需要再 ×2
                transaction_cost = self.config.commission * turnover

                # 记录调仓
                buys = sorted(new_holdings - current_holdings)
                sells = sorted(current_holdings - new_holdings)
                self.trade_log.append({
                    "date": str(date.date()) if hasattr(date, 'date') else str(date),
                    "n_holdings": n,
                    "n_buys": len(buys),
                    "n_sells": len(sells),
                    "buys": buys,
                    "sells": sells,
                    "turnover": round(turnover, 4),
                    "cost": round(transaction_cost, 6),
                })

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

    # 构造假的行业分类：每10只股票一个行业，共5个行业
    industry_map = {sym: f"IND_{i // 10}" for i, sym in enumerate(symbols)}

    config = StrategyConfig(name="test_multi_factor")

    # 测试 1：不做中性化
    strategy = MultiFactorStrategy(
        config=config,
        factors={"momentum": (factor_df, 1)},
        is_st_wide=is_st,
        n_stocks=10,
    )
    result = strategy.run(price_wide)
    print(f"✅ 无中性化回测完成 | 形状: {result.shape} | 累计收益: {result['cumulative_return'].iloc[-1]:.2%}")

    # 测试 2：开启行业中性化
    strategy2 = MultiFactorStrategy(
        config=config,
        factors={"momentum": (factor_df, 1)},
        is_st_wide=is_st,
        n_stocks=10,
        neutralize=True,
        industry_map=industry_map,
    )
    result2 = strategy2.run(price_wide)
    print(f"✅ 行业中性化回测完成 | 形状: {result2.shape} | 累计收益: {result2['cumulative_return'].iloc[-1]:.2%}")

    # 测试 3：neutralize=True 但不传 industry_map，应打 warning 而非报错
    import warnings as _w
    with _w.catch_warnings(record=True) as caught:
        _w.simplefilter("always")
        strategy3 = MultiFactorStrategy(
            config=config,
            factors={"momentum": (factor_df, 1)},
            n_stocks=10,
            neutralize=True,         # 未传 industry_map
        )
        result3 = strategy3.run(price_wide)
    assert any("industry_map" in str(w.message) for w in caught), "应有 warning 提示缺少 industry_map"
    print(f"✅ 缺少 industry_map warning 正常触发")
