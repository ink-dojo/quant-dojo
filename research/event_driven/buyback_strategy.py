"""
股票回购 event-driven 策略 — 预注册 (DSR trial #16, 2026-04-18).

### 假设
上市公司公告回购 → 流通股减少预期 → 股价上行压力 (与解禁相反).
文献: Ikenberry-Lakonishok-Vermaelen (1995) 美股 open-market buyback
post-announcement 4 年 CAR +12%. A 股 regulatory 2018+ 鼓励回购,
样本期合适.

### 数据 & 已知 caveat
- snapshot: stock_repurchase_em (5042 rows, 2018-2025=4788 events)
- 回购起始时间 = 公告生效日 T (event date)
- 信号 = 占公告前一日总股本比例-上限 (planned % of total shares)
- **survivorship bias 注意**: snapshot 是当前数据库内所有 plans. 理论上
  被 eastmoney 删除/归档的 cancelled plans 不在内. 但数据看 124 "停止实施"
  仍保留, 8 "股东大会否决" 也保留 → SR bias 存在但可能不严重. journal
  明确记录此 caveat, 不因此废掉数据.

### Pre-registration spec (零自由度)
- 事件: 回购起始时间 = T
- 信号: 占公告前一日总股本比例-上限 (>0, < 50% cap 过滤异常)
- 状态过滤: 排除 "股东大会否决" (8 events, 未通过 plan)
- 窗口: T+1 ~ T+20 (post-announcement drift, 20 交易日)
- 分层: monthly cross-section; top 30% LONG (强买方信号),
        bot 30% SHORT (弱信号 / 对照)
- UNIT 权重: 1/30 = 3.33% 固定 (ex-ante 基于 4788/8yr/252 × 20 × 0.6 ≈
  28.5 concurrent positions)
- 持仓期不 daily re-normalize (继承 v3 方法论)
- 成本: 0.15% 单边

### 失败红线
- 预注册 gate 同前: ann>15%, sharpe>0.8, mdd>-30%, PSR>0.95, ci_low>0.5
- FAIL → 全部 4 个 event 方向 fail, 写 phase 3 终结结论,
  建议 jialong 考虑 (a) 升级数据 tushare/wind (b) 切美股 (c) 中频量价

### DSR 累计: 16
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
POST_OFFSET = 1  # T+1 entry
TOP_PCT = 0.30
BOT_PCT = 0.30
TXN_ROUND_TRIP = 0.003
SIGNAL_COL = "占公告前一日总股本比例-上限"
EVENT_DATE_COL = "回购起始时间"
UNIT_POS_WEIGHT = 1.0 / 30


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, "股票代码"])
    df = df.rename(columns={"股票代码": "symbol", EVENT_DATE_COL: "event_date"})
    # 过滤: 排除否决案, 过滤信号异常
    df = df[df["实施进度"] != "股东大会否决"]
    df = df[(df[SIGNAL_COL] > 0) & (df[SIGNAL_COL] < 50)]  # <50% 总股本 (合理上限)
    # 不能用未来事件 (回测 end_date 之后的)
    df = df[df["event_date"] <= pd.Timestamp(end)]
    return df


def build_fixed_unit_weights(
    events: pd.DataFrame,
    trading_days: pd.DatetimeIndex,
    post_offset: int = POST_OFFSET,
    hold_days: int = HOLD_DAYS,
    unit_weight: float = UNIT_POS_WEIGHT,
) -> pd.DataFrame:
    """
    buyback event-triggered: top 30% → LONG UNIT, bot 30% → SHORT UNIT.
    入场 T+post_offset, 持仓 hold_days 天, 到期平仓. 持仓期间不 re-normalize.
    """
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values

    events = events.copy()
    events["month"] = events["event_date"].dt.to_period("M")
    total_long, total_short = 0, 0

    for month, grp in events.groupby("month", observed=True):
        grp = grp.sort_values(SIGNAL_COL, ascending=False)
        n = len(grp)
        if n < 10:
            continue
        n_top = max(1, int(np.floor(n * TOP_PCT)))
        n_bot = max(1, int(np.floor(n * BOT_PCT)))
        top_rows = grp.iloc[:n_top]  # 强买方信号
        bot_rows = grp.iloc[-n_bot:]  # 弱信号

        for _, r in top_rows.iterrows():
            t = np.datetime64(r["event_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + post_offset)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            # LONG high signal
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += unit_weight
            total_long += 1

        for _, r in bot_rows.iterrows():
            t = np.datetime64(r["event_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + post_offset)
            i_close = min(len(td_arr), i_open + hold_days)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            # SHORT low signal
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] -= unit_weight
            total_short += 1

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

    summary = performance_summary(net_ret, name="Buyback_L/S")
    print("\n" + "=" * 60)
    print(f"  回购 event-driven OOS ({start} ~ {end}) DSR #16")
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
    print("\n=== 预注册 Admission Gate (DSR trial #16) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  换手率均值 = {turnover.loc[start:end].mean():.4f}/日")
    print(f"  平均持仓数 = long {(w_exec > 0).sum(axis=1).mean():.1f}, short {(w_exec < 0).sum(axis=1).mean():.1f}")
    print(f"  平均 gross = {w_exec.abs().sum(axis=1).loc[start:end].mean():.3f}")
    print(f"  Gross ann (pre-cost): {annualized_return(daily_gross.loc[start:end].dropna()):.2%}")

    # Leg-by-leg
    w_long = w_exec.where(w_exec > 0, 0)
    w_short = w_exec.where(w_exec < 0, 0)
    long_gross = (w_long * rets).sum(axis=1)
    short_gross = (w_short * rets).sum(axis=1)
    print(f"\n  Long leg gross ann: {annualized_return(long_gross.loc[start:end].dropna()):.2%}")
    print(f"  Short leg gross ann: {annualized_return(short_gross.loc[start:end].dropna()):.2%}")

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
    parser.add_argument("--output", default="research/event_driven/buyback_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events: {len(events)} after filters")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选")
    else:
        print("\nFAIL — 4 event 方向全败, phase 3 日频 L/S 写死 / 换方向")


if __name__ == "__main__":
    main()
