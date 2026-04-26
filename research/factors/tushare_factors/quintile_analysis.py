"""
五分位回测分析 — 补充 IC 分析，验证因子单调性

对每个因子做：
- 按截面分五组（Q1=最低，Q5=最高）
- 计算各组平均月度收益率
- 计算 Q5-Q1 多空组合年化收益、夏普

运行方式:
    python research/factors/tushare_factors/quintile_analysis.py
"""
import sys
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).parent.parent.parent.parent
sys.path.insert(0, str(ROOT))
DATA = ROOT / "data" / "raw" / "tushare"

warnings.filterwarnings("ignore")


def load_cached_price_panel() -> pd.DataFrame:
    cache = DATA / "price_panel.parquet"
    if not cache.exists():
        raise FileNotFoundError("先运行 factor_research.py 生成价格缓存")
    return pd.read_parquet(cache)


def quintile_returns(
    factor_wide: pd.DataFrame,
    fwd_ret_wide: pd.DataFrame,
    n_bins: int = 5,
    min_stocks: int = 5,
) -> pd.DataFrame:
    """
    截面五分位回测

    参数:
        factor_wide  : 因子宽表 (date × symbol)
        fwd_ret_wide : 前向收益率宽表 (date × symbol)
        n_bins       : 分组数

    返回:
        DataFrame，index=date，columns=Q1..Q5 的平均收益
    """
    common_dates = factor_wide.index.intersection(fwd_ret_wide.index)
    common_stocks = factor_wide.columns.intersection(fwd_ret_wide.columns)
    fac = factor_wide.loc[common_dates, common_stocks]
    ret = fwd_ret_wide.loc[common_dates, common_stocks]

    bin_returns = {f"Q{i+1}": [] for i in range(n_bins)}
    dates = []

    for date in common_dates:
        f_row = fac.loc[date].dropna()
        r_row = ret.loc[date].dropna()
        idx = f_row.index.intersection(r_row.index)

        if len(idx) < min_stocks:
            continue

        f_cross = f_row[idx]
        r_cross = r_row[idx]

        # 分五组（等频）
        labels = pd.qcut(f_cross, n_bins, labels=False, duplicates="drop")
        if labels.nunique() < n_bins:
            continue

        dates.append(date)
        for i in range(n_bins):
            mask = labels == i
            bin_returns[f"Q{i+1}"].append(r_cross[mask].mean())

    result = pd.DataFrame(bin_returns, index=dates)
    return result


def factor_summary(name: str, q_rets: pd.DataFrame) -> dict:
    """打印五分位统计"""
    # 月度收益 → 年化
    mean_rets = q_rets.mean()
    annual = mean_rets * 252 / 21  # 21交易日/月，252交易日/年

    # Q5-Q1 多空组合
    ls = q_rets["Q5"] - q_rets["Q1"]
    ls_annual = ls.mean() * 252 / 21
    ls_sharpe = (ls.mean() / ls.std()) * np.sqrt(252 / 21)

    print(f"\n{'─'*55}")
    print(f"  {name}")
    print(f"{'─'*55}")
    print(f"  分组年化收益:")
    for q in ["Q1", "Q2", "Q3", "Q4", "Q5"]:
        bar = "█" * int(abs(annual[q] * 100))
        sign = "+" if annual[q] > 0 else ""
        print(f"    {q}: {sign}{annual[q]:.1%}  {bar}")
    print(f"  Q5-Q1 年化: {ls_annual:+.1%} | Sharpe: {ls_sharpe:.2f} | N月: {len(ls)}")

    return {
        "factor": name,
        "q1_annual": round(annual["Q1"], 4),
        "q5_annual": round(annual["Q5"], 4),
        "ls_annual": round(ls_annual, 4),
        "ls_sharpe": round(ls_sharpe, 3),
        "monotone": bool(
            (annual["Q1"] < annual["Q2"]) and
            (annual["Q4"] < annual["Q5"])
        ),
    }


def run():
    from research.factors.tushare_factors.factor_research import (
        build_inst_flow, build_nb_ratio_chg,
        build_roe_stability, build_cfoni_precise,
    )

    print("=" * 55)
    print("五分位收益分析")
    print("=" * 55)

    price_wide = load_cached_price_panel()
    price_idx = price_wide.index

    # 前向收益率（21日）
    fwd_ret = np.log(price_wide).diff(21).shift(-21)

    # 股票池
    mf_stocks = sorted(f.stem for f in (DATA / "moneyflow").glob("*.parquet"))
    db_stocks = sorted(f.stem for f in (DATA / "daily_basic").glob("*.parquet"))
    fi_stocks = sorted(f.stem.replace("fina_", "") for f in (DATA / "financial").glob("fina_*.parquet"))
    cf_stocks = sorted(f.stem.replace("cashflow_", "") for f in (DATA / "financial").glob("cashflow_*.parquet"))
    ic_stocks = sorted(f.stem.replace("income_", "") for f in (DATA / "financial").glob("income_*.parquet"))
    nb_stocks = set(f.stem for f in (DATA / "northbound").glob("*.parquet"))
    core_stocks = sorted(set(mf_stocks) & set(db_stocks))

    # 构建因子
    factors = {
        "inst_flow_20d": build_inst_flow(core_stocks),
        "nb_ratio_chg": build_nb_ratio_chg(sorted(nb_stocks & set(mf_stocks)), price_idx),
        "roe_stability": build_roe_stability(sorted(set(mf_stocks) & set(db_stocks) & set(fi_stocks)), price_idx),
        "cfoni_precise": build_cfoni_precise(sorted(set(cf_stocks) & set(ic_stocks)), price_idx),
    }

    all_summaries = []
    for name, fac in factors.items():
        q_rets = quintile_returns(fac, fwd_ret)
        summary = factor_summary(name, q_rets)
        all_summaries.append(summary)

    # 汇总
    print("\n" + "=" * 55)
    print(f"{'Factor':<20} {'Q1 ann':>8} {'Q5 ann':>8} {'LS ann':>8} {'LS Sharpe':>10} {'Mono':>6}")
    print("-" * 55)
    for s in all_summaries:
        mono_sym = "✓" if s["monotone"] else "✗"
        print(f"{s['factor']:<20} {s['q1_annual']:>+8.1%} {s['q5_annual']:>+8.1%} "
              f"{s['ls_annual']:>+8.1%} {s['ls_sharpe']:>10.2f} {mono_sym:>6}")

    # 保存
    out = ROOT / "research" / "factors" / "tushare_factors" / "quintile_results.csv"
    pd.DataFrame(all_summaries).to_csv(out, index=False)
    print(f"\n✅ 结果保存到 {out}")


if __name__ == "__main__":
    run()
