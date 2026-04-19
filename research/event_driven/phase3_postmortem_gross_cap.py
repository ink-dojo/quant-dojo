"""Phase 3 post-mortem — 修复 gross-cap 实现 defect, re-run #17/#23/#24.

### 问题诊断
DSR #17 buyback 实测 max gross **11.27x** (2024-02-28), p99 gross 6.59x.
事件聚集期 `W += UNIT` 未 cap → 2024-02 小微盘雪崩 + 回购潮共振,
166 只股票同时持仓, gross 10x+ leverage.

预注册 spec 声称 `gross 0.8 typical`, 但实现未强制 cap — 这是 bug,
不是 feature. 报告的 ann 37% / Sharpe 0.89 / MDD -79% 被 10x leverage
artifact 严重污染.

### 本 post-mortem 动作
1. apply_gross_cap(W, cap=1.0) overlay 应用到 #17 buyback + #23 preview
2. 重算 net return → 新 parquet (_capped 后缀)
3. 重算 50/50 ensemble 从 capped returns
4. 三个策略 side-by-side 对比 orig vs capped, 报告真实 alpha

### 计数
这不是新 trial. 是修 bug. 仍然保留 DSR penalty = 24 (Phase 3 最终).
新 pre-reg (Phase 4) 从 #25 起算.
"""
from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

from research.event_driven.buyback_long_only_strategy import (
    load_events as load_bb,
    build_long_only_weights as build_bb,
    TXN_ROUND_TRIP as BB_COST,
)
from research.event_driven.earnings_preview_strategy import (
    load_events as load_pv,
    build_long_only_weights as build_pv,
    TXN_ROUND_TRIP as PV_COST,
)
from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return,
    bootstrap_sharpe_ci,
    max_drawdown,
    probabilistic_sharpe,
    sharpe_ratio,
)
from utils.risk_overlay import apply_gross_cap

logger = logging.getLogger(__name__)

START = "2018-01-01"
END = "2025-12-31"
GROSS_CAP = 1.0


def compute_capped_returns(
    ev: pd.DataFrame,
    prices: pd.DataFrame,
    W_raw: pd.DataFrame,
    cost_round_trip: float,
    name: str,
) -> dict:
    """应用 gross cap, 重算 net return 和各项 gate."""
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    W_capped = apply_gross_cap(W_raw, cap=GROSS_CAP)
    w_exec = W_capped.shift(1)

    daily_gross = (w_exec * rets).sum(axis=1)
    turnover = w_exec.diff().abs().sum(axis=1).fillna(0)
    daily_cost = turnover * (cost_round_trip / 2)
    net_ret = (daily_gross - daily_cost).loc[START:END].dropna()

    # Diagnostics
    gross_ts = W_capped.abs().sum(axis=1).loc[START:END]
    raw_gross_ts = W_raw.abs().sum(axis=1).loc[START:END]

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
    print(f"\n=== {name} CAPPED (gross cap={GROSS_CAP}) ===")
    print(f"  mean raw gross: {raw_gross_ts.mean():.3f}, max raw: {raw_gross_ts.max():.3f}")
    print(f"  mean capped gross: {gross_ts.mean():.3f}, max capped: {gross_ts.max():.3f}")
    print(f"  ann={ann:+.2%} Sharpe={sr:.2f} MDD={mdd:.2%} PSR={psr:.3f} CI_low={boot['ci_low']:.2f}")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")

    return dict(returns=net_ret, gate=gate, ann=ann, sharpe=sr, mdd=mdd, psr=psr, boot=boot)


def main():
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")

    print("=" * 70)
    print("  Phase 3 POST-MORTEM — gross-cap bug fix, re-run DSR #17/#23/#24")
    print("=" * 70)

    # ============ DSR #17 BUYBACK ============
    print("\n[1/3] DSR #17 — 回购 long-only (capped)")
    ev_bb = load_bb(END)
    uni_bb = sorted(ev_bb["symbol"].dropna().unique().tolist())
    prices_bb = load_adj_price_wide(uni_bb, start=START, end=END)
    W_bb_raw = build_bb(ev_bb, prices_bb.pct_change().index).reindex(columns=prices_bb.columns).fillna(0)
    res_bb = compute_capped_returns(ev_bb, prices_bb, W_bb_raw, BB_COST, "回购 #17")
    Path("research/event_driven/buyback_long_capped_oos_returns.parquet").parent.mkdir(exist_ok=True, parents=True)
    res_bb["returns"].rename("net_return").to_frame().to_parquet(
        "research/event_driven/buyback_long_capped_oos_returns.parquet"
    )

    # ============ DSR #23 EARNINGS PREVIEW ============
    print("\n[2/3] DSR #23 — 业绩预告 (capped)")
    ev_pv = load_pv(END)
    uni_pv = sorted(ev_pv["symbol"].dropna().unique().tolist())
    prices_pv = load_adj_price_wide(uni_pv, start=START, end=END)
    W_pv_raw = build_pv(ev_pv, prices_pv.pct_change().index).reindex(columns=prices_pv.columns).fillna(0)
    res_pv = compute_capped_returns(ev_pv, prices_pv, W_pv_raw, PV_COST, "预告 #23")
    res_pv["returns"].rename("net_return").to_frame().to_parquet(
        "research/event_driven/earnings_preview_capped_oos_returns.parquet"
    )

    # ============ DSR #24 ENSEMBLE ============
    print("\n[3/3] DSR #24 — 50/50 ensemble (capped)")
    df = pd.concat(
        [res_bb["returns"].rename("buyback"), res_pv["returns"].rename("preview")], axis=1
    ).dropna()
    ens = 0.5 * df["buyback"] + 0.5 * df["preview"]
    corr = df.corr().iloc[0, 1]
    ann = annualized_return(ens)
    sr = sharpe_ratio(ens)
    mdd = max_drawdown(ens)
    psr = probabilistic_sharpe(ens, sr_benchmark=0.0)
    boot = bootstrap_sharpe_ci(ens, n_boot=2000)
    gate = {
        "ann>15%": ann > 0.15,
        "sharpe>0.8": sr > 0.8,
        "mdd>-30%": mdd > -0.30,
        "PSR>0.95": psr > 0.95,
        "ci_low>0.5": boot["ci_low"] > 0.5,
    }
    print(f"  corr buyback vs preview (capped) = {corr:.3f}")
    print(f"  ann={ann:+.2%} Sharpe={sr:.2f} MDD={mdd:.2%} PSR={psr:.3f} CI_low={boot['ci_low']:.2f}")
    for k, v in gate.items():
        print(f"    {'PASS' if v else 'FAIL'} {k}")
    ens.rename("net_return").to_frame().to_parquet(
        "research/event_driven/ensemble_v1_capped_oos_returns.parquet"
    )

    print("\n" + "=" * 70)
    print("  SIDE-BY-SIDE: 报告值 (leveraged) vs 修正值 (capped)")
    print("=" * 70)
    def pct(x): return f"{x:+.2%}"
    def fl(x, n=2): return f"{x:.{n}f}"
    print(f"{'metric':<15}{'#17 orig':>15}{'#17 capped':>15}{'#23 orig':>15}{'#23 capped':>15}")
    print(f"{'ann':<15}{'+37.17%':>15}{pct(res_bb['ann']):>15}{'+17.26%':>15}{pct(res_pv['ann']):>15}")
    print(f"{'sharpe':<15}{'0.89':>15}{fl(res_bb['sharpe']):>15}{'0.60':>15}{fl(res_pv['sharpe']):>15}")
    print(f"{'mdd':<15}{'-79.16%':>15}{pct(res_bb['mdd']):>15}{'-48.53%':>15}{pct(res_pv['mdd']):>15}")
    print(f"{'psr':<15}{'0.991':>15}{fl(res_bb['psr'], 3):>15}{'0.965':>15}{fl(res_pv['psr'], 3):>15}")
    print(f"\n{'ensemble #24':<15}{'orig':>15}{'capped':>15}")
    print(f"{'ann':<15}{'+33.48%':>15}{pct(ann):>15}")
    print(f"{'sharpe':<15}{'0.91':>15}{fl(sr):>15}")
    print(f"{'mdd':<15}{'-46.55%':>15}{pct(mdd):>15}")
    print(f"{'psr':<15}{'0.995':>15}{fl(psr, 3):>15}")


if __name__ == "__main__":
    main()
