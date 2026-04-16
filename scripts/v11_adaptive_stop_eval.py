"""
v11 候选研究：ICIR 学习权重 + 波动率自适应止损

v10 证明固定 -8% 止损在 OOS 失效（2025 震荡行情反复触发）。
v11 改用自适应阈值：threshold_t = baseline × clip(σ_t / σ_ref, 0.5, 2.0)
  - σ_t: 组合 60 日滚动年化波动率
  - σ_ref: 训练期 σ_t 中位数（WF 每窗口独立计算，避免未来泄漏）
  - baseline = -8%（和 v10 对齐便于对照）

设计目标：保留 v9 的 OOS 优势，同时控制 IS 回撤。

运行：python scripts/v11_adaptive_stop_eval.py
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
from utils.stop_loss import half_position_stop, adaptive_half_position_stop
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START       = "2013-01-01"
IS_START           = "2015-01-01"
IS_END             = "2024-12-31"
OOS_START          = "2025-01-01"
OOS_END            = "2025-12-31"
N_STOCKS           = 30
COST               = 0.003
FWD_DAYS           = 20
MIN_WEIGHT         = 0.05
BASELINE_THRESHOLD = -0.08    # 锚点阈值（σ_t == σ_ref 时触发）
VOL_WINDOW         = 60       # 滚动波动率窗口
MIN_SCALE          = 0.5      # σ_t/σ_ref 下夹
MAX_SCALE          = 2.0      # σ_t/σ_ref 上夹

V7_WEIGHTS = {
    "team_coin":       0.30,
    "low_vol_20d":     0.25,
    "cgo_simple":      0.20,
    "enhanced_mom_60": 0.15,
    "bp":              0.10,
}


# ══════════════════════════════════════════════════════════════════
# 数据加载 / 因子构建（同 v10）
# ══════════════════════════════════════════════════════════════════

def load_data():
    print("=" * 60)
    print("[1/5] 加载数据...")
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


def build_factors(price, pb):
    print("\n[2/5] 构建 5 因子 + 行业中性化...")
    factors = {
        "team_coin":       _team_coin(price),
        "low_vol_20d":     _low_vol_20d(price),
        "cgo_simple":      -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp":              bp_factor(pb).reindex_like(price),
    }
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)
    neutral = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }
    print(f"  行业覆盖: {len(industry_df)} 只")
    return neutral


def apply_signs(factors: dict, signs: dict) -> dict:
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


# ══════════════════════════════════════════════════════════════════
# ICIR 学习 + ref_vol 计算
# ══════════════════════════════════════════════════════════════════

def compute_is_icir_weights(price, neutral):
    print("\n[3/5] 计算 ICIR 权重（整段 IS）...")
    res = icir_weight(
        factors=neutral, price_wide=price,
        train_start=IS_START, train_end=IS_END,
        fwd_days=FWD_DAYS, min_weight=MIN_WEIGHT,
    )
    w, signs, stats = res["weights"], res["signs"], res["ic_stats"]
    print(f"\n  {'因子':<20} {'ICIR':>8} {'方向':>6} {'权重':>8}")
    print("  " + "-" * 50)
    for name in neutral:
        s = stats.get(name, {})
        print(f"  {name:<20} {s.get('icir', 0):>8.3f} "
              f"{signs.get(name, 1):>6d} {w.get(name, 0):>8.2%}")
    return w, signs, stats


def compute_ref_vol(ret: pd.Series, train_start, train_end) -> float:
    """训练期内 σ_t 中位数（60日滚动年化波动率）。"""
    train_ret = ret.loc[train_start:train_end]
    sigma_t = train_ret.rolling(VOL_WINDOW, min_periods=20).std() * np.sqrt(252)
    sigma_t = sigma_t.dropna()
    if len(sigma_t) < 5:
        return 0.20  # 兜底
    return float(sigma_t.median())


# ══════════════════════════════════════════════════════════════════
# 指标 / 回测
# ══════════════════════════════════════════════════════════════════

def calc_metrics(ret, bench=None):
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
    if bench is not None:
        common = ret.index.intersection(bench.index)
        if len(common) > 20:
            m["excess"] = annualized_return(ret.loc[common] - bench.loc[common])
    return m


def run_is_oos_comparison(price, neutral, tradable, weights, signs, hs300_full):
    print("\n[4/5] IS/OOS 对比（v7 vs v9 vs v10 vs v11）...")
    hs300_ret = hs300_full["close"].pct_change().dropna() if hs300_full is not None else None

    # v7 基准
    ret_v7 = run_backtest(
        price, neutral, V7_WEIGHTS,
        n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True,
    )
    # v9（ICIR 权重，无止损）
    neutral_signed = apply_signs(neutral, signs)
    ret_v9 = run_backtest(
        price, neutral_signed, weights,
        n_stocks=N_STOCKS, cost=COST, mask=tradable, lag1=True,
    )
    # v10（v9 + 固定止损）
    ret_v10 = half_position_stop(ret_v9, threshold=BASELINE_THRESHOLD) if len(ret_v9) > 0 else ret_v9

    # v11（v9 + 自适应止损）— 用训练期 σ_t 中位数做 ref_vol
    ref_vol_is = compute_ref_vol(ret_v9, IS_START, IS_END)
    print(f"  IS 参考波动率 ref_vol = {ref_vol_is:.4f}")
    ret_v11 = adaptive_half_position_stop(
        ret_v9,
        baseline_threshold=BASELINE_THRESHOLD,
        vol_window=VOL_WINDOW,
        ref_vol=ref_vol_is,
        min_scale=MIN_SCALE, max_scale=MAX_SCALE,
    ) if len(ret_v9) > 0 else ret_v9

    results = {}
    for label, ret in [
        ("v7_fixed",    ret_v7),
        ("v9_static",   ret_v9),
        ("v10_icir+sl", ret_v10),
        ("v11_adaptive", ret_v11),
    ]:
        is_ret  = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret, hs300_ret),
            "oos": calc_metrics(oos_ret, hs300_ret) if len(oos_ret) > 20 else {},
        }
        m = results[label]["is"]
        print(f"  {label:<14} IS: 年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
              f"  回撤={m.get('mdd',0):.2%}  超额={m.get('excess',float('nan')):+.2%}")
    return results, ret_v7, ret_v9, ret_v10, ret_v11, ref_vol_is


# ══════════════════════════════════════════════════════════════════
# WF：ICIR + 自适应止损，每窗口独立 ref_vol
# ══════════════════════════════════════════════════════════════════

def run_wf_v11(price, pb):
    print("\n[5/5] Walk-Forward（v11：每窗口 ICIR + 自适应止损）...")
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)

    def wf_fn(price_slice, _fdata, train_start, train_end, test_start, test_end):
        pb_slice = pb.reindex(index=price_slice.index, columns=price_slice.columns)
        local_factors = {
            "team_coin":       _team_coin(price_slice),
            "low_vol_20d":     _low_vol_20d(price_slice),
            "cgo_simple":      -(price_slice / price_slice.rolling(60).mean() - 1),
            "enhanced_mom_60": enhanced_momentum(price_slice, window=60),
        }
        try:
            local_factors["bp"] = bp_factor(pb_slice).reindex_like(price_slice)
        except Exception:
            pass
        neutral_factors = {
            name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
            for name, fac in local_factors.items()
        }

        # 训练期 ICIR 学权重
        w_res = icir_weight(
            factors=neutral_factors, price_wide=price_slice,
            train_start=train_start, train_end=train_end,
            fwd_days=FWD_DAYS, min_weight=MIN_WEIGHT,
        )
        neutral_signed = apply_signs(neutral_factors, w_res["signs"])

        # 无止损回测
        wf_ret = run_backtest(
            price_slice, neutral_signed, w_res["weights"],
            n_stocks=N_STOCKS, cost=COST, mask=None, lag1=True,
        )
        if len(wf_ret) == 0:
            return pd.Series(dtype=float)

        # 训练期 ref_vol（严格无未来泄漏）
        ref_vol = compute_ref_vol(wf_ret, train_start, train_end)

        # 自适应止损作用于全段（含测试期）
        wf_ret = adaptive_half_position_stop(
            wf_ret,
            baseline_threshold=BASELINE_THRESHOLD,
            vol_window=VOL_WINDOW,
            ref_vol=ref_vol,
            min_scale=MIN_SCALE, max_scale=MAX_SCALE,
        )
        return wf_ret.loc[test_start:test_end]

    wf_summary = None
    try:
        wf_df = walk_forward_test(
            wf_fn, price.loc[WARMUP_START:IS_END], {},
            train_years=3, test_months=6,
        )
        valid = wf_df[wf_df["sharpe"].notna()]
        wf_summary = {
            "windows":       len(wf_df),
            "valid":         len(valid),
            "sharpe_mean":   valid["sharpe"].mean(),
            "sharpe_median": valid["sharpe"].median(),
            "return_mean":   valid["total_return"].mean(),
            "win_rate":      (valid["total_return"] > 0).mean(),
            "mdd_mean":      valid["max_drawdown"].mean(),
        }
        print(f"  窗口: {wf_summary['windows']} | 有效: {wf_summary['valid']}")
        print(f"  夏普均值:  {wf_summary['sharpe_mean']:.4f}")
        print(f"  夏普中位数: {wf_summary['sharpe_median']:.4f}  ← 目标 >0.20")
        print(f"  收益均值:  {wf_summary['return_mean']:+.2%} | 胜率: {wf_summary['win_rate']:.0%}")
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()
    return wf_summary


# ══════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════

def write_report(is_oos, weights, signs, stats, wf_v11, ref_vol_is):
    out = Path(__file__).parent.parent / "journal" / f"v11_adaptive_stop_eval_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v11 ICIR + 波动率自适应止损 — 评估报告 — {date.today()}",
        "",
        "## 方法",
        "",
        f"- 因子权重：训练期 {FWD_DAYS} 日前向收益计算 ICIR，权重 ∝ |ICIR|，min_weight {MIN_WEIGHT:.0%}",
        f"- 自适应止损：`threshold_t = {BASELINE_THRESHOLD:.0%} × clip(σ_t / σ_ref, {MIN_SCALE}, {MAX_SCALE})`",
        f"  - σ_t = {VOL_WINDOW} 日滚动年化波动率",
        f"  - σ_ref = 训练期 σ_t 中位数（IS 整段：{ref_vol_is:.4f}；WF 每窗口独立计算）",
        f"  - 阈值区间：[{BASELINE_THRESHOLD*MIN_SCALE:.0%}, {BASELINE_THRESHOLD*MAX_SCALE:.0%}]",
        "- 无未来泄漏：ICIR cutoff + ref_vol 都严格限于训练期",
        "",
        "## 权重（IS 整段学到的）",
        "",
        "| 因子 | ICIR | 方向 | v7 权重 | v11 权重 |",
        "| --- | ---: | :---: | ---: | ---: |",
    ]
    for name in ["team_coin", "low_vol_20d", "cgo_simple", "enhanced_mom_60", "bp"]:
        s = stats.get(name, {})
        lines.append(
            f"| {name} | {s.get('icir', 0):.3f} | {signs.get(name, 1):+d}"
            f" | {V7_WEIGHTS.get(name, 0):.0%} | {weights.get(name, 0):.2%} |"
        )

    lines += [
        "",
        "## IS/OOS 对比",
        "",
        "| 策略 | 区间 | 年化 | 夏普 | 最大回撤 | 超额 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for label in ["v7_fixed", "v9_static", "v10_icir+sl", "v11_adaptive"]:
        res = is_oos.get(label, {})
        for period in ["is", "oos"]:
            m = res.get(period, {})
            if not m:
                continue
            lines.append(
                f"| {label} | {period.upper()} | {m.get('ann',0):+.2%} | {m.get('sr',0):.4f}"
                f" | {m.get('mdd',0):.2%} | {m.get('excess', float('nan')):+.2%} |"
            )

    lines += [
        "",
        "## Walk-Forward",
        "",
        "| 策略 | 窗口数 | 夏普均值 | **夏普中位数** | 胜率 |",
        "| --- | ---: | ---: | ---: | ---: |",
        "| v7（手工权重） | 17 | 0.4808 | 0.0000 | 53% |",
        "| v8（regime+止损） | 17 | 0.4917 | 0.2756 | 71% |",
        "| v9（ICIR 无止损） | 17 | 0.6322 | **0.5256** | 65% |",
        "| v10（ICIR+固定止损） | 17 | 0.4414 | 0.4555 | 65% |",
    ]
    if wf_v11:
        med = wf_v11['sharpe_median']
        verdict = "✅" if med > 0.2 else "❌"
        lines.append(
            f"| **v11（ICIR+自适应止损）** | {wf_v11['windows']} | {wf_v11['sharpe_mean']:.4f}"
            f" | **{med:.4f}** {verdict} | {wf_v11['win_rate']:.0%} |"
        )

    # Admission Gate
    lines += [
        "",
        "## Admission Gate 检查（v11 IS）",
        "",
        "| 指标 | 结果 | 门槛 | 状态 |",
        "| --- | ---: | ---: | :---: |",
    ]
    v11 = is_oos.get("v11_adaptive", {}).get("is", {})
    v11_ann, v11_sr, v11_mdd = v11.get("ann", 0), v11.get("sr", 0), v11.get("mdd", 0)
    wf_med = wf_v11["sharpe_median"] if wf_v11 else 0
    checks = [
        ("年化收益",       f"{v11_ann:+.2%}",  ">15%",   v11_ann > 0.15),
        ("夏普比率",       f"{v11_sr:.4f}",    ">0.8",   v11_sr > 0.8),
        ("最大回撤",       f"{v11_mdd:.2%}",   "<-30%",  v11_mdd > -0.30),
        ("WF 夏普中位数",  f"{wf_med:.4f}",    ">0.20",  wf_med > 0.20),
    ]
    for name, val, target, ok in checks:
        lines.append(f"| {name} | {val} | {target} | {'✅' if ok else '❌'} |")

    # OOS 对比（关键：是否修复了 v10 的 OOS 崩盘）
    v11_oos = is_oos.get("v11_adaptive", {}).get("oos", {})
    v10_oos = is_oos.get("v10_icir+sl",  {}).get("oos", {})
    v9_oos  = is_oos.get("v9_static",    {}).get("oos", {})
    lines += [
        "",
        "## OOS 横向（关键：是否修复 v10 的 2025 崩盘）",
        "",
        "| 策略 | 年化 | 夏普 | 超额 | 最大回撤 |",
        "| --- | ---: | ---: | ---: | ---: |",
        f"| v9（无止损） | {v9_oos.get('ann',0):+.2%} | {v9_oos.get('sr',0):.4f}"
        f" | {v9_oos.get('excess',float('nan')):+.2%} | {v9_oos.get('mdd',0):.2%} |",
        f"| v10（固定 -8%） | {v10_oos.get('ann',0):+.2%} | {v10_oos.get('sr',0):.4f}"
        f" | {v10_oos.get('excess',float('nan')):+.2%} | {v10_oos.get('mdd',0):.2%} |",
        f"| **v11（自适应）** | **{v11_oos.get('ann',0):+.2%}** | **{v11_oos.get('sr',0):.4f}**"
        f" | **{v11_oos.get('excess',float('nan')):+.2%}** | {v11_oos.get('mdd',0):.2%} |",
    ]

    all_pass = all(c[3] for c in checks)
    v11_oos_sr = v11_oos.get("sr", 0)
    v10_oos_sr = v10_oos.get("sr", 0)
    oos_fixed = v11_oos_sr > max(v10_oos_sr, 0.5)  # 至少修复 v10 崩盘

    lines += ["", "## 结论", ""]
    if all_pass and oos_fixed:
        lines.append(
            f"### **PROMOTE** ✅\n\n"
            f"v11 通过全部 Admission Gate 且修复了 v10 的 OOS 崩盘问题。\n"
            f"自适应止损在高波动期（2025）放宽阈值，避免了 v10 的反复触发。\n"
        )
    elif oos_fixed and not all_pass:
        failed = [c[0] for c in checks if not c[3]]
        lines.append(
            f"### **CONDITIONAL PROMOTE** — OOS 已修复，但 IS 门槛未全过：{', '.join(failed)}\n"
        )
    elif all_pass and not oos_fixed:
        lines.append(
            f"### **INCONCLUSIVE** — IS 过关但 OOS 仍不理想\n\n"
            f"v11 OOS 夏普 {v11_oos_sr:.2f}，未显著优于 v10（{v10_oos_sr:.2f}）。\n"
            f"自适应阈值未能避免错误触发。建议提高 max_scale 或改用 Z-score 方案。\n"
        )
    else:
        failed = [c[0] for c in checks if not c[3]]
        lines.append(
            f"### **REJECT** — 多项未过\n\n"
            f"未过门槛：{', '.join(failed)}\n"
            f"v11 OOS 夏普 {v11_oos_sr:.2f} vs v9 无止损 {v9_oos.get('sr',0):.2f}\n"
        )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")
    return out


def main():
    t_total = time.time()
    price, pb, hs300_full, tradable = load_data()
    neutral = build_factors(price, pb)
    weights, signs, stats = compute_is_icir_weights(price, neutral)
    is_oos, ret_v7, ret_v9, ret_v10, ret_v11, ref_vol_is = run_is_oos_comparison(
        price, neutral, tradable, weights, signs, hs300_full
    )
    wf_v11 = run_wf_v11(price, pb)
    write_report(is_oos, weights, signs, stats, wf_v11, ref_vol_is)
    print(f"\n完成，总耗时 {(time.time()-t_total)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
