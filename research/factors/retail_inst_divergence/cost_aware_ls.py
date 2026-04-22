"""
RIAD cost-aware long-short backtest

在 size+industry 双中性化因子的基础上, 把 IC 翻译成可执行策略:
    1. 每月末按因子分 5 组 (Q1-Q5)
    2. Long Q1 (或 Q2-Q3, 见分层倒 U) / Short Q5, 等权
    3. 20 日调仓, 双边 0.3% 成本 (单边 0.15%)
    4. 输出累计收益曲线、Sharpe、MDD, 对比 benchmark (等权全 A)

结论目标: 验证 RIAD 是否在**实盘成本**下仍有 positive risk-adjusted alpha.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

from research.factors.retail_inst_divergence.factor import (  # noqa: E402
    build_attention_panel,
    compute_riad_factor,
)
from research.factors.retail_inst_divergence.evaluate_riad import (  # noqa: E402
    PRICE_PATH,
    load_forward_returns,
)
from research.factors.retail_inst_divergence.industry_eval import (  # noqa: E402
    load_industry_series,
)
from research.factors.retail_inst_divergence.neutralize_eval import (  # noqa: E402
    load_circ_mv_wide,
    size_neutralize,
)
from utils.factor_analysis import industry_neutralize_fast  # noqa: E402

START, END = "2023-10-01", "2025-12-31"
FWD_DAYS = 20  # 调仓周期
COST_ONE_WAY = 0.0015  # 单边 0.15%


def monthly_ls_backtest(
    factor: pd.DataFrame,
    price: pd.DataFrame,
    modes: list[str],
    hold_days: int = 20,
) -> dict:
    """
    每 hold_days 日调仓, 按 factor 分 5 组, 计算不同组合多空收益 (毛 + 净).

    modes:
        "Q1_minus_Q5"  — 做多 Q1 (因子最低), 做空 Q5 (因子最高)
        "Q2Q3_minus_Q5"— 做多 Q2+Q3 等权, 做空 Q5 (基于倒 U 形发现)
        "Q1_long_only" — 只做多 Q1
        "Q5_short_only"— 只做空 Q5 (注意 A 股融券受限, 参考用)
    """
    # 对齐: 因子用每 hold_days 日的第一天作为调仓日
    all_dates = factor.index.intersection(price.index)
    rebal_dates = all_dates[::hold_days]

    # 调仓日 → 组合成员
    positions = {m: [] for m in modes}
    returns = {m: [] for m in modes}
    turnover = {m: [] for m in modes}
    prev_long = {m: set() for m in modes}
    prev_short = {m: set() for m in modes}

    # price 的 columns 是 6 位, factor 是 ts_code. 对齐要给 price columns 加后缀.
    def _to_ts(sym: str) -> str:
        if sym.startswith(("60", "68")):
            return f"{sym}.SH"
        if sym.startswith(("00", "30")):
            return f"{sym}.SZ"
        if sym[:1] in ("4", "8"):
            return f"{sym}.BJ"
        return f"{sym}.SZ"

    px = price.copy()
    px.columns = [_to_ts(c) for c in px.columns]

    for i, d in enumerate(rebal_dates[:-1]):
        f_row = factor.loc[d].dropna()
        if len(f_row) < 100:
            continue

        # 分 5 组
        labels = pd.qcut(f_row, q=5, labels=False, duplicates="drop")
        q1 = set(f_row.index[labels == 0])
        q2 = set(f_row.index[labels == 1])
        q3 = set(f_row.index[labels == 2])
        q5 = set(f_row.index[labels == 4])

        # 持有 hold_days 日 的收益: px[d+hold] / px[d] - 1
        next_d = rebal_dates[i + 1]
        p_start = px.loc[d]
        p_end = px.loc[next_d]
        hold_ret = (p_end / p_start - 1.0).dropna()

        for m in modes:
            if m == "Q1_minus_Q5":
                long_set, short_set = q1, q5
            elif m == "Q2Q3_minus_Q5":
                long_set, short_set = (q2 | q3), q5
            elif m == "Q1_long_only":
                long_set, short_set = q1, set()
            elif m == "Q5_short_only":
                long_set, short_set = set(), q5
            else:
                continue

            long_syms = [s for s in long_set if s in hold_ret.index]
            short_syms = [s for s in short_set if s in hold_ret.index]

            long_ret = hold_ret[long_syms].mean() if long_syms else 0.0
            short_ret = hold_ret[short_syms].mean() if short_syms else 0.0

            # turnover: 这一期 vs 上一期组合的 symmetric difference / 组合规模
            turn_long = len((long_set ^ prev_long[m])) / max(len(long_set) + len(prev_long[m]), 1)
            turn_short = len((short_set ^ prev_short[m])) / max(len(short_set) + len(prev_short[m]), 1)
            turn_avg = (turn_long + turn_short) / 2 if short_set else turn_long
            prev_long[m], prev_short[m] = long_set, short_set

            if m.endswith("long_only"):
                gross = long_ret
            elif m.endswith("short_only"):
                gross = -short_ret
            else:
                gross = long_ret - short_ret

            # 成本 = turnover × 2 (buy+sell) × one-way cost
            cost = turn_avg * 2 * COST_ONE_WAY
            net = gross - cost

            positions[m].append({
                "date": str(d.date()),
                "long": len(long_syms),
                "short": len(short_syms),
                "gross_ret": float(gross),
                "net_ret": float(net),
                "turnover": float(turn_avg),
            })
            returns[m].append(net)
            turnover[m].append(turn_avg)

    # 汇总
    out = {}
    for m in modes:
        rets = np.array(returns[m], dtype=float)
        if len(rets) == 0:
            continue
        periods_per_year = 252 / hold_days
        ann_ret = rets.mean() * periods_per_year
        ann_vol = rets.std(ddof=1) * np.sqrt(periods_per_year)
        sharpe = ann_ret / ann_vol if ann_vol > 0 else np.nan
        cum = np.cumprod(1 + rets) - 1
        peak = np.maximum.accumulate(np.cumprod(1 + rets))
        drawdown = (np.cumprod(1 + rets) - peak) / peak
        mdd = drawdown.min() if len(drawdown) else 0.0
        avg_turn = float(np.mean(turnover[m]))
        out[m] = {
            "periods": len(rets),
            "mean_ret_per_period": float(rets.mean()),
            "std_ret_per_period": float(rets.std(ddof=1)),
            "ann_return": float(ann_ret),
            "ann_vol": float(ann_vol),
            "sharpe": float(sharpe) if not np.isnan(sharpe) else None,
            "max_drawdown": float(mdd),
            "avg_turnover": avg_turn,
            "total_cost_drag_pct": float(avg_turn * 2 * COST_ONE_WAY * periods_per_year),
            "final_cum_net": float(cum[-1]) if len(cum) else 0.0,
        }
    return out


def main() -> None:
    price = pd.read_parquet(PRICE_PATH)
    cal = price.loc[START:END].index
    print(f"交易日历: {len(cal)} 日")

    # 构造 size+industry 双中性化因子
    panels = build_attention_panel(START, END, cal)
    raw = compute_riad_factor(panels["retail_attn"], panels["inst_attn"])
    circ_mv = load_circ_mv_wide(START, END)
    size_n = size_neutralize(raw, circ_mv)
    ind_series = load_industry_series()
    factor = industry_neutralize_fast(size_n, ind_series)

    # shift 1 日保证信号不泄漏
    factor_exec = factor.shift(1)

    modes = ["Q1_minus_Q5", "Q2Q3_minus_Q5", "Q1_long_only", "Q5_short_only"]
    results_is = monthly_ls_backtest(
        factor_exec.loc["2023-10-01":"2024-12-31"],
        price.loc["2023-10-01":"2024-12-31"],
        modes, hold_days=FWD_DAYS,
    )
    results_oos = monthly_ls_backtest(
        factor_exec.loc["2025-01-01":"2025-12-31"],
        price.loc["2025-01-01":"2025-12-31"],
        modes, hold_days=FWD_DAYS,
    )
    results_full = monthly_ls_backtest(
        factor_exec.loc["2023-10-01":"2025-12-31"],
        price.loc["2023-10-01":"2025-12-31"],
        modes, hold_days=FWD_DAYS,
    )

    print("\n=== RIAD cost-aware (双边 0.3%) backtest ===\n")
    header = f"{'Mode':<20} {'Period':<18} {'Ann%':>8} {'Vol%':>7} {'Sharpe':>7} {'MDD%':>8} {'AvgTurn':>8} {'CumNet%':>8}"
    print(header)
    print("-" * len(header))
    for name, res_set in [("IS 2023-10~2024-12", results_is),
                           ("OOS 2025", results_oos),
                           ("FULL", results_full)]:
        for m, r in res_set.items():
            sr = r["sharpe"] if r["sharpe"] is not None else float("nan")
            print(
                f"{m:<20} {name:<18} "
                f"{r['ann_return']*100:>7.2f} "
                f"{r['ann_vol']*100:>6.2f} "
                f"{sr:>7.2f} "
                f"{r['max_drawdown']*100:>7.2f} "
                f"{r['avg_turnover']:>7.2%} "
                f"{r['final_cum_net']*100:>7.2f}"
            )

    stamp = datetime.now().strftime("%Y%m%d")
    out_json = ROOT / "logs" / f"riad_cost_aware_{stamp}.json"
    with open(out_json, "w") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "factor": "RIAD (size + SW1 industry neutral, shift-1)",
                "cost_one_way": COST_ONE_WAY,
                "hold_days": FWD_DAYS,
                "IS": results_is,
                "OOS": results_oos,
                "FULL": results_full,
            },
            f,
            indent=2,
            ensure_ascii=False,
        )
    print(f"\n保存: {out_json}")


if __name__ == "__main__":
    main()
