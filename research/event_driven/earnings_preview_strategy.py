"""业绩预告 (earnings pre-announcement) drift — 预注册 (DSR trial #23, 2026-04-18).

### 假设
A股 要求净利润 YoY >±50% 预披露. 正向 surprise (预增/略增) 公告后 post-announcement
drift positive. 文献: PEAD (Bernard-Thomas 1989) + Fink-Johnson 美股 earnings
preview CAR, A 股 2018+ 样本持续存在 (祁玉清 2020).

### 前因
PEAD v1 (DSR #12) 用实际年报净利润 YoY FAIL: signal 在年报发布日已 price-in.
本策略改用 **预告日** (早于年报 30-60 日) 作为 event 日, 假设预告 surprise
尚未充分吸收.

### Pre-registration spec (零自由度)
- 数据: stock_yjyg_em 年报+中报+季报 2018-2025, 117071 行
- 事件日 T: 公告日期
- 过滤: 预测指标 = "归属于上市公司股东的净利润"
- 方向过滤: 预告类型 ∈ {预增, 略增} (pure positive, 可比)
- 信号: 业绩变动幅度 (%) ∈ (0, 500)
- 选股: monthly cross-section top 30% 业绩变动幅度 LONG
- 窗口: T+1 ~ T+20 (同 buyback v17 成功 spec)
- UNIT: 1/75 (ex-ante: 19840 events / 96 mo / × 0.3 ≈ 60 concurrent →
  UNIT 0.013 = 1/75 → gross 0.8)
- 成本: 0.15% 单边

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线
- FAIL → 本方向不 iterate. Phase 3 第 6 个 direction 也 fail, 写 terminal 报告
- PASS → paper-trade OOS 候选 #2 (vs DSR #17)

### DSR: 23
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
    / "data" / "raw" / "events" / "_all_earnings_preview_2018_2025.parquet"
)

HOLD_DAYS = 20
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 75  # ex-ante: 60 concurrent → gross 0.8

METRIC_FILTER = "归属于上市公司股东的净利润"
POSITIVE_TYPES = ["预增", "略增"]
SIGNAL_MIN = 0.0
SIGNAL_MAX = 500.0
EVENT_DATE_COL = "公告日期"
SIGNAL_COL = "业绩变动幅度"


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, "股票代码"])
    df = df.rename(columns={"股票代码": "symbol", EVENT_DATE_COL: "event_date"})
    df = df[df["预测指标"] == METRIC_FILTER]
    df = df[df["预告类型"].isin(POSITIVE_TYPES)]
    df["signal"] = df[SIGNAL_COL]
    df = df[(df["signal"] > SIGNAL_MIN) & (df["signal"] < SIGNAL_MAX)]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df.reset_index(drop=True)


def build_long_only_weights(
    events: pd.DataFrame, trading_days: pd.DatetimeIndex,
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

    logger.info(f"long-only positions: {total_long} across {len(events.groupby('month'))} months")
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

    summary = performance_summary(net_ret, name="Earnings_Preview")
    print("\n" + "=" * 60)
    print(f"  业绩预告 drift OOS ({start} ~ {end}) DSR #23")
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
    print("\n=== 预注册 Admission Gate (DSR trial #23) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率 = {turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均持仓 = {(w_exec > 0).sum(axis=1).mean():.1f}")
    print(f"  平均 gross = {w_exec.abs().sum(axis=1).loc[start:end].mean():.3f}")
    print(f"  Gross ann: {annualized_return(daily_gross.loc[start:end].dropna()):.2%}")

    bench = rets.mean(axis=1).loc[start:end].dropna()
    bench_ann = annualized_return(bench)
    print(f"  等权 universe bench ann: {bench_ann:.2%}")
    print(f"  vs bench excess: {ann - bench_ann:+.2%}")

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
    parser.add_argument("--output", default="research/event_driven/earnings_preview_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events after filters: {len(events)}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选 (DSR #23)")
    else:
        print("\nFAIL — Phase 3 第 6 方向 fail, terminal 报告")


if __name__ == "__main__":
    main()
