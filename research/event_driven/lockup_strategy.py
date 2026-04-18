"""
限售股解禁 event-driven 策略 — 预注册实现 (2026-04-18).

严格按 research/event_driven/NEXT_STEPS.md 草案, 零自由度:
  - 事件: 限售股解禁日 T (akshare stock_restricted_release_detail_em)
  - signal: 占解禁前流通市值比例 (pct_of_float, 越大 = 卖压越重)
  - 持仓窗口: T-5 ~ T-1 (共 5 个交易日, 抢跑卖压)
  - 分层: cross-sectional top 30% short (高解禁比例 = 强卖压预期)
          bottom 30% long (低解禁比例 对照)
  - 成本: 单边 0.15%
  - 无 overlay, 无 neutralization, 无 size filter

失败判据:
  ann<15% OR sharpe<0.8 OR mdd<-30% OR PSR<0.95 → FAIL, 下一 event 方向.

假设: 解禁前 5 日, 市场已知 T 日供给冲击, 理性卖方提前 partially 卖出
      → 高 pct_of_float 股票 T-5~T-1 abnormal negative return.
      Short these → alpha. Low pct_of_float 对照组吸收不了市场 beta,
      所以 long them 主要是 market-neutral hedging.
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
    bootstrap_sharpe_ci,
    max_drawdown,
    performance_summary,
    probabilistic_sharpe,
    sharpe_ratio,
)

logger = logging.getLogger(__name__)

EVENTS_PARQUET = (
    Path(__file__).parent.parent.parent
    / "data" / "raw" / "events" / "_all_lockup_2018_2025.parquet"
)

# 预注册常量 (不调)
PRE_WINDOW = 5  # T-5 ~ T-1
TOP_PCT = 0.30
BOT_PCT = 0.30
TXN_ROUND_TRIP = 0.003
SIGNAL_COL = "pct_of_float"


def load_events() -> pd.DataFrame:
    if not EVENTS_PARQUET.exists():
        raise FileNotFoundError(f"缺解禁数据: {EVENTS_PARQUET}")
    df = pd.read_parquet(EVENTS_PARQUET)
    df["release_date"] = pd.to_datetime(df["release_date"])
    df = df.dropna(subset=["release_date", SIGNAL_COL])
    # 去除 pct_of_float <= 0 的坏数据
    df = df[df[SIGNAL_COL] > 0]
    return df


def build_pre_window_signal(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    pre_window: int = PRE_WINDOW,
) -> pd.DataFrame:
    """
    对每个解禁事件 T, 填入 [T-pre_window, T-1] 的 signal 值到矩阵.
    同一 symbol 窗口内若多个事件重叠, 取 MAX signal (最大卖压主导).
    """
    symbols = sorted(events["symbol"].unique())
    signal = pd.DataFrame(np.nan, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values

    for _, row in events.iterrows():
        t = np.datetime64(row["release_date"])
        # T 日在交易日索引: 第一个 >= T 的位置 (T 可能不是交易日, 向后取)
        i_t = int(np.searchsorted(td_arr, t, side="left"))
        i0 = max(0, i_t - pre_window)
        i1 = i_t  # 不含 T 日本身 (策略是 T-1 平仓)
        if i0 >= i1:
            continue
        sym = row["symbol"]
        val = float(row[SIGNAL_COL])
        # MAX 而非覆盖: 窗口内重叠事件取最大卖压
        col = signal.iloc[i0:i1, signal.columns.get_loc(sym)]
        signal.iloc[i0:i1, signal.columns.get_loc(sym)] = np.where(
            col.isna() | (col < val), val, col
        )

    return signal


def cross_sectional_weights(
    signal_today: pd.Series,
    top_pct: float = TOP_PCT,
    bot_pct: float = BOT_PCT,
) -> pd.Series:
    """
    High signal (大解禁) → SHORT; Low signal → LONG.
    注意 PEAD 是 top long / bot short, 这里相反 (假设: 大解禁 → 跌).
    """
    s = signal_today.dropna()
    n = len(s)
    if n < 10:
        return pd.Series(0.0, index=signal_today.index)
    n_top = max(1, int(np.floor(n * top_pct)))
    n_bot = max(1, int(np.floor(n * bot_pct)))
    ranked = s.sort_values(ascending=False)
    top_high = ranked.iloc[:n_top].index  # 大解禁
    bot_low = ranked.iloc[-n_bot:].index  # 小解禁

    w = pd.Series(0.0, index=signal_today.index)
    w.loc[top_high] = -1.0 / n_top  # SHORT 大解禁
    w.loc[bot_low] = 1.0 / n_bot   # LONG 小解禁
    return w


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    logger.info(f"prices: {prices.shape}")
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    signal = build_pre_window_signal(events, rets.index)
    signal = signal.reindex(columns=prices.columns)
    logger.info(f"signal: {signal.shape}, non-NaN {signal.notna().mean().mean():.2%}")

    weights = signal.apply(cross_sectional_weights, axis=1)
    w_exec = weights.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = (daily_gross - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Lockup_L/S")
    print("\n" + "=" * 60)
    print(f"  解禁 预注册 OOS 结果 ({start} ~ {end})")
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
    print(f"  平均持仓数 = long {(w_exec > 0).sum(axis=1).mean():.1f}, short {(w_exec < 0).sum(axis=1).mean():.1f}")

    return {
        "returns": net_ret,
        "gross_returns": daily_gross.loc[start:end].dropna(),
        "ann": ann, "sharpe": sr, "mdd": mdd, "psr": psr,
        "bootstrap": boot, "gate": gate,
        "pass": all(gate.values()),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="research/event_driven/lockup_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events()
    logger.info(f"events: {len(events)}, symbols: {events['symbol'].nunique()}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\n🟢 预注册 admission PASS")
    else:
        print("\n🔴 预注册 admission FAIL — 试下一 event 方向")


if __name__ == "__main__":
    main()
