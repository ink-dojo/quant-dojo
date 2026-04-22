"""DSR #30 单独 5-gate + WF 验证 (spec v2 §9 item 1).

动机
----
旧 wf_and_stress.py 是 DSR #30 + DSR #33 50/50 的 ensemble 验证. 2026-04-21
alpha decay 诊断确认 DSR #33 2024-2025 SR -1.86 — ensemble 作废. paper-trade
spec v2 §9 明确要求 "DSR #30 单独重跑完整 5-gate + WF (确认去掉 #33 后真实
gate pass 数)". 本脚本单独对 BB / PV / BB+PV 50/50 三种 variant 跑:

  - 标准 5-gate (ann>15%, Sharpe>0.8, MDD>-30%, PSR>0.95, CI_low>0.5)
  - Walk-forward 2yr × 6mo step: median SR > 0.5 且 Q25 > 0
  - Regime split: bull/bear/sideways 中至少 2/3 过 (SR>0.5, MDD>-35%)
  - Trade-level (BB-only): win-rate > 45%, top-5 集中度 < 20%
  - Year-by-year 表

输入: research/event_driven/dsr30_mainboard_{bb,pv,recal_ensemble}_oos.parquet
输出: portfolio/public/data/event_driven/dsr30_standalone_wf.json
      + 控制台打印
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

import numpy as np
import pandas as pd

from research.event_driven.buyback_long_only_strategy import (
    HOLD_DAYS as BB_HOLD,
    POST_OFFSET as BB_OFFSET,
    SIGNAL_COL as BB_SIGNAL_COL,
    TOP_PCT as BB_TOP_PCT,
    load_events as load_bb_events,
)
from research.event_driven.dsr30_mainboard_recal import (
    MAIN_BOARD_SYMBOLS,
    filter_mainboard,
)
from research.event_driven.wf_and_stress import (
    regime_split,
    wf_stats,
    year_by_year,
)
from utils.local_data_loader import load_adj_price_wide
from utils.metrics import (
    annualized_return,
    bootstrap_sharpe_ci,
    max_drawdown,
    probabilistic_sharpe,
    sharpe_ratio,
)

logger = logging.getLogger(__name__)
REPO = Path(__file__).parent.parent.parent
OUT_DIR = REPO / "portfolio" / "public" / "data" / "event_driven"
START, END = "2018-01-01", "2025-12-31"


def load_net(path: Path) -> pd.Series:
    df = pd.read_parquet(path)
    s = df.iloc[:, 0]
    s.index = pd.to_datetime(s.index)
    return s.sort_index().dropna()


# ----------------------------------------------------------------------
# 5-gate
# ----------------------------------------------------------------------
def five_gate(ret: pd.Series, label: str) -> dict:
    ann = float(annualized_return(ret))
    sr = float(sharpe_ratio(ret))
    mdd = float(max_drawdown(ret))
    psr = float(probabilistic_sharpe(ret, sr_benchmark=0.0))
    boot = bootstrap_sharpe_ci(ret, n_boot=2000)
    ci_low = float(boot["ci_low"])
    ci_high = float(boot["ci_high"])
    gates = {
        "ann_gt_15": ann > 0.15,
        "sharpe_gt_08": sr > 0.8,
        "mdd_gt_minus_30": mdd > -0.30,
        "psr_gt_095": psr > 0.95,
        "ci_low_gt_05": ci_low > 0.5,
    }
    n_pass = int(sum(gates.values()))
    return {
        "label": label,
        "ann": ann, "sharpe": sr, "mdd": mdd, "psr": psr,
        "ci_low": ci_low, "ci_high": ci_high,
        "gates": gates, "n_pass": n_pass,
        "n_obs": int(len(ret)),
        "window": f"{ret.index[0].strftime('%Y-%m-%d')} ~ {ret.index[-1].strftime('%Y-%m-%d')}",
    }


# ----------------------------------------------------------------------
# Trade-level (BB 主板 rescaled)
# ----------------------------------------------------------------------
def trade_level_bb() -> dict:
    """单交易级 P&L: 月度 top-30% buyback 主板, T+1 进, 20d 持."""
    ev = load_bb_events(END)
    ev = filter_mainboard(ev)  # 主板过滤
    universe = sorted(ev["symbol"].dropna().unique().tolist())
    prices = load_adj_price_wide(universe, start=START, end=END)
    rets = prices.pct_change().where(lambda x: x.abs() < 0.25)

    td_arr = rets.index.values
    ev = ev.copy()
    ev["month"] = ev["event_date"].dt.to_period("M")

    trades = []
    for _, grp in ev.groupby("month", observed=True):
        grp = grp.sort_values(BB_SIGNAL_COL, ascending=False)
        if len(grp) < 10:
            continue
        n_top = max(1, int(np.floor(len(grp) * BB_TOP_PCT)))
        for _, r in grp.iloc[:n_top].iterrows():
            t = np.datetime64(r["event_date"])
            i_t = int(np.searchsorted(td_arr, t, side="left"))
            i_open = min(len(td_arr), i_t + BB_OFFSET)
            i_close = min(len(td_arr), i_open + BB_HOLD)
            if i_open >= i_close or r["symbol"] not in rets.columns:
                continue
            seg = rets[r["symbol"]].iloc[i_open:i_close].dropna()
            if len(seg) == 0:
                continue
            pnl = float((1 + seg).prod() - 1)
            trades.append({
                "symbol": r["symbol"],
                "event_date": r["event_date"].strftime("%Y-%m-%d"),
                "pnl": pnl,
                "n_days": int(len(seg)),
            })
    tdf = pd.DataFrame(trades)
    if tdf.empty:
        return {"n_trades": 0, "note": "no trades"}
    total_pnl = tdf["pnl"].sum()
    contrib = tdf.groupby("symbol")["pnl"].sum().sort_values(ascending=False)
    top5 = contrib.head(5).to_dict()
    bottom5 = contrib.tail(5).to_dict()
    top5_share = float(contrib.iloc[:5].sum() / total_pnl) if total_pnl != 0 else 0.0
    return {
        "n_trades": int(len(tdf)),
        "win_rate": float((tdf["pnl"] > 0).mean()),
        "avg_pnl": float(tdf["pnl"].mean()),
        "median_pnl": float(tdf["pnl"].median()),
        "pnl_p05": float(tdf["pnl"].quantile(0.05)),
        "pnl_p95": float(tdf["pnl"].quantile(0.95)),
        "avg_holding_days": float(tdf["n_days"].mean()),
        "top5_symbols_pnl": {str(k): float(v) for k, v in top5.items()},
        "bottom5_symbols_pnl": {str(k): float(v) for k, v in bottom5.items()},
        "top5_contribution_share": top5_share,
        "gate_win_rate_gt_45": bool((tdf["pnl"] > 0).mean() > 0.45),
        "gate_top5_concentration_lt_20pct": bool(top5_share < 0.20),
    }


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------
def main():
    logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(levelname)s %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 72)
    print("DSR #30 standalone — 5-gate + WF + regime + trade-level")
    print("=" * 72)

    r_bb = load_net(REPO / "research/event_driven/dsr30_mainboard_bb_oos.parquet")
    r_pv = load_net(REPO / "research/event_driven/dsr30_mainboard_pv_oos.parquet")
    r_ens = load_net(REPO / "research/event_driven/dsr30_mainboard_recal_ensemble_oos.parquet")

    variants = {
        "bb": ("BB 主板 rescaled", r_bb),
        "pv": ("PV 主板 rescaled", r_pv),
        "ens": ("BB+PV 50/50 ensemble", r_ens),
    }

    # 5-gate
    print("\n" + "=" * 72)
    print("  5-gate on single-sample (2018-2025)")
    print("=" * 72)
    gate = {}
    for k, (label, ret) in variants.items():
        g = five_gate(ret, label)
        gate[k] = g
        print(f"\n{label}:")
        print(f"  ann {g['ann']:+.2%}  Sharpe {g['sharpe']:.2f}  MDD {g['mdd']:.2%}  "
              f"PSR {g['psr']:.3f}  CI [{g['ci_low']:.2f}, {g['ci_high']:.2f}]")
        for gk, gv in g["gates"].items():
            print(f"    {'PASS' if gv else 'FAIL'}  {gk}")
        print(f"  → {g['n_pass']}/5 PASS")

    # WF
    print("\n" + "=" * 72)
    print("  Walk-forward (2yr window, 6mo step)")
    print("=" * 72)
    wf = {}
    for k, (label, ret) in variants.items():
        w = wf_stats(ret, label)
        wf[k] = w
        print(f"\n{label}:")
        print(f"  windows: {w['n_windows']}")
        print(f"  Sharpe: median {w['sharpe_median']:+.2f}  "
              f"Q25 {w['sharpe_q25']:+.2f}  Q75 {w['sharpe_q75']:+.2f}  "
              f"[{w['sharpe_min']:+.2f}, {w['sharpe_max']:+.2f}]")
        print(f"  ann median {w['ann_median']:+.2%}  MDD median {w['mdd_median']:.2%}  "
              f"worst {w['mdd_worst']:.2%}")
        print(f"  gates: median>0.5 {w['gate_median_gt_05']}  Q25>0 {w['gate_q25_gt_0']}")

    # Regime split
    print("\n" + "=" * 72)
    print("  Regime split (bull / bear / sideways)")
    print("=" * 72)
    reg = {}
    for k, (label, ret) in variants.items():
        rg = regime_split(ret, label)
        reg[k] = rg
        print(f"\n{label}:")
        for regime, m in rg["regimes"].items():
            print(f"  {regime:10s}  ann {m['ann']:+.2%}  SR {m['sharpe']:+.2f}  "
                  f"MDD {m['mdd']:.2%}  (n={m['n_obs']})")
        print(f"  pass: {rg['n_pass']}/3  (≥2 required: {rg['gate_2of3_pass']})")

    # Year-by-year (BB-only)
    print("\n" + "=" * 72)
    print("  Year-by-year (BB 主板 rescaled)")
    print("=" * 72)
    yby = {k: year_by_year(v[1]) for k, v in variants.items()}
    for row in yby["bb"]:
        print(f"  {row['year']}  ret {row['ret_total']:+.2%}  "
              f"SR {row['sharpe']:+.2f}  MDD {row['mdd']:.2%}  (n={row['n_obs']})")

    # Trade-level (BB only)
    print("\n" + "=" * 72)
    print("  Trade-level (BB 主板 rescaled)")
    print("=" * 72)
    tl = trade_level_bb()
    if "note" in tl:
        print(f"  {tl['note']}")
    else:
        print(f"  n_trades         = {tl['n_trades']}")
        print(f"  win_rate         = {tl['win_rate']:.1%}")
        print(f"  avg_pnl          = {tl['avg_pnl']:+.3%}")
        print(f"  median_pnl       = {tl['median_pnl']:+.3%}")
        print(f"  p05 / p95        = {tl['pnl_p05']:+.3%} / {tl['pnl_p95']:+.3%}")
        print(f"  avg holding days = {tl['avg_holding_days']:.1f}")
        print(f"  top5 share       = {tl['top5_contribution_share']:.1%}")
        print(f"  gates: win>45% {tl['gate_win_rate_gt_45']}  "
              f"top5<20% {tl['gate_top5_concentration_lt_20pct']}")

    # Final production-grade verdict (per variant)
    print("\n" + "=" * 72)
    print("  Production-grade verdict (5-gate + WF + regime + trade-level)")
    print("=" * 72)
    verdict = {}
    for k, (label, _) in variants.items():
        g5 = gate[k]["n_pass"] == 5
        gate_single = gate[k]["n_pass"]
        wf_pass = wf[k]["gate_median_gt_05"] and wf[k]["gate_q25_gt_0"]
        reg_pass = reg[k]["gate_2of3_pass"]
        tl_pass = (
            tl.get("gate_win_rate_gt_45", False)
            and tl.get("gate_top5_concentration_lt_20pct", False)
        ) if k == "bb" else None  # trade-level only ran for BB
        per = {
            "single_sample_gate_5_of_5": g5,
            "single_sample_n_pass": gate_single,
            "wf_median_gt_05_and_q25_gt_0": wf_pass,
            "regime_2_of_3_pass": reg_pass,
            "trade_level_pass": tl_pass,
        }
        passing = [
            per["single_sample_gate_5_of_5"],
            per["wf_median_gt_05_and_q25_gt_0"],
            per["regime_2_of_3_pass"],
        ]
        if per["trade_level_pass"] is not None:
            passing.append(per["trade_level_pass"])
        n_prod_pass = sum(bool(x) for x in passing)
        per["n_production_gates_pass"] = n_prod_pass
        per["n_production_gates_total"] = len(passing)
        verdict[k] = per
        print(f"\n{label}:")
        print(f"  single-sample 5-gate: {gate_single}/5  "
              f"({'✅' if g5 else '❌'} 5/5)")
        print(f"  WF median>0.5 & Q25>0: {'✅' if wf_pass else '❌'}")
        print(f"  Regime ≥2/3: {'✅' if reg_pass else '❌'}")
        if per["trade_level_pass"] is not None:
            print(f"  Trade-level (win>45%, top5<20%): "
                  f"{'✅' if per['trade_level_pass'] else '❌'}")
        print(f"  → {n_prod_pass}/{per['n_production_gates_total']} 生产级门过")

    # Write JSON
    out = {
        "generated_at": pd.Timestamp.now().strftime("%Y-%m-%d %H:%M"),
        "window": f"{START} ~ {END}",
        "single_sample_gate": gate,
        "walk_forward": wf,
        "regime_split": reg,
        "year_by_year": yby,
        "trade_level_bb": tl,
        "production_verdict": verdict,
    }
    out_path = OUT_DIR / "dsr30_standalone_wf.json"
    out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=float))
    print(f"\n保存: {out_path.relative_to(REPO)}")


if __name__ == "__main__":
    main()
