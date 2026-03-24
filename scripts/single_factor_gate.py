"""
单因子验证门禁 — 4 因子独立评审

对每个候选因子独立评审：
  1. IC 均值、ICIR、IC>0%、t-stat
  2. 五分位回测（Q1-Q5 年化收益、多空夏普）
  3. 压力期表现（2015 股灾、2018 贸易战）
  4. 样本外 vs 样本内
  5. 判定：KEEP / WATCH / DROP
"""
import sys
import time
import warnings
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.factor_analysis import compute_ic_series, ic_summary, quintile_backtest
from utils.metrics import annualized_return, sharpe_ratio

# ══════════════════════════════════════════════════════════════
# 配置
# ══════════════════════════════════════════════════════════════
IS_START = "2015-01-01"
IS_END = "2023-12-31"
OOS_START = "2024-01-01"
OOS_END = "2025-12-31"

# 压力期
STRESS_PERIODS = {
    "2015股灾": ("2015-06-01", "2015-09-30"),
    "2018贸易战": ("2018-01-01", "2018-12-31"),
}

# 判定门槛
ICIR_THRESHOLD = 0.3
IC_POS_THRESHOLD = 0.55
OOS_SHARPE_THRESHOLD = 0.0

FACTOR_NAMES = ["reversal_1m", "low_vol_20d", "turnover_rev", "momentum_12_1"]

# 多空方向：因子已做过符号翻转（高值=好），统一用 Qn_minus_Q1
LONG_SHORT_DIR = {
    "reversal_1m": "Qn_minus_Q1",
    "low_vol_20d": "Qn_minus_Q1",
    "turnover_rev": "Qn_minus_Q1",
    "momentum_12_1": "Qn_minus_Q1",
}


def build_factors(price_wide: pd.DataFrame) -> dict:
    """
    构建 4 个候选因子（与 strategy_eval.py 一致）

    参数:
        price_wide: 价格宽表

    返回:
        dict: {因子名: 因子宽表}
    """
    daily_ret = price_wide.pct_change()
    return {
        "reversal_1m": -price_wide.pct_change(21),
        "low_vol_20d": -daily_ret.rolling(20).std(),
        "turnover_rev": -daily_ret.abs().rolling(20).mean(),
        "momentum_12_1": price_wide.pct_change(252).shift(21),
    }


def compute_ls_sharpe(ls_ret: pd.Series) -> float:
    """计算多空组合年化夏普（简单版）"""
    ls_clean = ls_ret.dropna()
    if len(ls_clean) < 60:
        return np.nan
    return sharpe_ratio(ls_clean)


def verdict(icir: float, pct_pos: float, oos_sharpe: float) -> str:
    """
    判定因子去留

    KEEP: ICIR > 0.3 且 IC>0% > 55% 且 OOS 夏普 > 0
    WATCH: 部分满足
    DROP: 全不满足
    """
    checks = [
        abs(icir) > ICIR_THRESHOLD,
        pct_pos > IC_POS_THRESHOLD,
        oos_sharpe > OOS_SHARPE_THRESHOLD if not np.isnan(oos_sharpe) else False,
    ]
    n_pass = sum(checks)
    if n_pass == 3:
        return "KEEP"
    elif n_pass >= 1:
        return "WATCH"
    else:
        return "DROP"


def main():
    print("=" * 70)
    print("  单因子验证门禁 — 4 因子独立评审")
    print("=" * 70)

    # ── 加载数据 ──
    print("\n[1/5] 加载数据...")
    t0 = time.time()
    symbols = get_all_symbols()
    if not symbols:
        print("  ❌ 本地数据不可用，跳过验证")
        skip_path = Path(__file__).parent.parent / ".claude" / "skipped.md"
        skip_path.parent.mkdir(parents=True, exist_ok=True)
        skip_path.write_text(
            "# Skipped: single_factor_gate.py\n\n"
            "原因: 本地数据目录为空或不存在，无法加载行情数据。\n"
        )
        print(f"  已记录到 {skip_path}")
        return

    # 从 2013 开始给 momentum_12_1 留足预热期
    price_full = load_price_wide(symbols, "2013-01-01", OOS_END, field="close")
    if price_full.empty:
        print("  ❌ 价格数据为空，跳过验证")
        skip_path = Path(__file__).parent.parent / ".claude" / "skipped.md"
        skip_path.parent.mkdir(parents=True, exist_ok=True)
        skip_path.write_text(
            "# Skipped: single_factor_gate.py\n\n"
            "原因: load_price_wide 返回空 DataFrame。\n"
        )
        print(f"  已记录到 {skip_path}")
        return

    # 去掉交易日数太少的股票
    valid_cols = price_full.columns[price_full.notna().sum() > 500]
    price_full = price_full[valid_cols]
    print(f"  股票: {price_full.shape[1]} 只 | 交易日: {price_full.shape[0]} | 耗时: {time.time()-t0:.1f}s")

    # ── 构建因子和收益率 ──
    print("\n[2/5] 构建因子...")
    factors = build_factors(price_full)
    fwd_ret_1d = price_full.pct_change().shift(-1)  # 下一日收益作为 IC 的 y

    # ── 数据质量门 ──
    assert price_full.shape[0] > 100, f"数据行数异常: {price_full.shape[0]}"
    assert price_full.isnull().mean().mean() < 0.5, "缺失值过多"
    print(f"  ✅ 数据质量 OK | 行数: {price_full.shape[0]} | "
          f"时间: {price_full.index[0].date()} ~ {price_full.index[-1].date()}")

    # ── 逐因子评审 ──
    summary_rows = []

    for fname in FACTOR_NAMES:
        fac = factors[fname]
        ls_dir = LONG_SHORT_DIR[fname]

        print(f"\n{'─' * 70}")
        print(f"  因子: {fname}")
        print(f"{'─' * 70}")

        # ── (1) IC 分析 ──
        print("\n  [IC 分析]")

        # 样本内 IC
        fac_is = fac.loc[IS_START:IS_END]
        ret_is = fwd_ret_1d.loc[IS_START:IS_END]
        ic_is = compute_ic_series(fac_is, ret_is)
        stats_is = ic_summary(ic_is, name=f"{fname} (样本内)")

        # 样本外 IC
        fac_oos = fac.loc[OOS_START:OOS_END]
        ret_oos = fwd_ret_1d.loc[OOS_START:OOS_END]
        ic_oos = compute_ic_series(fac_oos, ret_oos)
        stats_oos = ic_summary(ic_oos, name=f"{fname} (样本外)")

        # ── (2) 五分位回测 ──
        print("  [五分位回测]")

        # 样本内
        group_ret_is, ls_ret_is = quintile_backtest(fac_is, ret_is, long_short=ls_dir)
        print(f"    样本内 Q1-Q5 年化收益:")
        for q in group_ret_is.columns:
            q_ann = group_ret_is[q].dropna().mean() * 252
            print(f"      {q}: {q_ann:>+.2%}")
        ls_sharpe_is = compute_ls_sharpe(ls_ret_is)
        print(f"    多空夏普(IS): {ls_sharpe_is:.4f}")

        # 样本外
        group_ret_oos, ls_ret_oos = quintile_backtest(fac_oos, ret_oos, long_short=ls_dir)
        ls_sharpe_oos = compute_ls_sharpe(ls_ret_oos)
        if not np.isnan(ls_sharpe_oos):
            print(f"\n    样本外 Q1-Q5 年化收益:")
            for q in group_ret_oos.columns:
                q_ann = group_ret_oos[q].dropna().mean() * 252
                print(f"      {q}: {q_ann:>+.2%}")
            print(f"    多空夏普(OOS): {ls_sharpe_oos:.4f}")
        else:
            print(f"    样本外数据不足，跳过")

        # ── (3) 压力期表现 ──
        print("\n  [压力期表现]")
        for period_name, (p_start, p_end) in STRESS_PERIODS.items():
            ls_stress = ls_ret_is.loc[p_start:p_end].dropna()
            if len(ls_stress) > 10:
                stress_ann = ls_stress.mean() * 252
                stress_vol = ls_stress.std() * np.sqrt(252)
                stress_sr = stress_ann / stress_vol if stress_vol > 0 else np.nan
                print(f"    {period_name}: 年化={stress_ann:>+.2%}, 夏普={stress_sr:>.3f}")
            else:
                print(f"    {period_name}: 数据不足")

        # ── (4) IS vs OOS 对比 ──
        print("\n  [IS vs OOS 对比]")
        print(f"    IC均值  IS={stats_is['IC_mean']:>+.4f}  OOS={stats_oos['IC_mean']:>+.4f}")
        print(f"    ICIR    IS={stats_is['ICIR']:>+.4f}  OOS={stats_oos['ICIR']:>+.4f}")
        print(f"    IC>0%   IS={stats_is['pct_pos']:>.2%}  OOS={stats_oos['pct_pos']:>.2%}")
        print(f"    LS夏普  IS={ls_sharpe_is:>+.4f}  OOS={ls_sharpe_oos:>+.4f}")

        # ── (5) 判定 ──
        v = verdict(stats_is["ICIR"], stats_is["pct_pos"], ls_sharpe_oos)
        print(f"\n  >>> 判定: {v}")

        summary_rows.append({
            "因子": fname,
            "IC均值(IS)": f"{stats_is['IC_mean']:+.4f}",
            "ICIR(IS)": f"{stats_is['ICIR']:+.4f}",
            "IC>0%(IS)": f"{stats_is['pct_pos']:.1%}",
            "t-stat(IS)": f"{stats_is['t_stat']:+.3f}",
            "LS夏普(IS)": f"{ls_sharpe_is:+.4f}",
            "LS夏普(OOS)": f"{ls_sharpe_oos:+.4f}" if not np.isnan(ls_sharpe_oos) else "N/A",
            "判定": v,
        })

    # ── 汇总表 ──
    print(f"\n\n{'=' * 70}")
    print("  汇总表")
    print(f"{'=' * 70}\n")
    summary_df = pd.DataFrame(summary_rows)
    print(summary_df.to_string(index=False))
    print()

    # 统计
    keep_count = sum(1 for r in summary_rows if r["判定"] == "KEEP")
    watch_count = sum(1 for r in summary_rows if r["判定"] == "WATCH")
    drop_count = sum(1 for r in summary_rows if r["判定"] == "DROP")
    print(f"  KEEP: {keep_count} | WATCH: {watch_count} | DROP: {drop_count}")
    print(f"{'=' * 70}")


if __name__ == "__main__":
    main()
