"""
股票回购 long-only + CSI300 beta hedge — 预注册 (DSR trial #18, 2026-04-18).

### 前因 (DSR #17 结果)
回购 long-only 4/5 gate PASS (ann 37%, Sharpe 0.89, PSR 0.991),
唯一 FAIL 是 MDD -79% — long-only market beta 暴露, 熊市被拖.

### 新 hypothesis
在 #17 基础上加 passive CSI300 short 对冲 market beta. 假设 buyback
portfolio market beta ≈ 1.0 (小盘偏多, ex-ante 合理估计).

**Dollar-neutral hedge**: 每日 short CSI300 = long portfolio gross exposure.
结果组合: 纯 "回购 signal 对 等权 market" 的 excess return, 去掉 market beta.

### Pre-registration spec
- Long leg: 同 #17 (top 30% 回购 UNIT=1/15 T+1~T+20, 月度 cross-section,
  排除股东大会否决, 信号 ∈ (0,50%))
- Hedge leg: 399300 (CSI300 index) short 仓位 = -long_gross_on_day_t
  (dollar neutral)
- Hedge rebalance: 每日 (隐含的, 通过 w_exec.shift 实现)
- 成本: long leg 0.15% 单边 (同前); hedge leg 0.05% 单边 (ETF/期货成本)
  -- **注意: hedge cost 用 0.05% 是 conservative 假设 IF/IC 期货成本,
  不是 ETF 0.15%. 这是 ex-ante 合理估计, 不 peek result.**

### Admission gates (不变)
- ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 失败红线
- FAIL → Phase 3 最后一个合理变体也 fail, 写终结文档
- PASS → paper-trade forward OOS 候选

### DSR: 18
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
    / "data" / "raw" / "events" / "_all_buyback.parquet"
)

HOLD_DAYS = 20
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_LONG_ROUND_TRIP = 0.003    # 0.15% 单边 long
TXN_HEDGE_ROUND_TRIP = 0.001   # 0.05% 单边 IF/IC 期货
SIGNAL_COL = "占公告前一日总股本比例-上限"
EVENT_DATE_COL = "回购起始时间"
UNIT_POS_WEIGHT = 1.0 / 15
HEDGE_SYMBOL = "399300"


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, "股票代码"])
    df = df.rename(columns={"股票代码": "symbol", EVENT_DATE_COL: "event_date"})
    df = df[df["实施进度"] != "股东大会否决"]
    df = df[(df[SIGNAL_COL] > 0) & (df[SIGNAL_COL] < 50)]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    return df


def build_long_only_weights(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
) -> pd.DataFrame:
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    events = events.copy()
    events["month"] = events["event_date"].dt.to_period("M")

    for _, grp in events.groupby("month", observed=True):
        grp = grp.sort_values(SIGNAL_COL, ascending=False)
        if len(grp) < 10:
            continue
        n_top = max(1, int(np.floor(len(grp) * TOP_PCT)))
        for _, r in grp.iloc[:n_top].iterrows():
            t = np.datetime64(r["event_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + POST_OFFSET)
            i_close = min(len(td_arr), i_open + HOLD_DAYS)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += UNIT_POS_WEIGHT
    return W


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    hedge_prices = load_adj_price_wide([HEDGE_SYMBOL], start=start, end=end)
    logger.info(f"prices: {prices.shape}, hedge: {hedge_prices.shape}")

    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)
    hedge_ret = hedge_prices[HEDGE_SYMBOL].pct_change()

    # Align hedge to same index
    hedge_ret = hedge_ret.reindex(rets.index)

    W = build_long_only_weights(events, rets.index)
    W = W.reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)

    daily_gross_long = (w_exec * rets).sum(axis=1)

    # Hedge: short CSI300 = -1 × daily long_gross_exposure
    long_gross_notional = w_exec.abs().sum(axis=1)  # daily positive notional
    hedge_weight = -long_gross_notional  # short
    daily_hedge_pnl = hedge_weight * hedge_ret

    # Turnover
    long_turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    hedge_turnover = hedge_weight.diff().abs().fillna(0)
    daily_cost = (long_turnover * (TXN_LONG_ROUND_TRIP / 2)
                  + hedge_turnover * (TXN_HEDGE_ROUND_TRIP / 2))

    gross_total = daily_gross_long + daily_hedge_pnl
    net_ret = (gross_total - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Buyback_Hedged")
    print("\n" + "=" * 60)
    print(f"  回购 long + CSI300 hedge OOS ({start} ~ {end}) DSR #18")
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
    print("\n=== 预注册 Admission Gate (DSR trial #18) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  Long leg 换手 = {long_turnover.loc[start:end].mean():.4f}/日")
    print(f"  Hedge leg 换手 = {hedge_turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均 long gross = {long_gross_notional.loc[start:end].mean():.3f}")
    print(f"  Gross ann (pre-cost): {annualized_return(gross_total.loc[start:end].dropna()):.2%}")
    print(f"  Long alone ann (gross): {annualized_return(daily_gross_long.loc[start:end].dropna()):.2%}")
    print(f"  Hedge alone ann: {annualized_return(daily_hedge_pnl.loc[start:end].dropna()):.2%}")

    return {
        "returns": net_ret,
        "ann": ann, "sharpe": sr, "mdd": mdd, "psr": psr,
        "bootstrap": boot, "gate": gate,
        "pass": all(gate.values()),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="research/event_driven/buyback_hedged_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events: {len(events)} after filters")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选")
    else:
        print("\nFAIL — 考虑继续 refine 或换方向")


if __name__ == "__main__":
    main()
