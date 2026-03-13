"""
标准化可视化模块
所有图表风格统一，方便研究报告使用
"""
import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import seaborn as sns

# 全局风格
plt.rcParams["font.family"] = ["PingFang SC", "Helvetica", "sans-serif"]
plt.rcParams["axes.grid"] = True
plt.rcParams["grid.alpha"] = 0.3
plt.rcParams["figure.dpi"] = 120


def plot_cumulative_returns(
    returns_dict: dict,
    title: str = "累计收益对比",
    figsize: tuple = (12, 5),
):
    """
    绘制累计收益曲线（可多策略对比）

    参数:
        returns_dict: {"策略名": returns_series, ...}
        title: 图标题
    """
    fig, ax = plt.subplots(figsize=figsize)
    for name, returns in returns_dict.items():
        cum = (1 + returns).cumprod()
        ax.plot(cum.index, cum.values, label=name, linewidth=1.5)

    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("累计净值")
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    ax.legend()
    ax.axhline(y=1, color="gray", linestyle="--", linewidth=0.8)
    plt.tight_layout()
    return fig


def plot_drawdown(returns: pd.Series, title: str = "回撤曲线", figsize: tuple = (12, 4)):
    """绘制回撤曲线"""
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.cummax()
    drawdown = (cumulative - rolling_max) / rolling_max

    fig, ax = plt.subplots(figsize=figsize)
    ax.fill_between(drawdown.index, drawdown.values, 0, alpha=0.4, color="red")
    ax.plot(drawdown.index, drawdown.values, color="red", linewidth=1)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.set_ylabel("回撤幅度")
    ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0%}"))
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m"))
    plt.tight_layout()
    return fig


def plot_monthly_returns_heatmap(returns: pd.Series, figsize: tuple = (12, 6)):
    """绘制月度收益热力图"""
    monthly = returns.resample("ME").apply(lambda x: (1 + x).prod() - 1)
    monthly_df = monthly.to_frame("return")
    monthly_df["year"] = monthly_df.index.year
    monthly_df["month"] = monthly_df.index.month

    pivot = monthly_df.pivot(index="year", columns="month", values="return")
    pivot.columns = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    fig, ax = plt.subplots(figsize=figsize)
    sns.heatmap(
        pivot,
        annot=True,
        fmt=".1%",
        cmap="RdYlGn",
        center=0,
        ax=ax,
        linewidths=0.5,
    )
    ax.set_title("月度收益热力图", fontsize=14, fontweight="bold")
    plt.tight_layout()
    return fig


def plot_returns_distribution(returns: pd.Series, figsize: tuple = (10, 4)):
    """绘制收益率分布"""
    fig, ax = plt.subplots(figsize=figsize)
    returns.hist(bins=50, ax=ax, color="steelblue", alpha=0.7, edgecolor="white")
    ax.axvline(returns.mean(), color="red", linestyle="--", label=f"均值 {returns.mean():.2%}")
    ax.axvline(0, color="black", linestyle="-", linewidth=0.8)
    ax.set_title("收益率分布", fontsize=14, fontweight="bold")
    ax.set_xlabel("日收益率")
    ax.legend()
    plt.tight_layout()
    return fig
