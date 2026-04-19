"""
v10 候选研究：V9 + reversal_skip1m 中期反转因子

核心改动（相对 v9）：
  - 在 v9 的 5 因子基础上，新增 reversal_skip1m（跳过近1个月的中期反转）
  - 权重仍由 ICIR 自动学习，新因子权重由数据决定
  - 目标：降低急跌行情中的回撤，同时不显著损失动量收益

对比基准：
  v7_fixed    : 手工固定权重，5 因子
  v9_static   : ICIR 权重，5 因子
  v10_static  : ICIR 权重，6 因子（新增 reversal_skip1m）

运行：python scripts/v10_reversal_eval.py
"""
import sys
import time
import warnings
from datetime import date
from pathlib import Path

warnings.filterwarnings("ignore")
sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.data_loader import get_index_history
from utils.metrics import (
    annualized_return, annualized_volatility, sharpe_ratio,
    max_drawdown, win_rate, calmar_ratio,
)
from utils.factor_analysis import neutralize_factor_by_industry
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.multi_factor import icir_weight
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
    reversal_skip1m as _reversal_skip1m,
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量（与 v9 保持一致）────────────────────────────────────────
WARMUP_START = "2013-01-01"
IS_START     = "2015-01-01"
IS_END       = "2024-12-31"
OOS_START    = "2025-01-01"
OOS_END      = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20
MIN_WEIGHT   = 0.05

# v7 固定权重（5因子）
V7_WEIGHTS = {
    "team_coin":       0.30,
    "low_vol_20d":     0.25,
    "cgo_simple":      0.20,
    "enhanced_mom_60": 0.15,
    "bp":              0.10,
}

DIVIDER = "=" * 65


# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════

def load_data():
    print(DIVIDER)
    print("  v10 因子评估报告（V9 + reversal_skip1m）")
    print(DIVIDER)
    print("\n[1/5] 加载数据...")
    t0 = time.time()
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, OOS_END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]

    pb_raw = load_price_wide(list(valid), WARMUP_START, OOS_END, field="pb")
    pb = pb_raw.reindex(index=price.index, columns=valid)

    hs300_full = None
    try:
        hs300_full = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
        common = price.index.intersection(hs300_full.index)
        price = price.loc[common]
        pb = pb.reindex(index=price.index)
        hs300_full = hs300_full.loc[common]
    except Exception as e:
        print(f"  HS300 不可用: {e}")

    tradable = apply_tradability_filter(price)
    print(f"  股票: {len(valid)} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")
    return price, pb, hs300_full, tradable


# ══════════════════════════════════════════════════════════════════
# 因子构建
# ══════════════════════════════════════════════════════════════════

def build_factors_v9(price, pb, industry_df):
    """v9 的 5 因子"""
    factors = {
        "team_coin":       _team_coin(price),
        "low_vol_20d":     _low_vol_20d(price),
        "cgo_simple":      -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp":              bp_factor(pb).reindex_like(price),
    }
    return {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }


def build_factors_v10(price, pb, industry_df):
    """v10 = v9 + reversal_skip1m"""
    factors = {
        "team_coin":        _team_coin(price),
        "low_vol_20d":      _low_vol_20d(price),
        "cgo_simple":       -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60":  enhanced_momentum(price, window=60),
        "bp":               bp_factor(pb).reindex_like(price),
        "reversal_skip1m":  _reversal_skip1m(price),
    }
    return {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }


def build_all_factors(price, pb):
    print("\n[2/5] 构建因子 + 行业中性化...")
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)
    neutral_v9  = build_factors_v9(price, pb, industry_df)
    neutral_v10 = build_factors_v10(price, pb, industry_df)
    print(f"  v9  因子: {list(neutral_v9.keys())}")
    print(f"  v10 因子: {list(neutral_v10.keys())}")
    return neutral_v9, neutral_v10, industry_df


# ══════════════════════════════════════════════════════════════════
# ICIR 权重
# ══════════════════════════════════════════════════════════════════

def apply_signs(factors, signs):
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


def compute_icir_weights(label, neutral, price):
    result = icir_weight(
        factors=neutral,
        price_wide=price,
        train_start=IS_START,
        train_end=IS_END,
        fwd_days=FWD_DAYS,
        min_weight=MIN_WEIGHT,
    )
    w, signs, stats = result["weights"], result["signs"], result["ic_stats"]
    print(f"\n  [{label}] {'因子':<20} {'IC均值':>8} {'ICIR':>7} {'方向':>5} {'权重':>8}")
    print("  " + "-" * 58)
    for name in neutral:
        s = stats.get(name, {})
        print(f"  {'':2}{name:<20} {s.get('ic_mean', np.nan):>8.4f} "
              f"{s.get('icir', 0):>7.3f} {signs.get(name, 1):>5d} {w.get(name, 0):>8.2%}")
    return w, signs


def compute_all_weights(price, neutral_v9, neutral_v10):
    print("\n[3/5] 计算 ICIR 权重...")
    w9, s9   = compute_icir_weights("v9_static",  neutral_v9,  price)
    w10, s10 = compute_icir_weights("v10_static", neutral_v10, price)
    return w9, s9, w10, s10


# ══════════════════════════════════════════════════════════════════
# IS/OOS 回测对比
# ══════════════════════════════════════════════════════════════════

def calc_metrics(ret, bench_ret=None):
    if ret is None or len(ret) == 0:
        return {}
    m = {
        "ann":    annualized_return(ret),
        "vol":    annualized_volatility(ret),
        "sr":     sharpe_ratio(ret),
        "mdd":    max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr":     win_rate(ret),
    }
    if bench_ret is not None:
        common = ret.index.intersection(bench_ret.index)
        if len(common) > 20:
            m["excess"] = annualized_return(ret.loc[common] - bench_ret.loc[common])
    return m


def run_is_oos(price, neutral_v9, neutral_v10, tradable,
               w9, s9, w10, s10, hs300_full):
    print("\n[4/5] IS/OOS 回测对比...")
    hs300_ret = hs300_full["close"].pct_change().dropna() if hs300_full is not None else None

    ret_v7  = run_backtest(price, neutral_v9, V7_WEIGHTS,
                           n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)
    ret_v9  = run_backtest(price, apply_signs(neutral_v9, s9), w9,
                           n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)
    ret_v10 = run_backtest(price, apply_signs(neutral_v10, s10), w10,
                           n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True)

    header = f"  {'策略':<14} {'年化':>8} {'波动':>8} {'夏普':>7} {'最大回撤':>10} {'超额':>8}"
    sep    = "  " + "-" * 60

    for period_label, s, e in [("IS (2015-2024)", IS_START, IS_END),
                                 ("OOS (2025)",    OOS_START, OOS_END)]:
        print(f"\n  ── {period_label} ──")
        print(header)
        print(sep)
        for name, ret in [("v7_fixed", ret_v7), ("v9_static", ret_v9), ("v10_static", ret_v10)]:
            seg = ret.loc[s:e]
            if len(seg) < 5:
                continue
            m = calc_metrics(seg, hs300_ret)
            print(f"  {name:<14} {m.get('ann',0):>8.2%} {m.get('vol',0):>8.2%} "
                  f"{m.get('sr',0):>7.4f} {m.get('mdd',0):>10.2%} "
                  f"{m.get('excess', float('nan')):>8.2%}")

    # 急跌段专项对比
    print(f"\n  ── 急跌行情专项 ──")
    stress = [
        ("2022 熊市",  "2022-01-01", "2022-10-31"),
        ("2024 急跌",  "2024-01-01", "2024-02-05"),
        ("2025 全段",  "2025-01-01", "2025-12-31"),
    ]
    print(f"  {'段':12} {'策略':<14} {'累计':>8} {'夏普':>7} {'最大回撤':>10}")
    print("  " + "-" * 55)
    for seg_label, s, e in stress:
        for name, ret in [("v9_static", ret_v9), ("v10_static", ret_v10)]:
            seg = ret.loc[s:e].fillna(0)
            if len(seg) < 3:
                continue
            cum = (1 + seg).prod() - 1
            sr  = sharpe_ratio(seg) if seg.std() > 0 else 0
            mdd = max_drawdown(seg)
            print(f"  {seg_label:<12} {name:<14} {cum:>8.2%} {sr:>7.3f} {mdd:>10.2%}")
        print()

    return ret_v7, ret_v9, ret_v10


# ══════════════════════════════════════════════════════════════════
# Walk-Forward
# ══════════════════════════════════════════════════════════════════

def run_wf(price, pb, tradable, industry_df, version="v10"):
    print(f"\n[5/5] Walk-Forward（{version}）...")

    def wf_fn(price_slice, _fdata, train_start, train_end, test_start, test_end):
        pb_slice = pb.reindex(index=price_slice.index, columns=price_slice.columns)
        local_factors = {
            "team_coin":       _team_coin(price_slice),
            "low_vol_20d":     _low_vol_20d(price_slice),
            "cgo_simple":      -(price_slice / price_slice.rolling(60).mean() - 1),
            "enhanced_mom_60": enhanced_momentum(price_slice, window=60),
            "reversal_skip1m": _reversal_skip1m(price_slice),
        }
        try:
            local_factors["bp"] = bp_factor(pb_slice).reindex_like(price_slice)
        except Exception:
            pass

        neutral = {
            name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
            for name, fac in local_factors.items()
        }
        w_res   = icir_weight(factors=neutral, price_wide=price_slice,
                              train_start=train_start, train_end=train_end,
                              fwd_days=FWD_DAYS, min_weight=MIN_WEIGHT)
        weights = w_res["weights"]
        signs   = w_res["signs"]
        neutral_signed = {n: f * signs.get(n, 1) for n, f in neutral.items()}
        wf_ret = run_backtest(price_slice, neutral_signed, weights,
                              n_stocks=N_STOCKS, cost=COST, mask=None, lag1=True)
        return wf_ret.loc[test_start:test_end] if len(wf_ret) > 0 else pd.Series(dtype=float)

    try:
        wf_df = walk_forward_test(
            wf_fn, price.loc[WARMUP_START:IS_END], {},
            train_years=3, test_months=6,
        )
        valid = wf_df[wf_df["sharpe"].notna()]
        print(f"  窗口: {len(wf_df)} | 有效: {len(valid)}")
        print(f"  夏普均值:   {valid['sharpe'].mean():.4f}")
        print(f"  夏普中位数: {valid['sharpe'].median():.4f}  ← 目标 >0.20")
        print(f"  收益均值:   {valid['total_return'].mean():+.2%} | 胜率: {(valid['total_return']>0).mean():.0%}")
        print(f"  回撤均值:   {valid['max_drawdown'].mean():.2%}")
        return wf_df
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════
# 报告写入
# ══════════════════════════════════════════════════════════════════

def write_report(ret_v9, ret_v10, w10, s10, wf_df):
    out = Path(__file__).parent.parent / "journal" / f"v10_reversal_eval_{date.today().strftime('%Y%m%d')}.md"

    def fmt(ret, s, e, hs300_ret=None):
        seg = ret.loc[s:e]
        m = calc_metrics(seg)
        return (f"年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
                f"  回撤={m.get('mdd',0):.2%}  胜率={m.get('wr',0):.1%}")

    lines = [
        f"# v10 反转因子评估报告 — {date.today()}",
        "",
        "## 核心改动",
        "",
        "在 v9（5因子 ICIR 加权）基础上，新增 `reversal_skip1m`（跳过近1个月的60日中期反转）。",
        "目标：通过引入与动量因子负相关的反转因子，降低急跌行情回撤。",
        "",
        "## v10 因子权重（整段 IS 学到）",
        "",
        "| 因子 | 方向 | 权重 |",
        "|------|------|------|",
    ]
    for name, w in w10.items():
        lines.append(f"| {name} | {'+1' if s10.get(name,1)>0 else '-1'} | {w:.2%} |")

    lines += [
        "",
        "## IS 表现（2015-2024）",
        "",
        f"- v9_static : {fmt(ret_v9,  IS_START, IS_END)}",
        f"- v10_static: {fmt(ret_v10, IS_START, IS_END)}",
        "",
        "## OOS 表现（2025）",
        "",
        f"- v9_static : {fmt(ret_v9,  OOS_START, OOS_END)}",
        f"- v10_static: {fmt(ret_v10, OOS_START, OOS_END)}",
        "",
        "## 急跌行情对比",
        "",
        "| 段 | v9 累计 | v10 累计 |",
        "|---|---|---|",
    ]
    for seg_label, s, e in [("2022熊市", "2022-01-01","2022-10-31"),
                              ("2024急跌", "2024-01-01","2024-02-05"),
                              ("2025全段", "2025-01-01","2025-12-31")]:
        c9  = (1 + ret_v9.loc[s:e].fillna(0)).prod() - 1
        c10 = (1 + ret_v10.loc[s:e].fillna(0)).prod() - 1
        lines.append(f"| {seg_label} | {c9:+.2%} | {c10:+.2%} |")

    if wf_df is not None:
        valid = wf_df[wf_df["sharpe"].notna()]
        lines += [
            "",
            "## Walk-Forward 结果",
            "",
            f"- 窗口数: {len(wf_df)}（有效: {len(valid)}）",
            f"- 夏普均值: {valid['sharpe'].mean():.4f}",
            f"- 夏普中位数: {valid['sharpe'].median():.4f}",
            f"- 胜率: {(valid['total_return']>0).mean():.0%}",
        ]

    lines += ["", "## 结论", "", "（待填写）"]
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  报告已写入: {out.name}")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    price, pb, hs300_full, tradable = load_data()
    neutral_v9, neutral_v10, industry_df = build_all_factors(price, pb)
    w9, s9, w10, s10 = compute_all_weights(price, neutral_v9, neutral_v10)
    ret_v7, ret_v9, ret_v10 = run_is_oos(
        price, neutral_v9, neutral_v10, tradable,
        w9, s9, w10, s10, hs300_full)
    wf_df = run_wf(price, pb, tradable, industry_df)
    write_report(ret_v9, ret_v10, w10, s10, wf_df)
    print(f"\n{DIVIDER}")
    print("  评估完成")
    print(DIVIDER)


if __name__ == "__main__":
    main()
