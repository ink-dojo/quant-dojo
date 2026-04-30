"""
Stacking 评估: roe_stability × inst_flow_20d (Issue #46).

输入:
    research.factors.tushare_factors.neutralize_and_cost 里的中性化路径
    (size + SW-L1 OLS 残差化, 然后截面 rank).

度量:
    1. IC 序列 Pearson + Spearman corr
    2. 月频 L-S (Qn − Q1) 收益序列 Pearson corr
    3. 等权 stacking (rank 平均后再做 quintile L-S) 的 sharpe vs 单腿
    4. cost 后净 sharpe 比较 (双边 0.3%, 月频)

输出:
    research/factors/tushare_factors/stacking_results.json (gitignored)
    控制台打印 corr 矩阵 + stacking sharpe 对比

执行:
    python research/factors/tushare_factors/stacking_analysis.py
"""
import json
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(ROOT))

from research.factors.tushare_factors.factor_research import (  # noqa: E402
    build_inst_flow,
    build_roe_stability,
)
from research.factors.tushare_factors.neutralize_and_cost import (  # noqa: E402
    HORIZON,
    MIN_STOCKS_FOR_IC,
    Direction,
    build_df_info,
    build_price_panel,
    build_size_panel,
    cost_aware_long_short,
    load_industry_l1,
    long_short_periods,
    resolve_stock_pools,
)
from research.factors.tushare_factors.factor_research import (  # noqa: E402
    compute_forward_returns,
)
from utils.factor_analysis import (  # noqa: E402
    compute_ic_series,
    cross_section_rank,
    neutralize_factor,
)

warnings.filterwarnings("ignore")

DATA = ROOT / "data" / "raw" / "tushare"
OUT = ROOT / "research" / "factors" / "tushare_factors"


def monthly_long_short_gross(
    factor_wide: pd.DataFrame,
    fwd_ret: pd.DataFrame,
    direction: Direction,
    n_groups: int = 5,
) -> pd.Series:
    """月频 gross L-S 序列, 用于序列 corr; 复用 long_short_periods 的 rebal 逻辑."""
    df = long_short_periods(factor_wide, fwd_ret, direction, n_groups=n_groups)
    return df["gross"].rename(f"ls_{direction}") if not df.empty else pd.Series(dtype=float, name=f"ls_{direction}")


def run() -> dict:
    print("=" * 72)
    print("Stacking 评估: roe_stability × inst_flow_20d  (Issue #46)")
    print("=" * 72)

    # 1. 股票池
    pools = resolve_stock_pools()
    core_stocks, quality_stocks = pools["core"], pools["quality"]
    print(f"\n股票池: core={len(core_stocks)} quality={len(quality_stocks)}")

    # 2. 价格 + 前向收益 + size + 行业 + df_info
    print("\n[Step 1] 价格 / size / 行业 / 前向收益")
    price_wide = build_price_panel(core_stocks, "20200101", "20251231")
    fwd_ret = compute_forward_returns(price_wide, horizon=HORIZON)
    size_panel = build_size_panel(core_stocks, price_wide.index)
    industry_l1 = load_industry_l1()
    df_info = build_df_info(size_panel, industry_l1)

    # 3. 构造 + 中性化两个 winner 因子
    print("\n[Step 2] 构造 + 中性化 (size + SW-L1)")
    f_inst = build_inst_flow(core_stocks).reindex(price_wide.index)
    f_roe = build_roe_stability(quality_stocks, price_wide.index).reindex(price_wide.index)

    r_inst = cross_section_rank(neutralize_factor(f_inst, df_info, n_sigma=3.0))
    r_roe = cross_section_rank(neutralize_factor(f_roe, df_info, n_sigma=3.0))

    # 4. IC 序列 + 序列 corr
    print("\n[Step 3] IC 序列 corr")
    ic_inst = compute_ic_series(r_inst, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
    ic_roe = compute_ic_series(r_roe, fwd_ret, method="spearman", min_stocks=MIN_STOCKS_FOR_IC)
    ic_df = pd.concat([ic_inst.rename("inst_flow_20d"), ic_roe.rename("roe_stability")], axis=1).dropna()
    pearson_ic = ic_df.corr(method="pearson").iloc[0, 1]
    spearman_ic = ic_df.corr(method="spearman").iloc[0, 1]
    print(f"  IC 序列 Pearson  corr = {pearson_ic:+.4f}")
    print(f"  IC 序列 Spearman corr = {spearman_ic:+.4f}  (n={len(ic_df)})")

    # 5. 月频 L-S 收益 corr (gross)
    print("\n[Step 4] 月频 gross L-S 收益序列 corr")
    ls_inst = monthly_long_short_gross(r_inst, fwd_ret, direction="Qn_minus_Q1")
    ls_roe = monthly_long_short_gross(r_roe, fwd_ret, direction="Qn_minus_Q1")
    ls_df = pd.concat([ls_inst.rename("inst_flow_20d"), ls_roe.rename("roe_stability")], axis=1).dropna()
    pearson_ls = ls_df.corr(method="pearson").iloc[0, 1]
    print(f"  L-S 月度收益 Pearson corr = {pearson_ls:+.4f}  (n={len(ls_df)})")

    # 6. 等权 stacking (rank 平均) + cost-aware
    print("\n[Step 5] 等权 stacking + cost-aware")
    stacked = (r_inst + r_roe) / 2
    bt_inst = cost_aware_long_short(r_inst, fwd_ret, long_short="Qn_minus_Q1")
    bt_roe = cost_aware_long_short(r_roe, fwd_ret, long_short="Qn_minus_Q1")
    bt_stack = cost_aware_long_short(stacked, fwd_ret, long_short="Qn_minus_Q1")

    # 7. 汇总
    summary = {
        "ic_corr_pearson": round(pearson_ic, 4),
        "ic_corr_spearman": round(spearman_ic, 4),
        "ls_corr_pearson": round(pearson_ls, 4),
        "n_ic_obs": int(len(ic_df)),
        "n_ls_obs": int(len(ls_df)),
        "single_leg": {
            "inst_flow_20d": {k: round(v, 4) if isinstance(v, float) else v
                              for k, v in bt_inst.items()},
            "roe_stability": {k: round(v, 4) if isinstance(v, float) else v
                              for k, v in bt_roe.items()},
        },
        "stacked_equal_weight": {k: round(v, 4) if isinstance(v, float) else v
                                  for k, v in bt_stack.items()},
    }

    print("\n" + "=" * 72)
    print("结果汇总")
    print("=" * 72)
    print(f"  IC 序列 corr (Pearson / Spearman): {pearson_ic:+.4f} / {spearman_ic:+.4f}")
    print(f"  月度 L-S corr: {pearson_ls:+.4f}")
    print()
    print(f"  {'factor':<22} {'gross_ann':>10} {'net_ann':>10} {'sharpe_gross':>14} {'sharpe_net':>12} {'turnover':>10}")
    for label, res in [("inst_flow_20d (alone)", bt_inst),
                       ("roe_stability (alone)", bt_roe),
                       ("stacked (50/50)", bt_stack)]:
        print(f"  {label:<22} {res['gross_ann']:>10.4f} {res['net_ann']:>10.4f} "
              f"{res['sharpe_gross']:>14.4f} {res['sharpe_net']:>12.4f} {res['avg_turnover']:>10.4f}")

    # 8. 落盘
    OUT.mkdir(parents=True, exist_ok=True)
    out_path = OUT / "stacking_results.json"
    out_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False))
    print(f"\n✅ 写入 {out_path}")

    return summary


if __name__ == "__main__":
    run()
