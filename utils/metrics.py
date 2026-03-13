"""
绩效指标计算模块
所有函数接受 pd.Series（日收益率）作为输入
"""
import numpy as np
import pandas as pd


TRADING_DAYS = 252


def annualized_return(returns: pd.Series) -> float:
    """年化收益率"""
    total = (1 + returns).prod()
    n_years = len(returns) / TRADING_DAYS
    return total ** (1 / n_years) - 1


def annualized_volatility(returns: pd.Series) -> float:
    """年化波动率"""
    return returns.std() * np.sqrt(TRADING_DAYS)


def sharpe_ratio(returns: pd.Series, risk_free: float = 0.02) -> float:
    """夏普比率（默认无风险利率2%）"""
    excess = annualized_return(returns) - risk_free
    vol = annualized_volatility(returns)
    return excess / vol if vol != 0 else 0.0


def max_drawdown(returns: pd.Series) -> float:
    """最大回撤"""
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max
    return drawdown.min()


def calmar_ratio(returns: pd.Series) -> float:
    """卡玛比率 = 年化收益 / |最大回撤|"""
    mdd = abs(max_drawdown(returns))
    ann_ret = annualized_return(returns)
    return ann_ret / mdd if mdd != 0 else 0.0


def win_rate(returns: pd.Series) -> float:
    """胜率（日收益为正的比例）"""
    return (returns > 0).mean()


def profit_loss_ratio(returns: pd.Series) -> float:
    """盈亏比 = 平均盈利 / 平均亏损"""
    wins = returns[returns > 0].mean()
    losses = abs(returns[returns < 0].mean())
    return wins / losses if losses != 0 else float("inf")


def performance_summary(returns: pd.Series, name: str = "Strategy") -> pd.DataFrame:
    """
    输出完整绩效报告

    参数:
        returns: 日收益率 Series
        name: 策略名称

    返回:
        格式化的绩效表格
    """
    metrics = {
        "年化收益率": f"{annualized_return(returns):.2%}",
        "年化波动率": f"{annualized_volatility(returns):.2%}",
        "夏普比率": f"{sharpe_ratio(returns):.2f}",
        "最大回撤": f"{max_drawdown(returns):.2%}",
        "卡玛比率": f"{calmar_ratio(returns):.2f}",
        "胜率": f"{win_rate(returns):.2%}",
        "盈亏比": f"{profit_loss_ratio(returns):.2f}",
        "交易天数": len(returns),
    }
    return pd.DataFrame.from_dict(metrics, orient="index", columns=[name])
