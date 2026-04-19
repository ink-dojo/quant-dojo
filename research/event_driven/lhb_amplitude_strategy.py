"""龙虎榜 振幅 volatility-spike drift — 预注册 (DSR trial #34, 2026-04-19).

### 假设
DSR #33 证明 "seat 净买入 + 跌幅偏离 LHB" contrarian 4/5 PASS.
本策略 robustness check: 换 LHB category 到 **振幅 15%** — 同时包含上下震荡,
不带方向 prior. Seat 净买入 若仍有 predictive power, 则 #33 alpha 不是
仅 "contrarian 跌幅" 特异性, 而是 institutional informed-flow 通用信号.

### Pre-registration spec (零 DoF)
- 数据: _all_lhb_2018_2025.parquet
- 事件筛选: 上榜原因 contain "振幅" (排除 涨幅/跌幅/换手率 for orthogonality)
- 信号: 净买额占总成交比 > 0
- 主板 only, monthly cross-section top 30% LONG
- 窗口: T+1 ~ T+5 (与 #33 一致)
- UNIT base: 1/30, gross cap: 1.0, 成本: 0.15% 单边

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### DSR: 34 (robustness check, n_trials accumulator → 34)
"""
from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return, bootstrap_sharpe_ci, max_drawdown,
    probabilistic_sharpe, sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)

EVENTS = Path("data/raw/events/_all_lhb_2018_2025.parquet")
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())

HOLD_DAYS = 5
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 30


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS)
    df["上榜日"] = pd.to_datetime(df["上榜日"], errors="coerce")
    df = df.dropna(subset=["上榜日", "代码", "净买额占总成交比"])
    df = df.rename(columns={"代码": "symbol", "上榜日": "event_date"})
    df = df[df["上榜原因"].str.contains("振幅", na=False)]
    df = df[df["symbol"].isin(MAIN_BOARD)]
    df["signal"] = pd.to_numeric(df["净买额占总成交比"], errors="coerce")
    df = df.dropna(subset=["signal"])
    df = df[df["signal"] > 0]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df.reset_index(drop=True)


def build_weights(events, trading_days, unit_weight=UNIT_POS_WEIGHT):
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    events = events.copy()
    events["month"] = events["event_date"].dt.to_period("M")
    n_pos = 0
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
            n_pos += 1
    logger.info(f"positions: {n_pos}")
    return W


def run_backtest(start="2018-01-01", end="2025-12-31"):
    ev = load_events(end)
    print(f"events: {len(ev)}  {ev['event_date'].min().date()} ~ {ev['event_date'].max().date()}")
    universe = sorted(ev["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=start, end=end)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W = build_weights(ev, rets.index).reindex(columns=prices.columns).fillna(0)
    W_cap = apply_gross_cap(W, cap=1.0)
    w_exec = W_cap.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    net = (daily_gross - turnover * (TXN_ROUND_TRIP / 2)).loc[start:end].dropna()

    ann = annualized_return(net); sr = sharpe_ratio(net); mdd = max_drawdown(net)
    psr = probabilistic_sharpe(net, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(net, n_boot=2000)
    gate = {
        "ann>15%": ann > 0.15, "sharpe>0.8": sr > 0.8,
        "mdd>-30%": mdd > -0.30, "PSR>0.95": psr > 0.95,
        "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    n_pass = sum(gate.values())
    print(f"\n=== DSR #34 LHB 振幅 volatility-spike drift ===")
    print(f"  ann={ann:+.2%}  Sharpe={sr:.2f}  MDD={mdd:.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    print(f"  {n_pass}/5")
    print(f"  mean_gross={W_cap.abs().sum(axis=1).loc[start:end].mean():.3f}")
    return {"returns": net, "n_pass": n_pass, "ann": ann, "sr": sr, "mdd": mdd,
            "psr": psr, "ci_low": boot["ci_low"]}


def main():
    logging.basicConfig(level=logging.WARNING)
    result = run_backtest()
    result["returns"].rename("net_return").to_frame().to_parquet(
        "research/event_driven/dsr34_lhb_amplitude_oos.parquet"
    )
    print(f"\n保存: research/event_driven/dsr34_lhb_amplitude_oos.parquet")


if __name__ == "__main__":
    main()
