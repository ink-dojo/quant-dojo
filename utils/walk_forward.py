"""
滚动样本外验证模块
实现 walk-forward 交叉验证，逐步前移窗口进行策略评估
"""
import inspect
import logging
from typing import Callable, Dict, Any, Optional

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from utils.metrics import sharpe_ratio, max_drawdown

logger = logging.getLogger(__name__)


def walk_forward_test(
    strategy_fn: Callable,
    price_wide: pd.DataFrame,
    factor_data: Dict[str, Any],
    train_years: int = 3,
    test_months: int = 6,
) -> pd.DataFrame:
    """
    滚动样本外验证。逐步前移窗口，每次用 train_years 年训练，预测 test_months 个月。

    参数:
        strategy_fn: 策略函数，签名为 fn(price_wide, factor_data_slice, train_start, train_end) -> returns_series
        price_wide: 价格宽表 (日期 x 股票代码)，Index 为交易日期
        factor_data: 因子数据字典，可包含特征矩阵等
        train_years: 训练窗口大小（年），默认3年
        test_months: 测试窗口大小（月），默认6个月

    返回:
        DataFrame，包含每个窗口的回测结果：
        - train_start, train_end: 训练期始末
        - test_start, test_end: 测试期始末
        - sharpe: 测试期夏普比率
        - max_drawdown: 测试期最大回撤
        - total_return: 测试期总收益
        - n_periods: 测试期交易天数
    """
    # 获取排序的日期列表
    dates = sorted(price_wide.index)
    if len(dates) < 2:
        raise ValueError("price_wide 必须至少有 2 个交易日")

    # 计算窗口大小（交易日）
    train_days = int(train_years * 252)
    test_days = int(test_months * 21)
    step_days = test_days

    results = []

    # 滑动窗口
    train_idx = 0
    while train_idx + train_days < len(dates):
        train_end_idx = train_idx + train_days
        test_end_idx = min(train_end_idx + test_days, len(dates))

        # 如果测试窗口不足，停止
        if test_end_idx - train_end_idx < test_days:
            break

        train_start = dates[train_idx]
        train_end = dates[train_end_idx - 1]
        test_start = dates[train_end_idx]
        test_end = dates[test_end_idx - 1]

        try:
            # 提取训练期和测试期的数据
            price_train = price_wide.loc[train_start:train_end]
            price_test = price_wide.loc[test_start:test_end]

            # 如果有 factor_data 的时间切片需求，在这里处理
            # 假设 factor_data 支持切片或按日期索引
            factor_slice = factor_data if isinstance(factor_data, dict) else factor_data.loc[train_start:test_end]

            # 调用策略函数进行训练和测试
            # 返回测试期的日收益率
            full_slice = price_wide.loc[train_start:test_end]
            sig = inspect.signature(strategy_fn)
            n_params = len(sig.parameters)

            # 兼容旧 notebook 中的四参 wrapper，以及新版六参接口。
            if n_params <= 4:
                test_returns = strategy_fn(
                    full_slice,
                    factor_slice,
                    train_start,
                    train_end,
                )
            else:
                test_returns = strategy_fn(
                    full_slice,
                    factor_slice,
                    train_start,
                    train_end,
                    test_start,
                    test_end,
                )

            # 确保返回值是 pd.Series
            if not isinstance(test_returns, pd.Series):
                logger.warning(f"窗口 {train_start} ~ {test_end}: strategy_fn 返回值非 Series，跳过")
                results.append({
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "sharpe": np.nan,
                    "max_drawdown": np.nan,
                    "total_return": np.nan,
                    "n_periods": len(test_returns) if hasattr(test_returns, '__len__') else np.nan,
                })
            else:
                # 计算测试期指标
                if len(test_returns) > 0:
                    sr = sharpe_ratio(test_returns)
                    mdd = max_drawdown(test_returns)
                    total_ret = (1 + test_returns).prod() - 1
                    n_periods = len(test_returns)
                else:
                    sr = mdd = total_ret = np.nan
                    n_periods = 0

                results.append({
                    "train_start": train_start,
                    "train_end": train_end,
                    "test_start": test_start,
                    "test_end": test_end,
                    "sharpe": sr,
                    "max_drawdown": mdd,
                    "total_return": total_ret,
                    "n_periods": n_periods,
                })

                logger.info(
                    f"窗口 {train_start.date()} ~ {test_end.date()}: "
                    f"sharpe={sr:.2f}, mdd={mdd:.2%}, ret={total_ret:.2%}"
                )

        except Exception as e:
            logger.error(f"窗口 {train_start} ~ {test_end} 处理异常: {e}")
            results.append({
                "train_start": train_start,
                "train_end": train_end,
                "test_start": test_start,
                "test_end": test_end,
                "sharpe": np.nan,
                "max_drawdown": np.nan,
                "total_return": np.nan,
                "n_periods": np.nan,
            })

        # 步进
        train_idx += step_days

    if not results:
        raise ValueError("无法生成任何有效的测试窗口")

    return pd.DataFrame(results)


def plot_walk_forward_results(wf_df: pd.DataFrame, figsize: tuple = (14, 6)) -> None:
    """
    绘制滚动样本外验证结果。展示夏普比率和最大回撤的时间序列。

    参数:
        wf_df: walk_forward_test() 返回的结果 DataFrame
        figsize: 图表大小
    """
    fig, axes = plt.subplots(2, 2, figsize=figsize)

    # 夏普比率时间序列
    ax = axes[0, 0]
    valid_sharpe = wf_df[wf_df["sharpe"].notna()]
    if not valid_sharpe.empty:
        ax.plot(valid_sharpe.index, valid_sharpe["sharpe"], marker="o", linestyle="-", linewidth=2)
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax.set_title("测试期夏普比率", fontweight="bold")
        ax.set_ylabel("Sharpe Ratio")
        ax.grid(True, alpha=0.3)
    else:
        ax.text(0.5, 0.5, "无有效数据", ha="center", va="center", transform=ax.transAxes)

    # 最大回撤时间序列
    ax = axes[0, 1]
    valid_mdd = wf_df[wf_df["max_drawdown"].notna()]
    if not valid_mdd.empty:
        ax.plot(valid_mdd.index, valid_mdd["max_drawdown"], marker="s", linestyle="-", linewidth=2, color="red")
        ax.axhline(y=0, color="gray", linestyle="--", alpha=0.5)
        ax.set_title("测试期最大回撤", fontweight="bold")
        ax.set_ylabel("Max Drawdown")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.grid(True, alpha=0.3)
    else:
        ax.text(0.5, 0.5, "无有效数据", ha="center", va="center", transform=ax.transAxes)

    # 总收益时间序列
    ax = axes[1, 0]
    valid_ret = wf_df[wf_df["total_return"].notna()]
    if not valid_ret.empty:
        colors = ["green" if x > 0 else "red" for x in valid_ret["total_return"]]
        ax.bar(valid_ret.index, valid_ret["total_return"], color=colors, alpha=0.7)
        ax.axhline(y=0, color="gray", linestyle="-", linewidth=0.5)
        ax.set_title("测试期总收益", fontweight="bold")
        ax.set_ylabel("Total Return")
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
        ax.grid(True, alpha=0.3, axis="y")
    else:
        ax.text(0.5, 0.5, "无有效数据", ha="center", va="center", transform=ax.transAxes)

    # 统计摘要
    ax = axes[1, 1]
    ax.axis("off")

    valid_data = wf_df[wf_df["sharpe"].notna()]
    if not valid_data.empty:
        summary_text = (
            f"滚动验证摘要\n"
            f"{'=' * 25}\n"
            f"窗口总数: {len(wf_df)}\n"
            f"有效窗口: {len(valid_data)}\n"
            f"\n夏普比率:\n"
            f"  均值: {valid_data['sharpe'].mean():.2f}\n"
            f"  中位数: {valid_data['sharpe'].median():.2f}\n"
            f"  标准差: {valid_data['sharpe'].std():.2f}\n"
            f"\n最大回撤:\n"
            f"  均值: {valid_data['max_drawdown'].mean():.2%}\n"
            f"  最小（最差）: {valid_data['max_drawdown'].min():.2%}\n"
            f"\n总收益:\n"
            f"  均值: {valid_data['total_return'].mean():.2%}\n"
            f"  胜率: {(valid_data['total_return'] > 0).mean():.0%}\n"
        )
    else:
        summary_text = "无有效数据"

    ax.text(0.1, 0.9, summary_text, fontfamily="monospace", fontsize=10,
            verticalalignment="top", transform=ax.transAxes)

    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    print("=" * 60)
    print("滚动样本外验证工具 (Walk-Forward Validation)")
    print("=" * 60)
    print("""
使用示例:

    from utils.walk_forward import walk_forward_test, plot_walk_forward_results
    import pandas as pd

    # 1. 定义策略函数
    def my_strategy(price_wide, factor_data, train_start, train_end, test_start, test_end):
        '''
        在 train_start ~ train_end 上训练因子，
        返回 test_start ~ test_end 期间的日收益率 Series
        '''
        # ... 训练逻辑 ...
        # returns_series = ...
        return returns_series

    # 2. 准备数据
    # price_wide: DataFrame，行为日期，列为股票代码，值为价格
    # factor_data: 因子相关数据字典或 DataFrame

    # 3. 运行滚动验证
    wf_results = walk_forward_test(
        strategy_fn=my_strategy,
        price_wide=price_wide,
        factor_data=factor_data,
        train_years=3,
        test_months=6
    )

    # 4. 查看结果
    print(wf_results)

    # 5. 绘图
    plot_walk_forward_results(wf_results)

返回的 DataFrame 包含每个窗口的：
  - train_start, train_end: 训练期时间段
  - test_start, test_end: 测试期时间段
  - sharpe: 测试期夏普比率
  - max_drawdown: 测试期最大回撤
  - total_return: 测试期总收益
  - n_periods: 测试期交易天数
    """)
    print("=" * 60)
