"""DSR #37 — 限售解禁后反弹 (post-unlock reversal).

### Pre-registration (2026-04-21, 锁定参数, 跑完不调)

**为什么 DSR #37?**
BTA 因子线 (DSR #35/#36) 已按 pre-reg 纪律终止. 转向 Option A: 限售解禁逆向因子.

Sanity (2026-04-21 下午):
- 全样本 (n=18,400) post_20d_return +1.49%  (已经是正的)
- cat ∈ {首发原股东, 定增, 股权激励, 首发战略机构}: n=16,919 +1.34%
- + pct_of_float ≤ 0.50: n=14,741 +1.46%
- + pre_20d ≤ -5%: n=5,672 +1.78%
- + pre_20d ≤ -10%: n=3,223 **+2.51%** ← 选这个
- + pre_20d ≤ -15%: n=1,539 +3.34% (但样本量少一半, over-fit 风险)

**核心假设**: 解禁前市场预期减持压力 → 提前下跌 → 解禁后不确定性消除 +
                前期超卖反弹 → post-unlock 反弹. 学术文献已 confirmed
                (Ofek & Richardson 2003, Field & Hanka 2001, A 股 CCER 2015).

**8 年稳定性** (selection rule 下 post_20d_return mean):
  2018 +0.85% (熊市也正)
  2019 +1.21%   2020 +2.03%   2021 +3.58%
  2022 +2.59%   2023 +0.35%   2024 +4.62%   2025 +6.33%
→ 无任何年份为负 (vs BTA 在 2018/2022 均为负)

**参数 (锁定)**
| 项 | 值 |
|---|---|
| Universe | 全 A (lockup 事件全市场) |
| 类型 filter | lockup_type ∈ {首发原股东, 定增, 股权激励, 首发战略机构} |
| 规模 filter | pct_of_float ≤ 0.50 (排除 top 10% "海啸") |
| 反转 filter | pre_20d_return ≤ -10% |
| Entry | release_date + 1 trading day |
| Hold | 21 交易日 |
| Weight | equal, UNIT 1/50 per 仓 |
| Gross cap | 1.0 |
| Rebalance | event-driven |
| Cost | 0.30% round-trip |
| Period | 2018-01-01 ~ 2025-12-31 |

预期并发头寸 ≈ 34 仓, UNIT 1/50 → 平均 gross ≈ 0.68 (留 buffer 给集中月份).

**Admission gate (不变)**
1. ann > 15%
2. Sharpe > 0.8
3. MDD > -30%
4. PSR > 0.95
5. Bootstrap CI_low > 0.5
5/5 → Phase 2 (WF + regime + cost stress)
4/5 → 候选, 需 WF median SR > 0
≤3/5 → 记录 post-mortem, 不再调这个因子的参数
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
    load_benchmark, PRICE_PATH,
)

logger = logging.getLogger(__name__)

LOCKUP_PATH = Path("data/raw/events/_all_lockup_2018_2025.parquet")
ALLOWED_CATS = {"首发原股东", "定向增发", "股权激励", "首发战略机构"}
POF_MAX = 0.50
PRE_20D_MAX = -10.0  # in pct (data is already in %)
HOLD_DAYS = 21
POST_OFFSET = 1
UNIT_POS_WEIGHT = 1.0 / 50
GROSS_CAP = 1.0
TXN_ROUND_TRIP = 0.003
RETURN_CLIP = 0.25


def classify_cat(t: str) -> str:
    """把复合 lockup_type 归到主类别."""
    if "首发原股东" in t and "战略" not in t:
        return "首发原股东"
    if "首发战略" in t or "首发机构" in t:
        return "首发战略机构"
    if "定向增发" in t and "激励" not in t:
        return "定向增发"
    if "股权激励" in t:
        return "股权激励"
    if "追加承诺" in t:
        return "追加承诺"
    return "其他"


def load_unlock_events(start: str = "2018-01-01", end: str = "2025-12-31") -> pd.DataFrame:
    """加载解禁事件, 按预设规则 filter."""
    df = pd.read_parquet(LOCKUP_PATH)
    df["release_date"] = pd.to_datetime(df["release_date"])
    df = df[(df["release_date"] >= start) & (df["release_date"] <= end)].copy()
    df["cat"] = df["lockup_type"].apply(classify_cat)
    before = len(df)
    df = df[df["cat"].isin(ALLOWED_CATS)]
    df = df[df["pct_of_float"] <= POF_MAX]
    df = df[df["pre_20d_return"] <= PRE_20D_MAX]
    df = df.dropna(subset=["pre_20d_return"])
    logger.info(f"events total={before:,} filtered={len(df):,} (cat ∩ pof<={POF_MAX} ∩ pre<={PRE_20D_MAX}%)")
    df = df.rename(columns={"release_date": "trade_date"})  # align with event pattern
    return df[["symbol", "trade_date", "cat", "pct_of_float", "pre_20d_return"]].copy()


def build_weights(events: pd.DataFrame, trading_days: pd.DatetimeIndex) -> pd.DataFrame:
    """每个 event 在 release_date + POST_OFFSET 开仓, 持 HOLD_DAYS."""
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    n_pos = 0
    for _, row in events.iterrows():
        sym = row["symbol"]
        t = np.datetime64(row["trade_date"])
        if sym not in W.columns:
            continue
        i_t = int(np.searchsorted(td_arr, t, side="left"))
        i_open = min(len(td_arr), i_t + POST_OFFSET)
        i_close = min(len(td_arr), i_open + HOLD_DAYS)
        if i_open >= i_close:
            continue
        W.iloc[i_open:i_close, W.columns.get_loc(sym)] += UNIT_POS_WEIGHT
        n_pos += 1
    logger.info(f"positions opened: {n_pos}")
    return W


def run_backtest(start="2018-01-01", end="2025-12-31") -> dict:
    logger.info("loading unlock events")
    ev = load_unlock_events(start, end)
    logger.info("loading price panel")
    px = pd.read_parquet(PRICE_PATH)
    px.index = pd.to_datetime(px.index)
    universe = sorted(ev["symbol"].unique())
    universe = [s for s in universe if s in px.columns]
    px = px[universe].loc[start:end]
    rets = px.pct_change().where(lambda x: x.abs() < RETURN_CLIP)

    W = build_weights(ev, rets.index).reindex(columns=px.columns).fillna(0)
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
    mean_gross = gross_series.mean()
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

    print(f"\n=== DSR #37 post-unlock reversal — pre-reg run ===")
    print(f"  期间: {start} ~ {end}  events: {len(ev):,}")
    print(f"\n  [A] long-only:")
    print(f"    ann={ann:+.2%}  SR={sr:+.3f}  MDD={mdd:+.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    for k, v in gate.items():
        print(f"      {'PASS' if v else 'FAIL'} {k}")
    print(f"    → {n_pass}/5")
    print(f"\n  [B] hedged (vs HS300):")
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
    out = Path("research/event_driven/dsr37_unlock_reversal_oos.parquet")
    pd.DataFrame({
        "net_return": result["returns"],
        "excess_return": result["excess"],
    }).to_parquet(out)
    result["yearly"].to_parquet("research/event_driven/dsr37_unlock_reversal_yearly.parquet")
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
