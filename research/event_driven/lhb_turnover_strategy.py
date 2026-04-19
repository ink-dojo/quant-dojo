"""龙虎榜 换手率异动 drift — 预注册 (DSR trial #32, 2026-04-19).

### 假设
Phase 3 DSR #20 测试了"涨幅偏离"LHB category 的 momentum continuation.
本策略测试**换手率 20%/30% 偏离**LHB category — 换手率极端异动通常对应
new information arrival. Barber-Odean 2008 "attention effect" 在 A 股表现为
极高换手后 T+1-T+3 continuation (散户 follow-through buying).

与 #20 区别:
- #20 信号 = 价格涨幅 outlier
- #32 信号 = 换手率 outlier (更纯粹 attention proxy, 不自带 momentum direction)

### Pre-registration spec (零 DoF)
- 数据: _all_lhb_2018_2025.parquet (138725 行, 本地)
- 事件筛选: 上榜原因 contain "换手率" (excludes 涨跌幅 events for orthogonality)
- 事件日: 上榜日 T
- 信号: 净买额占总成交比 (%) — seat 净买方向+强度
- 过滤: signal > 0 (排除净卖出), 主板 only (与 Phase 3.5 一致)
- 方向: monthly cross-section top 30% LONG
- 窗口: T+1 ~ T+3 (3 日, 同 #20)
- UNIT base: 1/30 (ex-ante)
- gross cap: 1.0, 成本: 0.15% 单边

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线
- 5/5 PASS → paper-trade 候选 #3
- 4/5 PASS → 加入 portfolio narrative 作 "methodology-rigorous partial win"
- ≤ 3/5 PASS → 写入 journal, 不 promote

### DSR: 32 (Phase 4.1 post-terminal extension, 为 portfolio 增加 trial)
"""
from __future__ import annotations
import argparse
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return, bootstrap_sharpe_ci, max_drawdown,
    performance_summary, probabilistic_sharpe, sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)

EVENTS = Path("data/raw/events/_all_lhb_2018_2025.parquet")
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())

HOLD_DAYS = 3
POST_OFFSET = 1
TOP_PCT = 0.30
TXN_ROUND_TRIP = 0.003
UNIT_POS_WEIGHT = 1.0 / 30


def load_events(end: str) -> pd.DataFrame:
    df = pd.read_parquet(EVENTS)
    df["上榜日"] = pd.to_datetime(df["上榜日"], errors="coerce")
    df = df.dropna(subset=["上榜日", "代码", "净买额占总成交比"])
    df = df.rename(columns={"代码": "symbol", "上榜日": "event_date"})
    # Filter: 换手率 category (orthogonal to 涨跌幅)
    df = df[df["上榜原因"].str.contains("换手率", na=False)]
    # Main-board only
    df = df[df["symbol"].isin(MAIN_BOARD)]
    df["signal"] = pd.to_numeric(df["净买额占总成交比"], errors="coerce")
    df = df.dropna(subset=["signal"])
    df = df[df["signal"] > 0]
    df = df[df["event_date"] <= pd.Timestamp(end)]
    df = df.sort_values("signal", ascending=False).drop_duplicates(
        subset=["symbol", "event_date"], keep="first"
    )
    return df.reset_index(drop=True)


def build_weights(events: pd.DataFrame, trading_days: pd.DatetimeIndex,
                   unit_weight: float = UNIT_POS_WEIGHT) -> pd.DataFrame:
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


def run_backtest(start="2018-01-01", end="2025-12-31") -> dict:
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
    print(f"\n=== DSR #32 LHB 换手率异动 drift ===")
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
        "research/event_driven/dsr32_lhb_turnover_oos.parquet"
    )
    print(f"\n保存: research/event_driven/dsr32_lhb_turnover_oos.parquet")


if __name__ == "__main__":
    main()
