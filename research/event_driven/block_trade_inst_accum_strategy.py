"""大宗交易机构单方面吸筹因子 (BTA — Block Trade institutional Accumulation).

### Pre-registration (2026-04-21, 执行前锁定参数)

**因子动机**
sanity v2 (block_trade_sanity_v2.py) 发现:
- 单纯 discount 因子弱 (monthly ICIR -0.20)
- 真正信号: buyer=机构专用 AND seller!=机构专用 (机构单方面吸筹)
  * n=16,661 事件, mean_fwd_21d +1.07%, Welch t=+8.52
  * 60d 持续 +0.70% edge
  * 同股同月 cluster 效应单调增强 (1+ 0.79% → 2+ 1.05% → 3+ 1.26%)
- 警告: 2021-2022 regime 反向 — 抱团瓦解期机构接盘反跑输

**机制假设**
机构在大宗交易里主动接盘 (非折价对倒), 反映信息优势:
1. 券商自营/公募/社保等机构有内部研究支撑
2. 单方面接盘 (对手盘是 非机构) 排除 "互换" / "关联交易" 噪音
3. 散户无法从二级市场直接复制这一行为, 形成制度性 alpha

**预先 hard-coded 参数** (锁定, 跑完不调)
| 项 | 值 | 选定理由 |
|---|---|---|
| Universe | 主板 | 避免小微盘 2024 崩盘噪音; sanity 显示主板 0.85% vs 非主板 0.69% mean_fwd_21d |
| 事件 filter | buyer="机构专用" AND seller != "机构专用" | sanity 四象限最强: t=+8.52, mean 1.07% |
| 信号强度 | 月度累计 amount (金额加权) | cluster 单调增强的基础 |
| Rebalance | 月频 (月度 cross-section 取前 30 名) | 低频 散户可执行 |
| 持有期 | 21 交易日 | 21d edge +0.59pp, p=2.5e-6; 5d 无显著性 |
| UNIT 权重 | 1/30 | 与 DSR #33 一致, 30 仓 |
| Gross cap | 1.0 | long-only, 不加杠杆 |
| 交易成本 | 0.30% round-trip (0.15% 单边) | 项目默认 |
| 回测期 | 2016-01-01 ~ 2025-12-31 | 10 年 OOS, 覆盖牛熊 + 抱团 + 崩盘 + 注册制 |
| Benchmark | 沪深300 | 与现有策略一致 |

**Admission gate (不变, 不依结果调整)**
1. 年化 > 15%
2. Sharpe > 0.8
3. MDD > -30%
4. PSR > 0.95
5. Bootstrap SR CI_low > 0.5
通过 5/5 → 进入 Phase 2 (WF + regime + cost stress).
通过 4/5 → 候选,需 WF 中位 SR > 0 才进.
通过 ≤3/5 → 记录 post-mortem, 不再调参.

**不会尝试** (避免 researcher DoF):
- 不调 HOLD_DAYS (锁定 21)
- 不调 top-N (锁定 30)
- 不调 UNIT (锁定 1/30)
- 不试 short leg (只做 long-only)
- 不加 2021-2022 regime filter (单样本先裸跑, regime 留 Phase 2)
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

logger = logging.getLogger(__name__)

EVENTS_DIR = Path("data/raw/tushare/events")
PRICE_PATH = Path("data/processed/raw_close_panel.parquet")
LISTING = pd.read_parquet("data/raw/listing_metadata.parquet")
MAIN_BOARD = set(LISTING[LISTING["board"] == "主板"]["symbol"].tolist())

HOLD_DAYS = 21
POST_OFFSET = 1
TOP_N_PER_MONTH = 30
UNIT_POS_WEIGHT = 1.0 / 30
GROSS_CAP = 1.0
TXN_ROUND_TRIP = 0.003  # 0.30% round-trip
RETURN_CLIP = 0.25  # filter price-wide noise > 25% single-day


def ts_to_symbol(ts_code: str) -> str:
    return ts_code.split(".")[0]


def load_events(start: str, end: str) -> pd.DataFrame:
    """Load all block_trade events in window, filter to institutional accumulation."""
    files = sorted(EVENTS_DIR.glob("block_trade_*.parquet"))
    dfs = []
    s_yyyymm = start.replace("-", "")[:6]
    e_yyyymm = end.replace("-", "")[:6]
    for f in files:
        yyyymm = f.stem.split("_")[-1]
        if yyyymm < s_yyyymm or yyyymm > e_yyyymm:
            continue
        dfs.append(pd.read_parquet(f))
    df = pd.concat(dfs, ignore_index=True)
    df["trade_date"] = pd.to_datetime(df["trade_date"], format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["trade_date", "price", "amount", "ts_code", "buyer", "seller"])
    df["symbol"] = df["ts_code"].apply(ts_to_symbol)
    df = df[(df["trade_date"] >= start) & (df["trade_date"] <= end)]
    # 主板 only (pre-registered)
    df = df[df["symbol"].isin(MAIN_BOARD)]
    # 机构单方面吸筹
    df = df[(df["buyer"] == "机构专用") & (df["seller"] != "机构专用")]
    # 去掉极端坏数据
    df = df[(df["price"] > 0) & (df["amount"] > 0) & (df["vol"] > 0)]
    logger.info(f"events (主板 × 机构吸筹): {len(df):,}  "
                f"{df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}  "
                f"unique symbols: {df['symbol'].nunique()}")
    return df.reset_index(drop=True)


def build_weights(events: pd.DataFrame, trading_days: pd.DatetimeIndex,
                   unit_weight: float = UNIT_POS_WEIGHT) -> pd.DataFrame:
    """月度 cross-section 取金额前 TOP_N, 每仓在 event_date+1 开仓, 持有 HOLD_DAYS."""
    symbols = sorted(events["symbol"].unique())
    W = pd.DataFrame(0.0, index=trading_days, columns=symbols, dtype=float)
    td_arr = trading_days.values
    events = events.copy()
    events["month"] = events["trade_date"].dt.to_period("M")

    # 月度 cross-section 取按 symbol 累计 amount 前 N
    n_pos = 0
    for month, grp in events.groupby("month", observed=True):
        # 月内先按 symbol 汇总金额
        sym_amount = grp.groupby("symbol").agg(
            total_amount=("amount", "sum"),
            first_event=("trade_date", "min"),
        ).reset_index()
        if len(sym_amount) == 0:
            continue
        # 取前 N
        top = sym_amount.nlargest(TOP_N_PER_MONTH, "total_amount")
        for _, r in top.iterrows():
            t = np.datetime64(r["first_event"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + POST_OFFSET)
            i_close = min(len(td_arr), i_open + HOLD_DAYS)
            if i_open >= i_close or r["symbol"] not in W.columns:
                continue
            W.iloc[i_open:i_close, W.columns.get_loc(r["symbol"])] += unit_weight
            n_pos += 1
    logger.info(f"total positions opened: {n_pos}  (~{n_pos/max(1,len(events.month.unique())):.1f}/month)")
    return W


def load_benchmark(start: str, end: str) -> pd.Series:
    """沪深300 日收益率."""
    idx = pd.read_parquet("data/raw/tushare/index_daily_000300.parquet")
    idx["trade_date"] = pd.to_datetime(idx["trade_date"], format="%Y%m%d")
    idx = idx.set_index("trade_date").sort_index()
    # pct_chg 是百分点 (e.g. 1.0962 = 1.10%)
    ret = idx["pct_chg"].astype(float) / 100.0
    return ret.loc[start:end]


def run_backtest(start="2016-01-01", end="2025-12-31") -> dict:
    logger.info("loading events")
    ev = load_events(start, end)
    logger.info("loading price panel")
    px = pd.read_parquet(PRICE_PATH)
    px.index = pd.to_datetime(px.index)
    # 只保留 universe 内股票
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
    # hedged excess (long BTA - short HS300 at same gross)
    bench = load_benchmark(start, end).reindex(net.index).fillna(0)
    # mean_gross 作 hedge notional, 对齐 exposure
    gross_series = W_cap.abs().sum(axis=1).loc[start:end].reindex(net.index).fillna(0)
    excess = net - gross_series.shift(1).fillna(0) * bench

    ann = annualized_return(net)
    sr = sharpe_ratio(net)
    mdd = max_drawdown(net)
    psr = probabilistic_sharpe(net, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(net, n_boot=2000)
    mean_gross = W_cap.abs().sum(axis=1).loc[start:end].mean()
    mean_turnover_ann = turnover.loc[start:end].mean() * 252

    # hedged excess metrics
    ex_ann = annualized_return(excess)
    ex_sr = sharpe_ratio(excess)
    ex_mdd = max_drawdown(excess)
    ex_psr = probabilistic_sharpe(excess, sr_benchmark=0.0)
    ex_boot = bootstrap_sharpe_ci(excess, n_boot=2000)

    gate = {
        "ann>15%": ann > 0.15,
        "sharpe>0.8": sr > 0.8,
        "mdd>-30%": mdd > -0.30,
        "PSR>0.95": psr > 0.95,
        "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    n_pass = sum(gate.values())
    gate_ex = {
        "ex_ann>10%": ex_ann > 0.10,
        "ex_sharpe>0.8": ex_sr > 0.8,
        "ex_mdd>-20%": ex_mdd > -0.20,
        "ex_PSR>0.95": ex_psr > 0.95,
        "ex_ci_low>0.5": ex_boot["ci_low"] > 0.5,
    }
    n_pass_ex = sum(gate_ex.values())

    print(f"\n=== BTA (Block-Trade Institutional Accumulation) — pre-reg run ===")
    print(f"  期间: {start} ~ {end}")
    print(f"  事件: {len(ev):,}  unique symbols: {ev['symbol'].nunique():,}")
    print(f"\n  [A] long-only (unhedged):")
    print(f"    ann={ann:+.2%}  SR={sr:+.3f}  MDD={mdd:+.2%}  PSR={psr:.3f}  CI=[{boot['ci_low']:.2f},{boot['ci_high']:.2f}]")
    for k, v in gate.items():
        print(f"      {'PASS' if v else 'FAIL'} {k}")
    print(f"    → {n_pass}/5")

    print(f"\n  [B] hedged (long BTA − short 沪深300 同 notional):")
    print(f"    ann={ex_ann:+.2%}  SR={ex_sr:+.3f}  MDD={ex_mdd:+.2%}  PSR={ex_psr:.3f}  CI=[{ex_boot['ci_low']:.2f},{ex_boot['ci_high']:.2f}]")
    for k, v in gate_ex.items():
        print(f"      {'PASS' if v else 'FAIL'} {k}")
    print(f"    → {n_pass_ex}/5")

    print(f"\n  mean_gross = {mean_gross:.3f}  (cap={GROSS_CAP})")
    print(f"  ann turnover = {mean_turnover_ann:.2f}x")

    # year by year (both long-only and hedged)
    print(f"\n  year-by-year (long-only vs hedged):")
    yearly = pd.DataFrame({
        "lo_ret": net.groupby(net.index.year).apply(lambda x: (1 + x).prod() - 1),
        "lo_sr": net.groupby(net.index.year).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan
        ),
        "hd_ret": excess.groupby(excess.index.year).apply(lambda x: (1 + x).prod() - 1),
        "hd_sr": excess.groupby(excess.index.year).apply(
            lambda x: x.mean() / x.std() * np.sqrt(252) if x.std() > 0 else np.nan
        ),
    })
    print(yearly.round(4).to_string())

    return {
        "returns": net,
        "excess": excess,
        "n_pass": n_pass, "n_pass_ex": n_pass_ex,
        "ann": ann, "sr": sr, "mdd": mdd, "psr": psr,
        "ci_low": boot["ci_low"],
        "ex_ann": ex_ann, "ex_sr": ex_sr, "ex_mdd": ex_mdd, "ex_psr": ex_psr,
        "ex_ci_low": ex_boot["ci_low"],
        "mean_gross": mean_gross,
        "ann_turnover": mean_turnover_ann,
        "n_events": len(ev),
        "yearly": yearly,
    }


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    result = run_backtest()
    out = Path("research/event_driven/bta_oos_returns.parquet")
    pd.DataFrame({
        "net_return": result["returns"],
        "excess_return": result["excess"],
    }).to_parquet(out)
    result["yearly"].to_parquet("research/event_driven/bta_yearly.parquet")
    print(f"\n保存: {out}")


if __name__ == "__main__":
    main()
