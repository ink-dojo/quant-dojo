"""Data-upgrade probe — PV 主板 rescaled 15yr (2010-2025).

目标: 测试 "option B 升级数据" 路径是否能把 PV alpha CI_low 推过 gate.
8yr vs 15yr bootstrap CI 对比.

NOT a new pre-reg DSR trial — 这是 option B feasibility probe.
Spec 继承 DSR #30 PV 主板 rescaled, 只延长 OOS 窗口.
"""
from __future__ import annotations
import logging
from pathlib import Path
import numpy as np
import pandas as pd

from research.event_driven.earnings_preview_strategy import (
    build_long_only_weights as build_pv_raw,
    TXN_ROUND_TRIP as PV_COST,
    UNIT_POS_WEIGHT as PV_UNIT_BASE,
    METRIC_FILTER, POSITIVE_TYPES, SIGNAL_MIN, SIGNAL_MAX,
    EVENT_DATE_COL, SIGNAL_COL,
)
from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return, bootstrap_sharpe_ci, max_drawdown,
    probabilistic_sharpe, sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())

PV_PARQUET = Path("data/raw/events/_all_earnings_preview_2010_2025.parquet")
TARGET_GROSS = 0.8


def load_pv_extended(end: str) -> pd.DataFrame:
    df = pd.read_parquet(PV_PARQUET)
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


def run(start: str, end: str, label: str) -> dict:
    ev = load_pv_extended(end)
    ev = ev[ev["symbol"].isin(MAIN_BOARD)]
    print(f"\n{label}: events={len(ev)}  date {ev['event_date'].min().date()} ~ {ev['event_date'].max().date()}")

    universe = sorted(ev["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=start, end=end)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    # Pass 1: measure base mean gross
    W = build_pv_raw(ev, rets.index, unit_weight=PV_UNIT_BASE).reindex(columns=prices.columns).fillna(0)
    W_cap = apply_gross_cap(W, cap=1.0)
    base_gross = W_cap.abs().sum(axis=1).loc[start:end].mean()
    scale = TARGET_GROSS / max(base_gross, 1e-6)
    print(f"  base mean_gross={base_gross:.3f}  scale={scale:.3f}")

    # Pass 2: rescaled
    W = build_pv_raw(ev, rets.index, unit_weight=PV_UNIT_BASE * scale).reindex(columns=prices.columns).fillna(0)
    W_cap = apply_gross_cap(W, cap=1.0)
    w_exec = W_cap.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    net = (daily_gross - turnover * (PV_COST / 2)).loc[start:end].dropna()
    final_gross = W_cap.abs().sum(axis=1).loc[start:end].mean()
    print(f"  rescaled mean_gross={final_gross:.3f}  OOS days={len(net)}")

    ann = annualized_return(net)
    sr = sharpe_ratio(net)
    mdd = max_drawdown(net)
    psr = probabilistic_sharpe(net, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(net, n_boot=2000)
    print(f"  ann={ann:+.2%}  SR={sr:.2f}  MDD={mdd:.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    return dict(ret=net, ann=ann, sr=sr, mdd=mdd, psr=psr, ci_low=boot["ci_low"], ci_high=boot["ci_high"])


def main():
    logging.basicConfig(level=logging.WARNING)
    print("=" * 72)
    print("  Data-upgrade probe — PV 主板 rescaled 8yr vs 15yr")
    print("=" * 72)

    r8 = run("2018-01-01", "2025-12-31", "PV 主板 rescaled 8yr (2018-2025)")
    r15 = run("2010-01-01", "2025-12-31", "PV 主板 rescaled 15yr (2010-2025)")

    print("\n" + "=" * 72)
    print("  Verdict on CI_low gate (0.5)")
    print("=" * 72)
    print(f"  8yr CI_low  = {r8['ci_low']:.3f}  width={r8['ci_high']-r8['ci_low']:.2f}")
    print(f"  15yr CI_low = {r15['ci_low']:.3f}  width={r15['ci_high']-r15['ci_low']:.2f}")
    if r15["ci_low"] > 0.5:
        print(">>> data upgrade WORKS — PV 15yr crosses CI_low gate <<<")
    elif r15["ci_low"] > r8["ci_low"]:
        print(">>> improved but still < 0.5 <<<")
    else:
        print(">>> no improvement — longer sample doesn't help <<<")


if __name__ == "__main__":
    main()
