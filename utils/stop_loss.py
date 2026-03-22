"""
止损管理模块
支持个股跌幅止损和组合回撤止损
所有函数接受日收益率 Series，返回修改后的日收益率 Series（相同 index）
"""
import numpy as np
import pandas as pd


def trailing_stop(
    portfolio_ret: pd.Series,
    threshold: float = -0.10,
) -> pd.Series:
    """
    个股跌幅止损：从最近高点回撤超过 threshold 时清仓（输出0收益）

    逐日独立判断：
    - 计算从历史最高点到当日的回撤
    - 如果当日回撤 < threshold（例如 -10%），则保留该日收益
    - 否则输出 0（止损触发，清仓）

    参数:
        portfolio_ret: 日收益率 Series，如 [0.01, -0.02, 0.015, ...]
        threshold: 回撤触发阈值，默认 -0.10（-10%）

    返回:
        修改后的日收益率 Series，止损触发的日期返回 0
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    # 计算累计收益
    cumulative = (1 + portfolio_ret).cumprod()

    # 计算运行最高值（从开始到当日）
    running_max = cumulative.cummax()

    # 计算从最高点的回撤
    drawdown = (cumulative - running_max) / running_max

    # 触发止损的日期（回撤低于 threshold）
    stop_triggered = drawdown < threshold

    # 输出：止损触发的日期为 0，否则保留原收益
    result = portfolio_ret.copy()
    result[stop_triggered] = 0.0

    return result


def portfolio_stop(
    portfolio_ret: pd.Series,
    max_drawdown: float = -0.20,
) -> pd.Series:
    """
    组合止损：累计回撤超过 max_drawdown 时清仓直到恢复

    状态机：
    - in_market = True（初始在市）
    - 当累计回撤 < max_drawdown 时，设置 in_market = False（清仓）
    - 当 in_market = False 且累计净值创新高时，恢复 in_market = True

    清仓期间返回 0（无收益），恢复后保留原收益。

    参数:
        portfolio_ret: 日收益率 Series
        max_drawdown: 组合止损阈值，默认 -0.20（-20%）

    返回:
        修改后的日收益率 Series
    """
    if len(portfolio_ret) == 0:
        return portfolio_ret.copy()

    # 计算累计净值
    cumulative = (1 + portfolio_ret).cumprod()

    # 初始化状态和结果
    result = portfolio_ret.copy()
    in_market = True
    peak = cumulative.iloc[0]  # 历史最高净值

    for i in range(len(portfolio_ret)):
        current_nav = cumulative.iloc[i]

        # 如果在市，检查是否触发止损
        if in_market:
            drawdown = (current_nav - peak) / peak
            if drawdown < max_drawdown:
                # 触发止损
                in_market = False
                result.iloc[i] = 0.0
            else:
                # 更新历史高点
                if current_nav > peak:
                    peak = current_nav
        else:
            # 清仓状态，检查是否恢复
            if current_nav > peak:
                # 净值创新高，恢复在市
                in_market = True
                peak = current_nav
            else:
                # 还在清仓，返回 0
                result.iloc[i] = 0.0

    return result


if __name__ == "__main__":
    # 冒烟测试
    import numpy as np

    # 构造模拟收益序列
    np.random.seed(42)
    dates = pd.date_range("2024-01-01", periods=100)
    daily_ret = pd.Series(np.random.randn(100) * 0.01, index=dates)  # 日收益 ±1%

    # 测试 trailing_stop
    stopped_ret = trailing_stop(daily_ret, threshold=-0.10)
    assert len(stopped_ret) == len(daily_ret), "返回长度错误"
    assert stopped_ret.index.equals(daily_ret.index), "index 不匹配"
    # 检查是否有 0 的日期
    zero_days = (stopped_ret == 0).sum()
    print(f"✅ trailing_stop OK | 输入长度={len(daily_ret)}, 触发止损天数={zero_days}")

    # 测试 portfolio_stop
    stopped_ret2 = portfolio_stop(daily_ret, max_drawdown=-0.20)
    assert len(stopped_ret2) == len(daily_ret), "返回长度错误"
    assert stopped_ret2.index.equals(daily_ret.index), "index 不匹配"
    zero_days2 = (stopped_ret2 == 0).sum()
    print(f"✅ portfolio_stop OK | 输入长度={len(daily_ret)}, 清仓天数={zero_days2}")

    # 测试空序列
    empty_ret = pd.Series([], dtype=float)
    assert trailing_stop(empty_ret).empty, "空序列处理错误"
    assert portfolio_stop(empty_ret).empty, "空序列处理错误"
    print(f"✅ 边界情况处理 OK")

    # 测试极端场景：所有正收益
    all_positive = pd.Series([0.01] * 50, index=pd.date_range("2024-01-01", periods=50))
    stopped_positive = trailing_stop(all_positive, threshold=-0.10)
    assert (stopped_positive == all_positive).all(), "全正收益不应触发止损"
    print(f"✅ 极端场景（全正收益）OK")

    # 测试极端场景：单次大幅回撤
    sharp_drawdown = pd.Series([0.05, 0.05, -0.15, 0.02, 0.02], dtype=float)
    stopped_sharp = trailing_stop(sharp_drawdown, threshold=-0.10)
    # 第 3 个回报应该被触发（累计下跌超过 -10%）
    assert stopped_sharp.iloc[2] == 0.0, "大幅回撤应该触发止损"
    print(f"✅ 极端场景（大幅回撤）OK")

    print("\n✅ 止损管理模块冒烟测试通过")
