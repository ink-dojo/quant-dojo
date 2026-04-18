"""
股票回购 LONG-only event-driven — 预注册 (DSR trial #17, 2026-04-18).

### 假设 (不同于 L/S v1)
L/S v1 FAIL 揭示: top 30% long leg gross +26% ann 信号强; bot 30% short
leg -21% ann (signal direction wrong). 这是 directional long signal,
不是 symmetric L/S.

**新 hypothesis**: buyback top 30% long-only 捕捉 Ikenberry 1995
post-announcement drift. 接受 market beta exposure 作为 cost of a
directional strategy.

### Pre-registration spec (零自由度)
- 事件: 回购起始时间 T
- 信号: 占公告前一日总股本比例-上限 (>0, <50%)
- 状态过滤: 排除 "股东大会否决"
- 选股: **monthly cross-section top 30%** (无 short leg)
- 窗口: T+1 ~ T+20
- UNIT 权重: 1/15 (ex ante: 1207 long positions / 8 yr / 252 × 20 ≈
  12 concurrent; UNIT=1/15 → gross 0.8 typical)
- 持仓期不 re-normalize (继承 v3 方法论)
- 成本: 0.15% 单边

### Admission gates (不放松 — long-only 同样门槛)
- ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5
- Long-only 有 market beta 暴露, 不是纯 alpha. MDD 门槛可能最难过.

### 失败红线
- FAIL → 4 event 方向 + 全部变体 全 fail. 写 phase 3 终结文档, 建议
  jialong 换方向 (升级数据 / 切美股 / 中频量价)
- PASS → paper-trade forward OOS. Market hedge overlay 要在 paper-trade
  阶段另加 (不属于本策略 spec 范围)

### DSR: 17
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
TXN_ROUND_TRIP = 0.003
SIGNAL_COL = "占公告前一日总股本比例-上限"
EVENT_DATE_COL = "回购起始时间"
UNIT_POS_WEIGHT = 1.0 / 15


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
    post_offset: int = POST_OFFSET,
    hold_days: int = HOLD_DAYS,
    unit_weight: float = UNIT_POS_WEIGHT,
) -> pd.DataFrame:
    """Top 30% 回购比例 → LONG UNIT, T+1 开仓持 20 日."""
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values

    events = events.copy()
    events["month"] = events["event_date"].dt.to_period("M")
    total_long = 0

    for month, grp in events.groupby("month", observed=True):
        grp = grp.sort_values(SIGNAL_COL, ascending=False)
        n = len(grp)
        if n < 10:
            continue
        n_top = max(1, int(np.floor(n * TOP_PCT)))
        top_rows = grp.iloc[:n_top]

        for _, r in top_rows.iterrows():
            t = np.datetime64(r["event_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + post_offset)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += unit_weight
            total_long += 1

    logger.info(f"long-only positions: {total_long} across {len(events.groupby('month'))} months, UNIT={unit_weight:.4f}")
    return W


def run_backtest(events: pd.DataFrame, start: str, end: str) -> dict:
    universe = sorted(events["symbol"].dropna().unique().tolist())
    logger.info(f"universe: {len(universe)} symbols")
    prices = load_adj_price_wide(universe, start=start, end=end)
    logger.info(f"prices: {prices.shape}")
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W = build_long_only_weights(events, rets.index)
    W = W.reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)

    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (TXN_ROUND_TRIP / 2)
    net_ret = (daily_gross - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Buyback_LongOnly")
    print("\n" + "=" * 60)
    print(f"  回购 LONG-only OOS ({start} ~ {end}) DSR #17")
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
    print("\n=== 预注册 Admission Gate (DSR trial #17) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率均值 = {turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均持仓数 = long {(w_exec > 0).sum(axis=1).mean():.1f}")
    print(f"  平均 gross = {w_exec.abs().sum(axis=1).loc[start:end].mean():.3f}")
    print(f"  Gross ann (pre-cost): {annualized_return(daily_gross.loc[start:end].dropna()):.2%}")

    # 相对等权 universe benchmark 的 excess
    bench = rets.mean(axis=1).loc[start:end].dropna()
    bench_ann = annualized_return(bench)
    print(f"\n  等权 universe bench ann: {bench_ann:.2%}")
    print(f"  vs bench excess ann: {ann - bench_ann:+.2%}")

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
    parser.add_argument("--output", default="research/event_driven/buyback_long_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events: {len(events)} after filters")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选 (需 market hedge overlay)")
    else:
        print("\nFAIL — 全部 event 方向 × 全部变体 fail. Phase 3 终结")


if __name__ == "__main__":
    main()
