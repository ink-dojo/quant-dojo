"""
回购 long + CSI1000 (small-cap hedge) — 预注册 (DSR trial #19, 2026-04-18).

### 前因 (DSR #18 结果)
CSI300 hedge FAIL: ann 26.52%, Sharpe 0.73, MDD -66%, hedge leg 独立
-16.18%.  根因: 回购 events 主要是中小盘 (2018-2025 A 股 regulatory
鼓励中小盘回购), CSI300 是大盘指数 — hedge 不匹配 portfolio cap 暴露.

### 新 hypothesis (结构性假设改变)
**A 股 small-mid-cap buyback alpha 必须匹配 small-cap hedge**.
替换 hedge 工具: CSI300 → CSI1000 (000852, 小盘基准).
CSI1000 跟踪 801-1800 市值排名, 与回购 universe 市值分布更匹配.

### Pre-registration spec (除 hedge 外同 #18)
- Long leg: top 30% 回购 UNIT=1/15 T+1~T+20 月度 cross-section
- Hedge leg: 000852 (CSI1000) short = -1.0 × long gross
- 成本: long 0.15% 单边, hedge 0.05% 单边 (IM 1000 期货或 512100 ETF)

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线 (最后一次合理 iteration)
- FAIL → Phase 3 event-driven 已探索 4 方向 × 多变体, 回购 alpha 明确
  存在 (+27% excess vs 等权 bench) 但在 admission 框架下 MDD 卡死.
  写终结报告, 建议 jialong: (a) paper-trade 长仓 (接受 MDD risk) 或
  (b) 切换方向 (升级数据 / 美股 / 中频)
- PASS → paper-trade forward OOS 候选, DSR n=19

### 诚实声明
这是**第 4 个 buyback 变体** (L/S v16, long-only v17, CSI300 hedged v18,
CSI1000 hedged v19). 每次 pivot 都基于前次诊断. 按 DSR 逻辑 n_trials=19
作为 penalty. 如果 v19 又 fail 我**停止** iteration — 再改就是
genuine p-hacking.
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
TXN_LONG_ROUND_TRIP = 0.003
TXN_HEDGE_ROUND_TRIP = 0.001
SIGNAL_COL = "占公告前一日总股本比例-上限"
EVENT_DATE_COL = "回购起始时间"
UNIT_POS_WEIGHT = 1.0 / 15
HEDGE_SYMBOL = "000852"  # CSI1000 — the only spec change vs v18


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, "股票代码"])
    df = df.rename(columns={"股票代码": "symbol", EVENT_DATE_COL: "event_date"})
    df = df[df["实施进度"] != "股东大会否决"]
    df = df[(df[SIGNAL_COL] > 0) & (df[SIGNAL_COL] < 50)]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    return df


def build_long_only_weights(events: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
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
    logger.info(f"universe: {len(universe)} symbols, hedge={HEDGE_SYMBOL}")
    prices = load_adj_price_wide(universe, start=start, end=end)
    hedge_prices = load_adj_price_wide([HEDGE_SYMBOL], start=start, end=end)

    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)
    hedge_ret = hedge_prices[HEDGE_SYMBOL].pct_change().reindex(rets.index)

    W = build_long_only_weights(events, rets.index).reindex(columns=prices.columns).fillna(0)
    w_exec = W.shift(1)

    daily_gross_long = (w_exec * rets).sum(axis=1)
    long_gross_notional = w_exec.abs().sum(axis=1)
    hedge_weight = -long_gross_notional
    daily_hedge_pnl = hedge_weight * hedge_ret

    long_turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    hedge_turnover = hedge_weight.diff().abs().fillna(0)
    daily_cost = (long_turnover * (TXN_LONG_ROUND_TRIP / 2)
                  + hedge_turnover * (TXN_HEDGE_ROUND_TRIP / 2))

    gross_total = daily_gross_long + daily_hedge_pnl
    net_ret = (gross_total - daily_cost).loc[start:end].dropna()

    summary = performance_summary(net_ret, name="Buyback_Hedged_CSI1000")
    print("\n" + "=" * 60)
    print(f"  回购 long + CSI1000 hedge OOS ({start} ~ {end}) DSR #19")
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
    print("\n=== 预注册 Admission Gate (DSR trial #19) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  平均 long gross = {long_gross_notional.loc[start:end].mean():.3f}")
    print(f"  Gross ann: {annualized_return(gross_total.loc[start:end].dropna()):.2%}")
    print(f"  Long leg gross ann: {annualized_return(daily_gross_long.loc[start:end].dropna()):.2%}")
    print(f"  Hedge leg ann: {annualized_return(daily_hedge_pnl.loc[start:end].dropna()):.2%}")

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
    parser.add_argument("--output", default="research/event_driven/buyback_hedged_v2_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events: {len(events)} after filters")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选 (DSR #19)")
    else:
        print("\nFAIL — 停止 iteration, 写 phase 3 终结报告")


if __name__ == "__main__":
    main()
