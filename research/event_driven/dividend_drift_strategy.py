"""分红预案 drift event-driven — 预注册 (DSR trial #21 FAIL → #22 UNIT recal).

### DSR #21 结果 (pre-reg FAIL — operational error)
UNIT=1/15 × 72 concurrent positions = 4.78× gross leverage (vs buyback 0.8x).
ann -86%, vol 231%, MDD -100%. **不是信号测试, 是杠杆炸仓**.

### DSR #22 修正 (此文件当前)
**ONE-SHOT operational recalibration** (非信号/变体): UNIT 目标 0.8 gross
(同 buyback v17), 因分红 event 密度 ~6× 于 buyback.
- 72 concurrent × UNIT = 0.8 → UNIT = 1/90
- 所有信号/窗口/选股逻辑**不变**
- 这是一次 pre-reg design flaw 修正, 不是 p-hacking variant.
  计入 DSR trial #22 (+1 penalty).
- FAIL → 分红 方向终结, 换下一方向 (不再 iterate)


### 假设
上市公司公布高股息分红预案 → 信号 quality/cash flow 稳定 → 股价 T+1~T+20
positive drift.

文献:
- Miller-Rock (1985) 信号理论: 分红公告正向信号
- Koch-Sun (2004) 美股分红提高 +1.6% announcement CAR
- A 股 2019+ 监管鼓励持续分红, 红利因子被主动资金追逐
  (红利 ETF 规模 2020-2025 ×5)

### Pre-registration spec (零自由度)
- 数据: stock_fhps_em backfill 27131 条 2018-2025
- 事件日 T: 预案公告日
- 信号: 现金分红-股息率 (range filter (0, 0.15))
- **无 future-info 过滤**: 方案进度 属于下游状态, 不在 T 可知, 不使用
  (94% 实际执行, survivor bias 可忽略)
- 方向: **monthly cross-section top 30% 股息率 LONG only**
- 窗口: T+1 ~ T+20 (同 buyback v17 成功 spec)
- UNIT: 1/15 固定权重 (同 buyback v17)
- 成本: 0.15% 单边

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 失败红线
- FAIL → 不 iterate 分红 变体. 换下一方向或进入 phase 3 终结
- PASS → paper-trade OOS 候选 #2 (vs DSR #17)

### DSR: 21
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
    / "data" / "raw" / "events" / "_all_dividend_2018_2025.parquet"
)

HOLD_DAYS = 20
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 90  # recal to 0.8 gross target (DSR #22)

SIGNAL_COL = "现金分红-股息率"
EVENT_DATE_COL = "预案公告日"
SIGNAL_MIN = 0.0
SIGNAL_MAX = 0.15


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS_PARQUET)
    df[EVENT_DATE_COL] = pd.to_datetime(df[EVENT_DATE_COL], errors="coerce")
    df = df.dropna(subset=[EVENT_DATE_COL, SIGNAL_COL, "代码"])
    df = df.rename(columns={"代码": "symbol", EVENT_DATE_COL: "event_date"})
    df["signal"] = df[SIGNAL_COL]
    df = df[(df["signal"] > SIGNAL_MIN) & (df["signal"] < SIGNAL_MAX)]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    # 同一 (symbol, date) 去重 (取最大)
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

    summary = performance_summary(net_ret, name="Dividend_Drift")
    print("\n" + "=" * 60)
    print(f"  分红预案 drift OOS ({start} ~ {end}) DSR #22 (UNIT recal)")
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
    print("\n=== 预注册 Admission Gate (DSR trial #22) ===")
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
    parser.add_argument("--output", default="research/event_driven/dividend_drift_oos_returns.parquet")
    args = parser.parse_args()

    events = load_events(end=args.end)
    logger.info(f"events after filters: {len(events)}")
    result = run_backtest(events, args.start, args.end)
    result["returns"].rename("net_return").to_frame().to_parquet(args.output)
    logger.info(f"P&L 落盘: {args.output}")
    if result["pass"]:
        print("\nPASS — paper-trade forward OOS 候选 (DSR #21)")
    else:
        print("\nFAIL — 换下一方向")


if __name__ == "__main__":
    main()
