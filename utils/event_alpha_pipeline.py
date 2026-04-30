"""
A 路通用 event-alpha pipeline orchestrator.

抽自 research/event_alpha/lhb_phase2_crosstab.py + repurchase_event_study.py 的
共同 3-variant cross-tab + framework decision 模式. A 路下 4 个 candidate
(LHB / 回购 / 减持 / 调研) 都跑同样的:
  Variant A: 全部事件 (上界, 含 T+1 涨跌停)
  Variant B: 排 T+1 涨跌停 (tradeable)
  Variant C: 排涨跌停 + |signal| top X% (extreme tradeable)
+ time slice cross-tab + framework_strict_decision (only on B/C)

每候选只需写: load events + 算 signal + define subgroups (optional). 主流程
import 这个 orchestrator. 防 47% 复制.
"""
from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from utils.event_study import (
    cell_verdict,
    framework_strict_decision,
    quintile_spread,
)


def _filter_extreme(long_df: pd.DataFrame, signal_col: str,
                    top_pct: float, symbol_col: str) -> pd.DataFrame:
    """只保留 |signal| top_pct 的 events. 同 (symbol, event_date) 共享 signal."""
    ev_signal = long_df.groupby([symbol_col, "event_date"])[signal_col].first()
    threshold = ev_signal.abs().quantile(1 - top_pct)
    extreme_keys = set(ev_signal[ev_signal.abs() >= threshold].index)
    keep_mask = long_df.set_index([symbol_col, "event_date"]).index.isin(extreme_keys)
    return long_df[keep_mask].copy()


def _crosstab_print(
    out: dict,
    label: str,
    horizons: list[int],
    time_slices: list[tuple[str, str, str]],
    subgroup_labels: list[str],
):
    print(f"\n  ── {label} ──")
    print(f"  {'subgroup':<16} {'slice':<14} | "
          f"{'T+'+str(horizons[0])+' net':>9} {'t':>5} | "
          + "".join(f"{'T+'+str(h)+' net':>9} {'t':>5} | " for h in horizons[1:])
          + "verdict_T+" + str(horizons[1] if len(horizons) > 1 else horizons[0]))
    print("  " + "─" * (38 + 16 * len(horizons)))
    verdict_h = horizons[1] if len(horizons) > 1 else horizons[0]
    for sg in subgroup_labels:
        if sg not in out: continue
        for slabel, _, _ in time_slices:
            cells = out[sg][slabel]
            row = f"  {sg:<16} {slabel:<14} |"
            for h in horizons:
                m = cells[h]
                if m["spread_gross"] is None:
                    row += f" {'—':>9} {'—':>5} |"
                else:
                    row += f" {m['spread_net']*100:>+8.2f}% {m['t_stat']:>+5.1f} |"
            v = cells[verdict_h]
            row += f" {cell_verdict(v['spread_net'], v['t_stat'])}"
            print(row)


def crosstab_one_variant(
    long_df: pd.DataFrame,
    *,
    signal_col: str,
    horizons: list[int],
    time_slices: list[tuple[str, str, str]],
    subgroup_col: Optional[str] = None,
    subgroups: Optional[list[str]] = None,
    cost_per_side: float = 0.0025,
    n_legs: int = 2,
    symbol_col: str = "symbol",
) -> dict:
    """对 long_df 跑 (subgroups × time slices × horizons) cross-tab.

    subgroup_col=None → 单 'all' subgroup, 输出 {'all': {slabel: {h: ...}}}.
    subgroup_col='reason_cat' + subgroups list → 每 reason_cat 跑.
    """
    if subgroup_col is None:
        sg_iter = [("all", long_df)]
    else:
        sg_iter = [(sg, long_df[long_df[subgroup_col] == sg])
                   for sg in (subgroups or sorted(long_df[subgroup_col].dropna().unique()))]

    out: dict = {}
    for sg_label, sub_sg in sg_iter:
        if len(sub_sg) == 0:
            continue
        out[sg_label] = {}
        for slabel, s, e in time_slices:
            mask = ((sub_sg["event_date"] >= pd.Timestamp(s))
                    & (sub_sg["event_date"] <= pd.Timestamp(e)))
            sub = sub_sg[mask]
            sl = quintile_spread(sub, signal_col=signal_col, horizons=horizons,
                                 cost_per_side=cost_per_side, n_legs=n_legs,
                                 skip_overnight_gap=True)
            out[sg_label][slabel] = sl
    return out


def run_3variant_pipeline(
    long_df: pd.DataFrame,
    *,
    signal_col: str,
    limit_col: str,
    horizons: list[int],
    time_slices: list[tuple[str, str, str]],
    subgroup_col: Optional[str] = None,
    subgroups: Optional[list[str]] = None,
    extreme_top_pct: float = 0.10,
    cost_per_side: float = 0.0025,
    n_legs: int = 2,
    oos_slice_label: str = "T3_2024_2026",
    is_slice_labels: tuple[str, ...] = ("T1_2015_2019", "T2_2020_2023"),
    candidate_name: str = "candidate",
    next_candidate: str = "下一候选",
    symbol_col: str = "symbol",
    print_tables: bool = True,
) -> dict:
    """A 路通用 3-variant cross-tab + framework decision orchestrator.

    输入:
        long_df: utils.event_study.compute_event_abn_returns 的输出, 必含
                 [symbol_col, event_date, rel_day, abn_ret, signal_col, limit_col]
        signal_col: signal 列名 (用于 quintile)
        limit_col: bool 列名, True = T+1 涨跌停 → variant B/C 排除
        horizons: 报告 horizon list, e.g. [1, 5, 10]
        time_slices: [(label, start, end)] 三元组
        subgroup_col / subgroups: None → 单 'all' subgroup
        candidate_name / next_candidate: 决策打印时用 (e.g. "回购预案" / "减持冷静期")

    返回 dict: {variant_A_all, variant_B_no_limit, variant_C_extreme_no_limit, decision}
    """
    sg_labels = (subgroups if subgroups
                 else (["all"] if subgroup_col is None
                       else sorted(long_df[subgroup_col].dropna().unique())))

    # Variant A: 全事件
    if print_tables:
        print(f"\n[crosstab A] 全部事件 (含 T+1 涨跌停, 不可交易上界)")
    out_a = crosstab_one_variant(long_df, signal_col=signal_col, horizons=horizons,
                                  time_slices=time_slices, subgroup_col=subgroup_col,
                                  subgroups=subgroups, cost_per_side=cost_per_side,
                                  n_legs=n_legs, symbol_col=symbol_col)
    if print_tables:
        _crosstab_print(out_a, "A_all (上界)", horizons, time_slices, sg_labels)

    # Variant B: 排涨跌停
    long_b = long_df[~long_df[limit_col]].copy()
    if print_tables:
        print(f"\n[crosstab B] 排 T+1 涨跌停 (tradeable, n={long_b.groupby([symbol_col,'event_date']).ngroups:,})")
    out_b = crosstab_one_variant(long_b, signal_col=signal_col, horizons=horizons,
                                  time_slices=time_slices, subgroup_col=subgroup_col,
                                  subgroups=subgroups, cost_per_side=cost_per_side,
                                  n_legs=n_legs, symbol_col=symbol_col)
    if print_tables:
        _crosstab_print(out_b, "B_no_limit (tradeable)", horizons, time_slices, sg_labels)

    # Variant C: 排涨跌停 + extreme top X%
    long_c = _filter_extreme(long_b, signal_col, extreme_top_pct, symbol_col)
    if print_tables:
        print(f"\n[crosstab C] 排涨跌停 + |signal| top {int(extreme_top_pct*100)}% "
              f"(n={long_c.groupby([symbol_col,'event_date']).ngroups:,})")
    out_c = crosstab_one_variant(long_c, signal_col=signal_col, horizons=horizons,
                                  time_slices=time_slices, subgroup_col=subgroup_col,
                                  subgroups=subgroups, cost_per_side=cost_per_side,
                                  n_legs=n_legs, symbol_col=symbol_col)
    if print_tables:
        _crosstab_print(out_c, f"C_extreme_no_limit (top {int(extreme_top_pct*100)}%)",
                        horizons, time_slices, sg_labels)

    # framework decision (only B/C, A 含涨跌停 是不可执行上界)
    decision = framework_strict_decision(
        {"B_no_limit": out_b, "C_extreme_no_limit": out_c},
        horizons=horizons,
        oos_slice_label=oos_slice_label,
        is_slice_labels=is_slice_labels,
    )

    if print_tables:
        print("\n" + "=" * 100)
        print(f"{candidate_name} 方向死活判定 (framework Live-Tier 1 严格门, 只看 B/C tradeable)")
        print("=" * 100)
        print(f"\n  OOS PASS cell 数: {len(decision['oos_pass_cells'])} (loose 判定, 仅参考)")
        for w in decision["oos_pass_cells"][:5]:
            print(f"    [loose] {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                  f"net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,}")
        print(f"\n  Framework PASS: {len(decision['framework_pass'])}")
        if decision["framework_pass"]:
            print(f"\n  ✅ 有 framework PASS, 继续 Phase 3 写 spec ({candidate_name}):")
            for w in decision["framework_pass"]:
                print(f"    {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                      f"OOS net {w['oos_net']*100:+.2f}% t={w['oos_t']:+.2f} n={w['n_events']:,} "
                      f"worst slice drag {w['worst_drag_nav']*100:.3f}% NAV/yr")
        else:
            print(f"\n  ❌ 无 framework PASS. **杀 {candidate_name} 方向**, 转 {next_candidate}.")
            if decision["framework_rejected"]:
                print("\n  Top 3 rejected (按 OOS net 排) — 离 framework PASS 最近的:")
                for w in decision["framework_rejected"][:3]:
                    print(f"    {w['variant']:<22} {w['subgroup']:<16} T+{w['horizon']:<2}  "
                          f"OOS net {w['oos_net']*100:+.2f}% / "
                          f"failed slices {[(s, f'{n*100:+.2f}%') for s, n in w['fail_slices_net_ann']]} / "
                          f"worst drag {w['worst_drag_nav']*100:.3f}% NAV/yr")

    return {
        "variant_A_all": out_a,
        "variant_B_no_limit": out_b,
        "variant_C_extreme_no_limit": out_c,
        "decision": decision,
    }
