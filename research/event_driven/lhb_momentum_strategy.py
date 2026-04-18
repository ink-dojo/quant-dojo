"""
龙虎榜 momentum event-driven — 预注册 (DSR trial #20, 2026-04-18).

### 假设
A 股 **涨幅偏离 +7% 龙虎榜** 事件后, 高净买额股票展现 short-term momentum
continuation (T+1~T+3). 信号 = 龙虎榜净买额 / 流通市值 (cross-sectional
normalized 机构买方强度).

文献背景:
- Barber-Odean (2008) "Attention and news" — 媒体关注股票次日异常 return
- Seasholes-Wu (2007) "Price limits and earnings management" — 涨停板后
  continuation in A-share (2001-2004)
- A 股散户 attention-driven trade, 涨停股次日 +0.5-1% CAR 已有多篇确认

### Pre-registration spec (零自由度)
- 数据: stock_lhb_detail_em 2018-2025 (全量 backfill 成功)
- 事件筛选: 上榜原因包含 "涨幅偏离值达到7%" (momentum event, 非跌幅)
- 事件日: 上榜日 T
- 信号: 龙虎榜净买额 / 流通市值 (>0; net buy 强度 relative 规模)
- 方向: **monthly cross-section top 30% LONG** (only, 无 short)
- 窗口: T+1 ~ T+3 (3 日持仓)
- UNIT: 1/30 固定权重
- 成本: 0.15% 单边

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 失败红线
- FAIL → 不 iterate (不像 buyback 那样 v1→v5 都试). 换下一方向.
- PASS → paper-trade forward OOS 候选 #2 (vs #17)

### 数据健康检查 (不偷看结果)
- 2018-2025 涨幅偏离事件 ≈ 每年 2000-3000 (1 月 ≈ 200)
- 2018+ 监管后 LHB 入榜标准固定, 样本 stationary
- 流通市值 in 万元, 净买额 in 元 — unit ratio 需要确认 (乘 10000)

### DSR: 20
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
    / "data" / "raw" / "events" / "_all_lhb_2018_2025.parquet"
)

HOLD_DAYS = 3
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 30

REASON_FILTER = "涨幅偏离值达到7%"


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df["上榜日"] = pd.to_datetime(df["上榜日"])
    df = df.dropna(subset=["上榜日", "代码", "龙虎榜净买额", "流通市值"])
    df = df.rename(columns={"代码": "symbol", "上榜日": "event_date"})
    # 事件筛选: 仅 涨幅偏离 momentum events
    df = df[df["上榜原因"].str.contains(REASON_FILTER, na=False)]
    # 正 net buy (sell-dominant 的排除)
    df = df[df["龙虎榜净买额"] > 0]
    df = df[df["流通市值"] > 0]
    # 构造 signal: 净买额 / 流通市值 (注意: 流通市值 in 万元, 净买额 in 元)
    df["signal"] = df["龙虎榜净买额"] / (df["流通市值"] * 10000)
    df = df[df["event_date"] <= pd.Timestamp(end)]
    # 同一 (symbol, date) 多行 (多个原因): 取最大 signal
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df.reset_index(drop=True)


def build_long_only_weights(
    events: pd.DataFrame, trading_days: pd.DatetimeIndex,
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
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += UNIT_POS_WEIGHT
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

    summary = performance_summary(net_ret, name="LHB_Momentum")
    print("\n" + "=" * 60)
    print(f"  龙虎榜 momentum OOS ({start} ~ {end}) DSR #20")
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
    print("\n=== 预注册 Admission Gate (DSR trial #20) ===")
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
    parser.add_argument("--output", default="research/event_driven/lhb_momentum_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events after filters: {len(events)}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选")
    else:
        print("\nFAIL — 换下一方向")


if __name__ == "__main__":
    main()
