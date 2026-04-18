"""
限售股解禁 v2 — event-triggered 持仓构造 (2026-04-18).

预注册: 解禁 v1 的 FAIL 发现 gross Sharpe=1.88 但 43% 年化成本吃掉全部 alpha.
       v2 改进: 事件触发建仓, 窗口内不 re-rank, 大幅降低 turnover.

**这是一个新的 hypothesis trial (DSR n_trials = 14), 不是 v1 的 re-tune.**
v1 spec 的网络结果已落档 (不改), v2 是平行对照的新 spec.

### v2 spec (零自由度)
- 事件 = 解禁日 T, signal = pct_of_float (同 v1)
- **portfolio construction 改变**:
  - 每个交易日 T-5 收盘: 筛选 next 5 天内解禁的股票, 按 pct_of_float 排序
  - Top 30% 解禁股票加入 "pending short" (5 日内开盘入场)
  - Bottom 30% 解禁股票加入 "pending long"
  - 入场后持仓 5 日, 到期平仓, **不因新事件到来 re-rank 已有持仓**
  - 组合上限: 无硬性 cap, 位置权重 = 1/n_current (各 leg 等权)
- 成本 = 单边 0.15%
- 其他 admission gates 同 v1

### 与 v1 差异总结
| 维度 | v1 | v2 |
|:-|:-|:-|
| 分层判断 | 每日 cross-section rank | 事件发生时 snapshot rank |
| 持仓更新 | 每日 re-rank 重建组合 | 开仓锁定 5 日, 到期平仓 |
| turnover 结构 | O(新事件/天) ≈ 1.137 | O(新事件/5日) ≈ 0.4-0.5 (预期) |
| 理论基础 | cross-sectional factor | event study |

### 失败红线
- 不 re-tune v2 spec 任何数字
- v2 fail → 试 指数调仓 或 回购 (减持 数据 broken)
- v2 pass → 触发 paper-trade forward OOS
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

PRE_WINDOW = 5
HOLD_DAYS = 5
TOP_PCT = 0.30
BOT_PCT = 0.30
TXN_ROUND_TRIP = 0.003
SIGNAL_COL = "pct_of_float"


def load_events() -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df["release_date"] = pd.to_datetime(df["release_date"])
    df = df.dropna(subset=["release_date", SIGNAL_COL])
    df = df[df[SIGNAL_COL] > 0]
    return df


def build_event_triggered_weights(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    pre_window: int = PRE_WINDOW,
    hold_days: int = HOLD_DAYS,
) -> pd.DataFrame:
    """
    事件触发的权重矩阵: date × symbol.

    对每个月 (分桶近似 cross-section 时间窗), 全月所有解禁事件按 pct_of_float
    分 top 30% / bottom 30%. top → short, bottom → long.
    开仓日 = 事件前 pre_window 个交易日; 持仓 hold_days 后平仓.
    持仓期间不因新事件 re-rank.

    注: 用"月度事件池"做 rank 而不是"每日 snapshot 池", 因为任一日
        新增事件池都太稀疏 (median < 5), 无法 cross-section. 月度池
        平均 ~40 事件, 30% tail = 12 个, 与 v1 持仓规模一致, 但 v2 的
        是"锁定 5 日不动", v1 是"每日 re-rank".
    """
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values

    # 按月分桶事件, 每月内 cross-section rank
    events = events.copy()
    events["month"] = events["release_date"].dt.to_period("M")
    total_long, total_short = 0, 0

    for month, grp in events.groupby("month", observed=True):
        grp = grp.sort_values(SIGNAL_COL, ascending=False)
        n = len(grp)
        if n < 10:
            continue
        n_top = max(1, int(np.floor(n * TOP_PCT)))
        n_bot = max(1, int(np.floor(n * BOT_PCT)))
        top_rows = grp.iloc[:n_top]
        bot_rows = grp.iloc[-n_bot:]

        for _, r in top_rows.iterrows():
            t = np.datetime64(r["release_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = max(0, i_t - pre_window)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            # SHORT position: append, 不覆盖 (等权多 position 叠加)
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] -= 1.0
            total_short += 1

        for _, r in bot_rows.iterrows():
            t = np.datetime64(r["release_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = max(0, i_t - pre_window)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += 1.0
            total_long += 1

    logger.info(f"opened long={total_long}, short={total_short} positions across {len(events.groupby('month'))} months")

    # 每日归一化: long sleeve sum=1, short sleeve sum=-1 (市场中性 gross=2)
    long_mask = W.where(W > 0, 0)
    short_mask = W.where(W < 0, 0)

    long_sum = long_mask.sum(axis=1).replace(0, np.nan)
    short_sum = short_mask.sum(axis=1).replace(0, np.nan).abs()

    long_norm = long_mask.div(long_sum, axis=0)
    short_norm = short_mask.div(short_sum, axis=0)
    return (long_norm.fillna(0) + short_norm.fillna(0))


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    logger.info(f"prices: {prices.shape}")
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W = build_event_triggered_weights(events, rets.index)
    W = W.reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = (daily_gross - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Lockup_v2")
    print("\n" + "=" * 60)
    print(f"  解禁 v2 (event-triggered) OOS ({start} ~ {end})")
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
    print(f"  Gross ann (pre-cost): {annualized_return(daily_gross.loc[start:end].dropna()):.2%}")

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
    parser.add_argument("--output", default="research/event_driven/lockup_v2_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events()
    logger.info(f"events: {len(events)}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\n🟢 PASS — paper-trade forward OOS 候选")
    else:
        print("\n🔴 FAIL — 下一 event 方向")


if __name__ == "__main__":
    main()
