"""大股东增持 drift — 预注册 (DSR trial #31 候选, 2026-04-18).

### 假设
Seyhun 1988 / Lakonishok-Lee 2001 美股 insider purchase → +abnormal return
60-day CAR 3-5%. A 股 彭韶兵 et al 2015 大股东增持 信号同方向. Top 30%
按增持占总股本比例, LONG-only T+1-T+20.

### Pre-registration spec (零自由度)
- 数据: stock_ggcg_em 2018-2025
- 事件日 T: 公告日
- 方向过滤: 持股变动信息-增减 == "增持"
- 信号: 持股变动信息-占总股本比例 (%)
- signal ∈ (0.1, 20)  # 排除 housekeeping (<0.1%) + major buyout (>20%)
- 选股: monthly cross-section top 30% signal LONG
- 窗口: T+1 ~ T+20 (同 buyback #17)
- UNIT: 1/30  (ex-ante: ~100k 增持事件 / 96 mo / 0.3 ≈ 300+ concurrent
  → 若选 top 30% 且 主板 过滤 后 ~50-80 concurrent → UNIT 1/30 → gross 0.8)
- 成本: 0.15% 单边 (round-trip 0.3%)

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### DSR: 31 candidate (before 3-way ensemble formally pre-reg)
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
    / "data" / "raw" / "events" / "_all_ggcg_2018_2025.parquet"
)

HOLD_DAYS = 20
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 30

DIRECTION_FILTER = "增持"
SIGNAL_MIN = 0.1
SIGNAL_MAX = 20.0
EVENT_DATE_COL = "公告日"
DIRECTION_COL = "持股变动信息-增减"
SIGNAL_COL = "持股变动信息-占总股本比例"
SYMBOL_COL = "代码"


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, SYMBOL_COL])
    df = df.rename(columns={SYMBOL_COL: "symbol", EVENT_DATE_COL: "event_date"})
    df = df[df[DIRECTION_COL] == DIRECTION_FILTER]
    df["signal"] = pd.to_numeric(df[SIGNAL_COL], errors="coerce")
    df = df.dropna(subset=["signal"])
    df = df[(df["signal"] > SIGNAL_MIN) & (df["signal"] < SIGNAL_MAX)]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df.reset_index(drop=True)


def build_long_only_weights(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    unit_weight: float = UNIT_POS_WEIGHT,
) -> pd.DataFrame:
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    events = events.copy()
    events["month"] = events["event_date"].dt.to_period("M")
    total_long = 0

    for _, grp in events.groupby("month", observed=True):
        grp = grp.sort_values("signal", ascending=False)
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
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += unit_weight
            total_long += 1

    logger.info(f"long positions: {total_long} across {len(events.groupby('month'))} months, UNIT={unit_weight:.4f}")
    return W


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    logger.info(f"prices: {prices.shape}")
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W = build_long_only_weights(events, rets.index).reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = (daily_gross - daily_cost).loc[start:end].dropna()

    print("\n" + "=" * 60)
    print(f"  大股东增持 LONG-only OOS ({start} ~ {end})")
    print("=" * 60)
    print(performance_summary(net_ret, name="Insider_Purchase").to_string())

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
    print("\n=== Gate ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  Sharpe CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率 = {turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均持仓 = {(w_exec > 0).sum(axis=1).mean():.1f}")
    print(f"  平均 gross = {w_exec.abs().sum(axis=1).loc[start:end].mean():.3f}")

    return {
        "returns": net_ret, "ann": ann, "sharpe": sr, "mdd": mdd,
        "psr": psr, "bootstrap": boot, "gate": gate,
        "pass": all(gate.values()),
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2018-01-01")
    parser.add_argument("--end", default="2025-12-31")
    parser.add_argument("--output", default="research/event_driven/insider_purchase_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events: {len(events)} 增持 after filters")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")


if __name__ == "__main__":
    main()
