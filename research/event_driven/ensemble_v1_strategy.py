"""回购 + 业绩预告 ensemble long-only — 预注册 (DSR trial #24, 2026-04-18).

### 前因
DSR #17 (回购 long-only) 4/5 PASS: ann 37% Sharpe 0.89 MDD -79% +27% excess
DSR #23 (业绩预告 drift) 2/5 PASS: ann 17% Sharpe 0.60 MDD -48% +7% excess
两信号都 real alpha 但都 fail MDD. 本 #24 测试 ensemble 是否降 MDD.

### 假设
两独立 event-driven alpha 源 (mgmt buyback 信号 vs earnings surprise
信号) **低相关**, ensemble 理论上 Sharpe ↑ MDD ↓.
若 MDD 改善不足 30%, 证明 A 股 long-only alpha 共同暴露 2018/2022 熊市
系统风险, 无法通过纯 ensemble 消除 — 需要 dynamic hedge.

### Pre-registration spec (零自由度)
- 两子策略权重: **50/50** (equal-weight, 无 vol-target 调优)
- 每日 ret = 0.5 × ret_buyback_#17 + 0.5 × ret_preview_#23
- 成本已在各自子策略内扣除
- 数据源: research/event_driven/{buyback_long_oos_returns,earnings_preview_oos_returns}.parquet

### Admission gates (不变)
ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5

### 红线
- FAIL → **Phase 3 最终终结**. jialong 选 option A/C (不 iterate ensemble)
- PASS → paper-trade OOS 候选 #2, Phase 3 complete

### DSR: 24 (cumulative penalty n=24)
"""
from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from utils.metrics import (
    annualized_return,
    bootstrap_sharpe_ci,
    max_drawdown,
    performance_summary,
    probabilistic_sharpe,
    sharpe_ratio,
)

logger = logging.getLogger(__name__)

BUYBACK_RET = Path("research/event_driven/buyback_long_oos_returns.parquet")
PREVIEW_RET = Path("research/event_driven/earnings_preview_oos_returns.parquet")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    r_bb = pd.read_parquet(BUYBACK_RET)["net_return"]
    r_pv = pd.read_parquet(PREVIEW_RET)["net_return"]
    logger.info(f"buyback: {r_bb.shape}, preview: {r_pv.shape}")

    df = pd.concat([r_bb.rename("buyback"), r_pv.rename("preview")], axis=1).dropna()
    logger.info(f"aligned: {df.shape}, corr = {df.corr().iloc[0,1]:.3f}")

    net_ret = 0.5 * df["buyback"] + 0.5 * df["preview"]

    summary = performance_summary(net_ret, name="Ensemble_Buyback_Preview")
    print("\n" + "=" * 60)
    print("  回购 + 预告 50/50 ensemble OOS DSR #24")
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
    print("\n=== 预注册 Admission Gate (DSR trial #24) ===")
    for k, v in gate.items():
        print(f"  {'PASS' if v else 'FAIL'} {k}")
    print(f"\n  PSR = {psr:.3f}")
    print(f"  Sharpe 95% CI = [{boot['ci_low']:.2f}, {boot['ci_high']:.2f}]")
    print(f"  子策略相关系数 = {df.corr().iloc[0,1]:.3f}")

    # Component breakdown
    for name, s in [("buyback #17", df["buyback"]), ("preview #23", df["preview"])]:
        print(f"  {name}: ann {annualized_return(s):+.2%}, Sharpe {sharpe_ratio(s):.2f}, MDD {max_drawdown(s):.2%}")

    out_path = Path("research/event_driven/ensemble_v1_oos_returns.parquet")
    net_ret.rename("net_return").to_frame().to_parquet(out_path)
    logger.info(f"P&L 落盘: {out_path}")

    if all(gate.values()):
        print("\nPASS — paper-trade 候选 #2, Phase 3 complete")
    else:
        print("\nFAIL — Phase 3 最终终结, 交 jialong 选 option A/C")


if __name__ == "__main__":
    main()
