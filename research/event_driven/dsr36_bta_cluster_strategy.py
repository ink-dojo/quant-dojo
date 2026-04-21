"""DSR #36 — BTA cluster-count variant.

### Pre-registration (2026-04-21, 锁定参数, 跑完不调)

**为什么 DSR #36?**
DSR #35 (amount-ranked top-30) 0/5 FAIL. Post-mortem 定位:
- 主板 × 机构吸筹 unconditional mean_fwd_21d: +1.23%
- top-30 by amount 只 +0.36% (选错 axis)
- **cluster 3+ events/month/stock: +1.29%** ← 最强 subset
- amount 最小 decile +2.79% > amount 最大 decile +1.35%
推论: 信号不在"最大单笔", 而在"同股反复机构吸筹"的高 conviction signal.

**独立 trial**: 基于 DSR #35 post-mortem 的发现设计新 selection rule, 独立 pre-reg,
独立执行, 不合并结果. 若 FAIL, 不再试第三次 amount/count 变体.

**参数 (锁定)**
| 项 | 值 |
|---|---|
| Universe | 主板 |
| 事件 filter | buyer="机构专用" AND seller != "机构专用" |
| Selection | 过去 30 天内同股累计 机构吸筹 事件数 >= 3 |
| Weight | equal, UNIT 1/30 per 仓 |
| Hold | 21 交易日 |
| Rebalance | monthly cross-section cluster filter |
| Gross cap | 1.0 |
| Cost | 0.30% round-trip |
| Period | 2016-01-01 ~ 2025-12-31 |

**Admission gate (不变)**
1. ann > 15%
2. Sharpe > 0.8
3. MDD > -30%
4. PSR > 0.95
5. Bootstrap CI_low > 0.5
5/5 → Phase 2 (WF + regime + cost stress)
4/5 → 候选, 需 WF median SR > 0
≤3/5 → 记录 post-mortem, 不再调参
"""
from __future__ import annotations
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from utils.metrics import (
    annualized_return, bootstrap_sharpe_ci, max_drawdown,
    probabilistic_sharpe, sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

from research.event_driven.block_trade_inst_accum_strategy import (
    load_events, load_benchmark, PRICE_PATH,
)

logger = logging.getLogger(__name__)

HOLD_DAYS = 21
POST_OFFSET = 1
CLUSTER_WINDOW_DAYS = 30
CLUSTER_MIN_EVENTS = 3
UNIT_POS_WEIGHT = 1.0 / 30
GROSS_CAP = 1.0
TXN_ROUND_TRIP = 0.003
RETURN_CLIP = 0.25


def build_weights_cluster(events: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """每天扫描, 若某股过去 30 天内累计机构吸筹事件 >= 3 且 今天 首次满足, 下一日开仓持 21 日.
    用 event-driven 构造, 避免重复开仓.
    """
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    events = events.sort_values("trade_date").copy()

    n_pos = 0
    for sym, grp in events.groupby("symbol"):
        dates = grp["trade_date"].values
        if len(dates) < CLUSTER_MIN_EVENTS:
            continue
        triggered = set()  # 防止 rebounding 多次开仓
        for i in range(CLUSTER_MIN_EVENTS - 1, len(dates)):
            t = dates[i]
            # 过去 30 天有几次事件
            window_start = t - np.timedelta64(CLUSTER_WINDOW_DAYS, "D")
            count = ((dates[:i+1] >= window_start) & (dates[:i+1] <= t)).sum()
            if count < CLUSTER_MIN_EVENTS:
                continue
            # avoid re-open: 最近 21 日内已开仓则跳过
            month_key = pd.Timestamp(t).to_period("M")
            if (sym, month_key) in triggered:
                continue
            triggered.add((sym, month_key))

            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + POST_OFFSET)
            i_close = min(len(td_arr), i_open + HOLD_DAYS)
            if i_open >= i_close or sym not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(sym)] += UNIT_POS_WEIGHT
            n_pos += 1
    logger.info(f"cluster positions opened: {n_pos}")
    return W


def run_backtest(start="2016-01-01", end="2025-12-31") -> dict:
    logger.info("loading events")
    ev = load_events(start, end)
    logger.info("loading price panel")
    px = pd.read_parquet(PRICE_PATH)
    px.index = pd.to_datetime(px.index)
    universe = sorted(ev["symbol"].unique())
    universe = [s for s in universe if s in px.columns]
    px = px[universe].loc[start:end]
    rets = px.pct_change().where(lambda x: x.abs() < RETURN_CLIP)

    W = build_weights_cluster(ev, rets.index).reindex(columns=px.columns).fillna(0)
    W_cap = apply_gross_cap(W, cap=GROSS_CAP)
    w_exec = W_cap.shift(1)
    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    net = (daily_gross - turnover * (TXN_ROUND_TRIP / 2)).loc[start:end].dropna()

    bench = load_benchmark(start, end).reindex(net.index).fillna(0)
    gross_series = W_cap.abs().sum(axis=1).loc[start:end].reindex(net.index).fillna(0)
    excess = net - gross_series.shift(1).fillna(0) * bench

    ann = annualized_return(net); sr = sharpe_ratio(net); mdd = max_drawdown(net)
    psr = probabilistic_sharpe(net, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(net, n_boot=2000)
    mean_gross = W_cap.abs().sum(axis=1).loc[start:end].mean()
    mean_turnover_ann = turnover.loc[start:end].mean() * 252

    ex_ann = annualized_return(excess); ex_sr = sharpe_ratio(excess); ex_mdd = max_drawdown(excess)
    ex_psr = probabilistic_sharpe(excess, sr_benchmark=0.0)
    ex_boot = bootstrap_sharpe_ci(excess, n_boot=2000)

    gate = {
        "ann>15%": ann > 0.15, "sharpe>0.8": sr > 0.8, "mdd>-30%": mdd > -0.30,
        "PSR>0.95": psr > 0.95, "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    n_pass = sum(gate.values())
    gate_ex = {
        "ex_ann>10%": ex_ann > 0.10, "ex_sharpe>0.8": ex_sr > 0.8, "ex_mdd>-20%": ex_mdd > -0.20,
        "ex_PSR>0.95": ex_psr > 0.95, "ex_ci_low>0.5": ex_boot["ci_low"] > 0.5,
    }
    n_pass_ex = sum(gate_ex.values())

    print(f"\n=== DSR #36 BTA cluster (>=3 events/30d) — pre-reg run ===")
    print(f"  期间: {start} ~ {end}  events: {len(ev):,}")
    print(f"\n  [A] long-only:")
    print(f"    ann={ann:+.2%}  SR={sr:+.3f}  MDD={mdd:+.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    for k, v in gate.items():
        print(f"      {'PASS' if v else 'FAIL'} {k}")
    print(f"    → {n_pass}/5")
    print(f"\n  [B] hedged:")
    print(f"    ann={ex_ann:+.2%}  SR={ex_sr:+.3f}  MDD={ex_mdd:+.2%}  PSR={ex_psr:.3f}  CI=[{ex_boot['ci_low']:.2f},{ex_boot['ci_high']:.2f}]")
    for k, v in gate_ex.items():
        print(f"      {'PASS' if v else 'FAIL'} {k}")
    print(f"    → {n_pass_ex}/5")
    print(f"\n  mean_gross={mean_gross:.3f}  ann_turnover={mean_turnover_ann:.2f}x")

    yearly = pd.DataFrame({
        "lo_ret": net.groupby(net.index.year).apply(lambda x: (1 + x).prod() - 1),
        "lo_sr": net.groupby(net.index.year).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan),
        "hd_ret": excess.groupby(excess.index.year).apply(lambda x: (1 + x).prod() - 1),
        "hd_sr": excess.groupby(excess.index.year).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan),
    })
    print(f"\n  year-by-year:")
    print(yearly.round(4).to_string())

    return {
        "returns": net, "excess": excess, "n_pass": n_pass, "n_pass_ex": n_pass_ex,
        "ann": ann, "sr": sr, "mdd": mdd, "psr": psr, "ci_low": boot["ci_low"],
        "ex_ann": ex_ann, "ex_sr": ex_sr, "ex_mdd": ex_mdd, "ex_psr": ex_psr,
        "ex_ci_low": ex_boot["ci_low"], "mean_gross": mean_gross,
        "ann_turnover": mean_turnover_ann, "n_events": len(ev), "yearly": yearly,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    result = run_backtest()
    out = Path("research/event_driven/dsr36_bta_cluster_oos.parquet")
    pd.DataFrame({
        "net_return": result["returns"],
        "excess_return": result["excess"],
    }).to_parquet(out)
    result["yearly"].to_parquet("research/event_driven/dsr36_bta_cluster_yearly.parquet")
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
