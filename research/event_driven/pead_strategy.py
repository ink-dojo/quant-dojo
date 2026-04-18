"""
PEAD 策略 — 预注册实现 (2026-04-18)

严格按 research/event_driven/README.md 的 spec, 零自由度:
  - 事件: 财报披露日 (实际披露, 非首次预约)
  - surprise: 净利润 YoY (akshare 直接给)
  - 持仓窗口: T+1 ~ T+20 (交易日)
  - 分层: cross-sectional top 30% long / bottom 30% short, 等权
  - 调仓: 日频 (每日重算当前持仓集合, 旧事件到期自动淘汰)
  - 成本: 单边 0.15% (双边 0.3%) 已扣
  - 无 overlay: 无 regime, 无 vol target, 无 stop-loss, 无行业中性化

失败判据 (不软化):
  ann < 15% OR sharpe < 0.8 OR mdd < -30% OR PSR < 0.95 → 方向 FAIL, 试下一个事件.

输入:
  - data/raw/events/_all_events_2018_2025.parquet (event_loader 产出)
  - 本地股价 via utils.local_data_loader.load_adj_price_wide

输出:
  - 策略日收益 Series
  - performance_summary + PSR + bootstrap CI

CLI:
  python -m research.event_driven.pead_strategy \
         --start 2018-01-01 --end 2025-12-31
"""
from __future__ import annotations

import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return,
    annualized_volatility,
    bootstrap_sharpe_ci,
    max_drawdown,
    performance_summary,
    probabilistic_sharpe,
    sharpe_ratio,
)

logger = logging.getLogger(__name__)

EVENTS_PARQUET = Path(__file__).parent.parent.parent / "data" / "raw" / "events" / "_all_events_2018_2025.parquet"

# 预注册常量 (不调!)
HOLDING_WINDOW = 20
TOP_PCT = 0.30
BOT_PCT = 0.30
TXN_ROUND_TRIP = 0.003  # 双边 0.3% (单边 0.15%)
SURPRISE_COL = "net_profit_yoy"


def load_events() -> pd.DataFrame:
    """读全量事件 DataFrame. event_loader.get_earning_announcements 已 quality_gate 过."""
    if not EVENTS_PARQUET.exists():
        raise FileNotFoundError(
            f"缺事件数据: {EVENTS_PARQUET}\n"
            f"先跑: python -c \"from utils.event_loader import get_earning_announcements; "
            f"df=get_earning_announcements(start='2018-01-01',end='2025-12-31'); "
            f"df.to_parquet('{EVENTS_PARQUET}', index=False)\""
        )
    df = pd.read_parquet(EVENTS_PARQUET)
    df["announce_date"] = pd.to_datetime(df["announce_date"])
    return df


def build_holdings_matrix(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    holding_window: int = HOLDING_WINDOW,
) -> pd.DataFrame:
    """
    把事件展开成日频 surprise 矩阵 (date × symbol).

    value: 若 date ∈ (announce_date, announce_date + holding_window 个交易日], 则 = surprise
           否则 NaN.
    同一 symbol 窗口内发生新公告 → 取最晚 (surprise 覆盖).

    注意: T+1 是第一个持仓日 (公告次交易日), T+20 是最后持仓日 (含).
    """
    df = events.dropna(subset=["announce_date", SURPRISE_COL]).copy()
    df = df.sort_values(["symbol", "announce_date"])
    symbols = sorted(df["symbol"].unique())

    signal = pd.DataFrame(
        np.nan, index=trading_days, columns=symbols, dtype=float
    )

    td_arr = trading_days.values  # ndarray datetime64[ns]
    for _, row in df.iterrows():
        ad = np.datetime64(row["announce_date"])
        # 第一个严格晚于 announce_date 的交易日 = T+1
        i0 = int(np.searchsorted(td_arr, ad, side="right"))
        i1 = i0 + holding_window
        if i0 >= len(td_arr):
            continue
        i1 = min(i1, len(td_arr))
        sym = row["symbol"]
        val = row[SURPRISE_COL]
        # 覆盖: 新公告覆盖旧 (按时间顺序遍历, 天然后者覆盖前者)
        signal.iloc[i0:i1, signal.columns.get_loc(sym)] = val

    return signal


def cross_sectional_weights(
    signal_today: pd.Series,
    top_pct: float = TOP_PCT,
    bot_pct: float = BOT_PCT,
) -> pd.Series:
    """
    当日 cross-section 分层 → L/S 权重 (sum long = +1, sum short = -1, market-neutral gross=2).

    返回 Series (index=symbol), value ∈ {+1/n_top, -1/n_bot, 0 或 NaN}.
    """
    s = signal_today.dropna()
    n = len(s)
    if n < 10:  # 当日可交易事件太少, 不足以 cross-section
        return pd.Series(0.0, index=signal_today.index)

    n_top = max(1, int(np.floor(n * top_pct)))
    n_bot = max(1, int(np.floor(n * bot_pct)))
    ranked = s.sort_values(ascending=False)
    top = ranked.iloc[:n_top].index
    bot = ranked.iloc[-n_bot:].index

    w = pd.Series(0.0, index=signal_today.index)
    w.loc[top] = 1.0 / n_top
    w.loc[bot] = -1.0 / n_bot
    return w


def run_backtest(
    events: pd.DataFrame,
    start: str,
    end: str,
) -> dict:
    """
    执行 OOS 回测, 返回 dict with returns + metrics.
    """
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"回测 universe: {len(universe)} 只股票 (出现过事件的)")

    logger.info(f"加载股价 {start} ~ {end} ...")
    prices = load_adj_price_wide(universe, start=start, end=end)
    if prices.empty:
        raise RuntimeError("股价数据空, 检查本地 CSV 是否覆盖该区间")
    logger.info(f"价格表: {prices.shape}, 时间 {prices.index.min()} ~ {prices.index.max()}")

    # 日收益
    rets = prices.pct_change()
    # 把 |收益| > 0.11 的当作脏数据/涨跌停外 (A 股日内 10% 涨跌停, 允许少量 tolerance)
    rets = rets.where(rets.abs() < 0.25)

    # signal matrix: 日频, index = 交易日
    trading_days = rets.index
    signal = build_holdings_matrix(events, trading_days)
    signal = signal.reindex(columns=prices.columns)  # 对齐 universe
    logger.info(f"signal matrix: {signal.shape}, non-NaN 单元格占比 {signal.notna().mean().mean():.2%}")

    # 日频权重 (T 日权重, 用于 T+1 日收益 = shift(-1) 或直接 element-wise: w_t * r_{t+1})
    # 用 apply 按行生成权重
    weights = signal.apply(cross_sectional_weights, axis=1)

    # 策略收益 = sum(w_t * r_{t+1}), 即 w shift(1) 与 r 对齐 (严格避免 look-ahead:
    # w_t 在 T 日收盘用 T 日公告信息计算, T+1 日开盘按 w_t 成交, 取 T+1 日收益)
    w_exec = weights.shift(1)  # T 日的权重到 T+1 日才执行
    daily_ls_ret = (w_exec * rets).sum(axis=1)

    # 交易成本: turnover = Σ|Δw| 天然已含双边 (卖+买 各算一次 = 2 × 单边换手)
    # 所以乘 单边 0.15% 即为总成本. 等价于 round-trip 0.3% × (turnover/2)
    turnover = (w_exec.diff().abs().sum(axis=1)).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = daily_ls_ret - daily_cost
    net_ret = net_ret.loc[start:end].dropna()

    summary = performance_summary(net_ret, name="PEAD_L/S")
    print("\n" + "=" * 60)
    print(f"  PEAD 预注册 OOS 结果 ({start} ~ {end})")
    print("=" * 60)
    print(summary.to_string())

    ann = annualized_return(net_ret)
    sr = sharpe_ratio(net_ret)
    mdd = max_drawdown(net_ret)
    psr = probabilistic_sharpe(net_ret, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(net_ret, n_boot=2000)

    gate = {
        "ann>15%": ann > 0.15,
        "sharpe>0.8": sr > 0.8,
        "mdd>-30%": mdd > -0.30,
        "PSR>0.95": psr > 0.95,
        "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    print("\n=== 预注册 Admission Gate ===")
    for k, v in gate.items():
        print(f"  {'✅' if v else '❌'} {k}")

    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率均值 = {turnover.loc[start:end].mean():.3f}/日")
    print(f"  平均持仓数 = long {(w_exec > 0).sum(axis=1).mean():.0f}, short {(w_exec < 0).sum(axis=1).mean():.0f}")

    return {
        "returns": net_ret,
        "gross_returns": daily_ls_ret.loc[start:end].dropna(),
        "weights": w_exec,
        "summary": summary,
        "ann": ann,
        "sharpe": sr,
        "mdd": mdd,
        "psr": psr,
        "bootstrap": boot,
        "gate": gate,
        "pass": all(gate.values()),
    }


def main():
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="research/event_driven/pead_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events()
    logger.info(f"加载事件: {len(events)} 行, {events['symbol'].nunique()} unique symbols")

    result = run_backtest(events, args.start, args.end)

    # 落盘日度 P&L 供后续 DSR / 诊断
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"日度 P&L 落盘: {args.output}")

    if result["pass"]:
        print("\n🟢 预注册 admission PASS — 进入 paper-trade forward OOS")
    else:
        print("\n🔴 预注册 admission FAIL — 按结果判读预案处理 (不 re-tune)")


if __name__ == "__main__":
    main()
