"""
反转因子完整评估报告

评估三个反转因子在 A 股的 IC / ICIR / 分层收益表现：
  - reversal_5d      : 5日超短期反转
  - reversal_1m      : 1个月反转（已有，作对比基准）
  - reversal_skip1m  : 跳过近1个月的中期反转（60d - 5d）

同时与 V9 中的 enhanced_mom_60 对比，看两者是否互补。

运行：python scripts/reversal_factor_eval.py
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd
from scipy import stats

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.alpha_factors import (
    reversal_5d,
    reversal_1m,
    reversal_skip1m,
    enhanced_momentum,
)
from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest
from utils.metrics import annualized_return, annualized_volatility, sharpe_ratio, max_drawdown

# ── 参数 ─────────────────────────────────────────────────────────
START        = "2015-01-01"
END          = "2025-12-31"
WARMUP_START = "2014-01-01"
FWD_DAYS     = 1    # IC 计算用次日收益
MIN_STOCKS   = 50

DIVIDER = "=" * 65


# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════

def load_data():
    print(DIVIDER)
    print("  反转因子评估报告")
    print(DIVIDER)
    print("\n[1/4] 加载数据...")
    t0 = time.time()

    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]

    # 数据质量门
    assert price.shape[0] > 100, f"数据行数异常: {price.shape[0]}"
    # 已在前面用 notna().sum() > 500 过滤了稀疏股，跳过全局缺失率检查
    assert price.index.is_monotonic_increasing, "日期未排序"

    price_eval = price.loc[START:END]
    print(f"  股票数: {len(valid)} | 交易日: {len(price_eval)} | 耗时: {time.time()-t0:.1f}s")
    print(f"  时间范围: {price_eval.index[0].date()} ~ {price_eval.index[-1].date()}")
    return price, price_eval


# ══════════════════════════════════════════════════════════════════
# 构建因子
# ══════════════════════════════════════════════════════════════════

def build_factors(price):
    print("\n[2/4] 构建因子...")
    factors = {
        "reversal_5d":     reversal_5d(price),
        "reversal_1m":     reversal_1m(price),
        "reversal_skip1m": reversal_skip1m(price),
        "enhanced_mom_60": enhanced_momentum(price, window=60),  # 对比参照
    }
    print(f"  因子: {list(factors.keys())}")
    return {k: v.loc[START:END] for k, v in factors.items()}


# ══════════════════════════════════════════════════════════════════
# IC 分析
# ══════════════════════════════════════════════════════════════════

def run_ic_analysis(factors, price_eval):
    print("\n[3/4] IC / ICIR 分析...")

    # 次日收益率（shift(-1)：今日因子预测明日收益）
    ret_1d = price_eval.pct_change().shift(-1)

    results = {}
    for name, fac in factors.items():
        ic_series = compute_ic_series(fac, ret_1d, method="spearman",
                                      min_stocks=MIN_STOCKS)
        summary = ic_summary(ic_series, name=name, fwd_days=FWD_DAYS, verbose=False)
        results[name] = {"ic_series": ic_series, "summary": summary}

    # 打印汇总表
    print(f"\n  {'因子':<22} {'IC均值':>8} {'ICIR':>7} {'IC>0%':>7} {'HAC-t':>8} {'有效天':>7}")
    print("  " + "-" * 62)
    for name, r in results.items():
        s = r["summary"]
        marker = " ★" if abs(s["ICIR"]) > 0.3 and abs(s["t_stat_hac"]) > 2 else ""
        print(f"  {name:<22} {s['IC_mean']:>8.4f} {s['ICIR']:>7.4f} "
              f"{s['pct_pos']:>6.1%} {s['t_stat_hac']:>8.3f} {s['n']:>7}{marker}")

    print("\n  ★ = |ICIR|>0.3 且 HAC-t 显著（|t|>2）")
    return results


# ══════════════════════════════════════════════════════════════════
# 分层回测
# ══════════════════════════════════════════════════════════════════

def run_quintile_backtest(factors, price_eval):
    print("\n[4/4] 分层回测（五分位）...")
    ret_1d = price_eval.pct_change().shift(-1)

    # 先算 IC 符号决定多空方向（IC>0 → Qn做多；IC<0 → Q1做多）
    ret_1d_ic = price_eval.pct_change().shift(-1)

    all_ls = {}
    for name, fac in factors.items():
        ic_check = compute_ic_series(fac, ret_1d_ic, method="spearman",
                                     min_stocks=MIN_STOCKS)
        ic_sign = ic_check.mean()
        ls_dir = "Qn_minus_Q1" if ic_sign > 0 else "Q1_minus_Qn"

        group_ret, ls_ret = quintile_backtest(fac, ret_1d, n_groups=5,
                                              long_short=ls_dir)
        all_ls[name] = ls_ret

        ann_ret = annualized_return(ls_ret)
        ann_vol = annualized_volatility(ls_ret)
        sr      = sharpe_ratio(ls_ret)
        mdd     = max_drawdown(ls_ret)   # 传日收益序列，函数内部自己算累计

        q1_cum = (1 + group_ret["Q1"].fillna(0)).cumprod().iloc[-1] - 1
        q5_cum = (1 + group_ret["Q5"].fillna(0)).cumprod().iloc[-1] - 1
        monotone = q5_cum > q1_cum if ic_sign > 0 else q1_cum > q5_cum

        print(f"\n  [{name}]  IC方向: {'正向(Qn多)' if ic_sign > 0 else '负向(Q1多)'}")
        print(f"    多空年化: {ann_ret:.2%}  波动: {ann_vol:.2%}  夏普: {sr:.3f}  最大回撤: {mdd:.2%}")
        print(f"    Q1 累计: {q1_cum:.2%}  Q5 累计: {q5_cum:.2%}  单调性: {'✓' if monotone else '✗'}")

    return all_ls


# ══════════════════════════════════════════════════════════════════
# 与动量因子的相关性（判断是否互补）
# ══════════════════════════════════════════════════════════════════

def correlation_check(ic_results):
    print(f"\n{DIVIDER}")
    print("  IC 序列相关性（判断因子是否互补）")
    print(DIVIDER)

    reversal_factors = ["reversal_5d", "reversal_1m", "reversal_skip1m"]
    mom_key = "enhanced_mom_60"

    ic_df = pd.DataFrame({k: v["ic_series"] for k, v in ic_results.items()}).dropna()

    print(f"\n  {'':22}", end="")
    keys = reversal_factors + [mom_key]
    for k in keys:
        print(f"  {k[:12]:>12}", end="")
    print()
    print("  " + "-" * (22 + 14 * len(keys)))

    for k1 in keys:
        print(f"  {k1:<22}", end="")
        for k2 in keys:
            if k1 == k2:
                print(f"  {'1.000':>12}", end="")
            else:
                c = ic_df[k1].corr(ic_df[k2])
                print(f"  {c:>12.3f}", end="")
        print()

    mom_corrs = {k: ic_df[k].corr(ic_df[mom_key]) for k in reversal_factors}
    best = min(mom_corrs, key=lambda x: abs(mom_corrs[x]))
    print(f"\n  结论：与 enhanced_mom_60 相关性最低的反转因子是 [{best}]，"
          f"相关性 = {mom_corrs[best]:.3f}")
    print(f"  → 最适合与 V9 动量因子搭配使用")


# ══════════════════════════════════════════════════════════════════
# 急跌行情表现（2022 熊市 / 2024 大幅波动）
# ══════════════════════════════════════════════════════════════════

def stress_test(factors, price_eval, all_ls):
    print(f"\n{DIVIDER}")
    print("  急跌行情压力测试")
    print(DIVIDER)

    periods = {
        "2022 熊市": ("2022-01-01", "2022-10-31"),
        "2024 急跌": ("2024-01-01", "2024-02-05"),
        "2025 全段": ("2025-01-01", "2025-12-31"),
    }

    for label, (s, e) in periods.items():
        print(f"\n  [{label}] {s} ~ {e}")
        print(f"  {'因子':<22} {'多空累计':>10} {'夏普':>8}")
        print("  " + "-" * 42)
        for name, ls_ret in all_ls.items():
            seg = ls_ret.loc[s:e].fillna(0)
            if len(seg) < 5:
                continue
            cum = (1 + seg).prod() - 1
            sr = sharpe_ratio(seg) if seg.std() > 0 else 0
            print(f"  {name:<22} {cum:>10.2%} {sr:>8.3f}")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    price, price_eval = load_data()
    factors = build_factors(price)
    ic_results = run_ic_analysis(factors, price_eval)
    all_ls = run_quintile_backtest(factors, price_eval)
    correlation_check(ic_results)
    stress_test(factors, price_eval, all_ls)

    print(f"\n{DIVIDER}")
    print("  评估完成")
    print(DIVIDER)


if __name__ == "__main__":
    main()
