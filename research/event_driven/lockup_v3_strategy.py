"""
限售股解禁 v3 — fixed-unit event-triggered (2026-04-18).

预注册 (DSR trial #15). **不是 v2 的 re-tune**, 是 portfolio construction 的
结构性变体 (analog: switching from OLS to ridge, 同 features 同 label).

### 前因
- v1 (daily re-rank): gross ann 44.5%, net -11.96%, turnover 1.137 → 43% cost
- v2 (monthly bucket + 5d lock + daily renorm): gross 39.4%, net -3.70%,
  turnover 0.978 → 37% cost. 月度分桶未解决 turnover.
- root cause: 每日对 sum(W) 归一化, 新 event 进入稀释老 position 权重,
  每 position 天天产生小幅 turnover.

### v3 结构变更 (唯一一个变化)
不做 daily re-normalize. 每个 event 开仓时分配固定 UNIT_POS_WEIGHT,
持仓期间权重不变 (除非有新同 symbol event 叠加).

UNIT_POS_WEIGHT = 1/20 = 5%  (ex-ante 选: A股解禁月 ~57 事件,
top30%+bot30% = 34 events/月 ≈ 1.6 events/日 入场, × 5 日持仓 =
~8 concurrent positions. UNIT=5% → gross 40-80% 典型区间. 非 peek 选择.)

换手率数学期望:
- 每日新开仓 ≈ 1.6 events (top+bot)
- 每日平仓 ≈ 1.6 events (前 5 天的那批)
- 每笔 open/close = 5% weight change
- Turnover = 2 × 1.6 × 5% = 0.16/日 (vs v2 的 0.978)
- 成本 = 0.16 × 0.15% × 252 = 6.0% 年化 (vs v1 43%, v2 37%)

### 预期净表现 (ex ante, 不偷看)
gross expected ~35-40% (v1/v2 均值), 成本 ~6%,
净 ann 期望 28-33%, Sharpe 依赖波动结构.

### 失败红线
- v3 fail → **结论**: 解禁方向 3 次都 fail, 去试 回购 (接受 survivorship
  bias 作为已知 caveat), 如 回购也 fail → phase 3 日频 L/S 写死.
- v3 pass → paper-trade forward OOS

### DSR 累计
v34: 11, PEAD: 12, 解禁 v1: 13, 解禁 v2: 14, **v3: 15**
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
UNIT_POS_WEIGHT = 1.0 / 20  # fixed 5% per event, ex ante


def load_events() -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df["release_date"] = pd.to_datetime(df["release_date"])
    df = df.dropna(subset=["release_date", SIGNAL_COL])
    df = df[df[SIGNAL_COL] > 0]
    return df


def build_fixed_unit_weights(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    pre_window: int = PRE_WINDOW,
    hold_days: int = HOLD_DAYS,
    unit_weight: float = UNIT_POS_WEIGHT,
) -> pd.DataFrame:
    """
    Fixed-unit event-triggered portfolio construction.

    对每个月事件 cross-section rank, top 30% → UNIT short, bot 30% → UNIT long.
    入场在 T-pre_window, 持仓 hold_days 天, 到期平仓.
    **持仓期间权重为 UNIT 不变**, 不因新事件到来 re-normalize.
    """
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values

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
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] -= unit_weight
            total_short += 1

        for _, r in bot_rows.iterrows():
            t = np.datetime64(r["release_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = max(0, i_t - pre_window)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += unit_weight
            total_long += 1

    logger.info(
        f"opened long={total_long}, short={total_short} positions across "
        f"{len(events.groupby('month'))} months, UNIT={unit_weight:.4f}"
    )
    return W


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    logger.info(f"prices: {prices.shape}")
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W = build_fixed_unit_weights(events, rets.index)
    W = W.reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = (daily_gross - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Lockup_v3")
    print("\n" + "=" * 60)
    print(f"  解禁 v3 (fixed-unit event-triggered) OOS ({start} ~ {end})")
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
    print("\n=== 预注册 Admission Gate (DSR trial #15) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率均值 = {turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均持仓数 = long {(w_exec > 0).sum(axis=1).mean():.1f}, short {(w_exec < 0).sum(axis=1).mean():.1f}")
    print(f"  平均 gross = {w_exec.abs().sum(axis=1).loc[start:end].mean():.3f}")
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
    parser.add_argument("--output", default="research/event_driven/lockup_v3_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events()
    logger.info(f"events: {len(events)}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选")
    else:
        print("\nFAIL — 解禁方向 3 次均 fail, 下一尝试: 回购 (接受 SR bias)")


if __name__ == "__main__":
    main()
