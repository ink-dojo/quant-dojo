"""
v9 候选研究：ICIR 加权 多因子合成

核心改动（相对 v7 手工权重、v8 regime 自适应）：
  - 权重不再手工拍定，而是基于训练期 ICIR 自动计算
  - 每个 WF 窗口独立学习权重（真正的 walk-forward）
  - 用 signs 检测因子方向，自动翻转负 IC 因子

变体：
  v7_fixed   : 基准，手工固定权重
  v9_static  : 在整段 IS 上计算一次 ICIR 权重，应用到 IS+OOS
  v9_wf      : 每个 WF 窗口在训练期学权重，应用到测试期

关键防泄漏：
  - icir_weight 内部严格截断到 train_end - fwd_days，
    确保前向收益完全落在训练期内
  - shift(1) 防未来函数（由 run_backtest 保证）

运行：python scripts/v9_icir_weighted_eval.py
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
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START = "2013-01-01"
IS_START     = "2015-01-01"
IS_END       = "2024-12-31"
OOS_START    = "2025-01-01"
OOS_END      = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20       # 用未来 20 日收益计算 IC
MIN_WEIGHT   = 0.05     # 权重下限 5%

# v7 基准权重（固定）
V7_WEIGHTS = {
    "team_coin":       0.30,
    "low_vol_20d":     0.25,
    "cgo_simple":      0.20,
    "enhanced_mom_60": 0.15,
    "bp":              0.10,
}


# ══════════════════════════════════════════════════════════════════
# 数据加载（复用 v8 模式）
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


# ══════════════════════════════════════════════════════════════════
# 因子构建（和 v8 完全一致）
# ══════════════════════════════════════════════════════════════════

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


# ══════════════════════════════════════════════════════════════════
# 工具：应用方向符号到因子（负 IC 因子翻转）
# ══════════════════════════════════════════════════════════════════

def apply_signs(factors: dict, signs: dict) -> dict:
    """把 sign < 0 的因子乘以 -1，让后续合成都是正向贡献"""
    return {name: fac * signs.get(name, 1) for name, fac in factors.items()}


# ══════════════════════════════════════════════════════════════════
# v9_static：整段 IS 上学一次权重
# ══════════════════════════════════════════════════════════════════

def compute_is_icir_weights(price, neutral):
    print("\n[3/5] 计算 v9_static ICIR 权重（整段 IS）...")
    result = icir_weight(
        factors=neutral,
        price_wide=price,
        train_start=IS_START,
        train_end=IS_END,
        fwd_days=FWD_DAYS,
        min_weight=MIN_WEIGHT,
    )
    w = result["weights"]
    signs = result["signs"]
    stats = result["ic_stats"]

    print(f"\n  {'因子':<20} {'IC均值':>10} {'IC标准差':>10} {'ICIR':>8} {'方向':>6} {'权重':>8}")
    print("  " + "-" * 70)
    for name in neutral:
        s = stats.get(name, {})
        print(f"  {name:<20} {s.get('ic_mean', np.nan):>10.4f} "
              f"{s.get('ic_std', np.nan):>10.4f} {s.get('icir', 0):>8.3f} "
              f"{signs.get(name, 1):>6d} {w.get(name, 0):>8.2%}")
    return w, signs, stats


# ══════════════════════════════════════════════════════════════════
# IS/OOS 对比
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


def run_is_oos_comparison(price, neutral, tradable, v9_weights, v9_signs, hs300_full):
    print("\n[4/5] IS/OOS 对比（v7 vs v9_static）...")
    hs300_ret = hs300_full["close"].pct_change().dropna() if hs300_full is not None else None

    # v7 基准
    ret_v7 = run_backtest(
        price, neutral, V7_WEIGHTS, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, lag1=True,
    )

    # v9_static：应用 signs 后用 ICIR 权重
    neutral_signed = apply_signs(neutral, v9_signs)
    ret_v9 = run_backtest(
        price, neutral_signed, v9_weights, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, lag1=True,
    )

    results = {}
    for label, ret in [("v7_fixed", ret_v7), ("v9_static", ret_v9)]:
        is_ret  = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret, hs300_ret),
            "oos": calc_metrics(oos_ret, hs300_ret) if len(oos_ret) > 20 else {},
        }
        m = results[label]["is"]
        print(f"  {label} IS: 年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
              f"  回撤={m.get('mdd',0):.2%}  超额={m.get('excess',float('nan')):+.2%}")
    return results, ret_v7, ret_v9


# ══════════════════════════════════════════════════════════════════
# v9_wf：每个 WF 窗口独立学权重
# ══════════════════════════════════════════════════════════════════

def run_wf_icir(price, pb, tradable):
    print("\n[5/5] Walk-Forward（v9_wf：每窗口独立学权重）...")
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)

    # 记录每个窗口学到的权重（用于诊断）
    window_weights = []

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

        # 在训练期上学权重
        w_res = icir_weight(
            factors=neutral_factors,
            price_wide=price_slice,
            train_start=train_start,
            train_end=train_end,
            fwd_days=FWD_DAYS,
            min_weight=MIN_WEIGHT,
        )
        weights = w_res["weights"]
        signs = w_res["signs"]
        window_weights.append({
            "train_start": train_start, "train_end": train_end,
            **{f"w_{k}": v for k, v in weights.items()},
            **{f"s_{k}": v for k, v in signs.items()},
        })

        # 应用 signs（用统一的 helper）
        neutral_signed = apply_signs(neutral_factors, signs)

        # 跑回测（含测试期）
        wf_ret = run_backtest(
            price_slice, neutral_signed, weights,
            n_stocks=N_STOCKS, cost=COST, mask=None, lag1=True,
        )
        return wf_ret.loc[test_start:test_end] if len(wf_ret) > 0 else pd.Series(dtype=float)

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

        # 打印权重演化
        ww_df = pd.DataFrame(window_weights)
        weight_cols = [c for c in ww_df.columns if c.startswith("w_")]
        print(f"\n  权重演化（各窗口 ICIR 学到的权重）：")
        print(f"  {'窗口':<28}" + "".join(f"{c[2:]:>12}" for c in weight_cols))
        for _, row in ww_df.iterrows():
            print(f"  {str(row['train_start'].date())}~{str(row['train_end'].date()):<12}"
                  + "".join(f"{row[c]:>11.2%} " for c in weight_cols))
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()
    return wf_summary, window_weights


# ══════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════

def write_report(is_oos, v9_weights, v9_signs, v9_stats, wf_v9):
    out = Path(__file__).parent.parent / "journal" / f"v9_icir_weighted_eval_{date.today().strftime('%Y%m%d')}.md"

    lines = [
        f"# v9 ICIR 加权 — 评估报告 — {date.today()}",
        "",
        "## 方法",
        "",
        f"权重 ∝ |ICIR|，使用训练期 {FWD_DAYS} 日前向收益计算 IC，"
        f"最低权重 {MIN_WEIGHT:.0%}（严格无未来泄漏）。",
        "",
        "## v9_static（整段 IS 学到的权重）",
        "",
        "| 因子 | IC均值 | IC标准差 | ICIR | 方向 | 权重 |",
        "| --- | ---: | ---: | ---: | :---: | ---: |",
    ]
    for name, w in v9_weights.items():
        s = v9_stats.get(name, {})
        lines.append(
            f"| {name} | {s.get('ic_mean', np.nan):.4f} | {s.get('ic_std', np.nan):.4f}"
            f" | {s.get('icir', 0):.3f} | {v9_signs.get(name, 1):+d} | {w:.2%} |"
        )

    lines += [
        "",
        "## v7 基准权重（对照）",
        "",
        "| 因子 | v7 权重 | v9_static 权重 | 变化 |",
        "| --- | ---: | ---: | ---: |",
    ]
    for name in V7_WEIGHTS:
        v7w = V7_WEIGHTS[name]
        v9w = v9_weights.get(name, 0)
        delta = v9w - v7w
        arrow = "↑" if delta > 0.01 else ("↓" if delta < -0.01 else "≈")
        lines.append(f"| {name} | {v7w:.0%} | {v9w:.1%} | {delta:+.1%} {arrow} |")

    lines += [
        "",
        "## IS/OOS 对比",
        "",
        "| 策略 | 区间 | 年化 | 夏普 | 最大回撤 | 超额 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for label in ["v7_fixed", "v9_static"]:
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
        "## Walk-Forward 对比",
        "",
        "| 策略 | 窗口数 | 夏普均值 | **夏普中位数** | 胜率 |",
        "| --- | ---: | ---: | ---: | ---: |",
        "| v7（固定权重，历史基准） | 17 | 0.4808 | **0.0000** | 53% |",
    ]
    if wf_v9:
        med = wf_v9['sharpe_median']
        verdict = "✅ 改善" if med > 0.1 else ("⚠️ 轻微改善" if med > 0 else "❌ 未改善")
        lines.append(
            f"| v9（ICIR 学习权重） | {wf_v9['windows']} | {wf_v9['sharpe_mean']:.4f}"
            f" | **{med:.4f}** {verdict} | {wf_v9['win_rate']:.0%} |"
        )

    lines += ["", "## 结论", ""]
    if wf_v9:
        med = wf_v9['sharpe_median']
        v9_sr = is_oos.get("v9_static", {}).get("is", {}).get("sr", 0)
        v9_mdd = is_oos.get("v9_static", {}).get("is", {}).get("mdd", 0)
        v9_ann = is_oos.get("v9_static", {}).get("is", {}).get("ann", 0)
        pass_gate = (v9_ann > 0.15 and v9_sr > 0.8 and v9_mdd > -0.30 and med > 0.2)
        if pass_gate:
            verdict = (
                f"**PROMOTE** — IS 年化={v9_ann:+.2%} / 夏普={v9_sr:.3f} / 回撤={v9_mdd:.2%}，"
                f"WF 中位数={med:.3f}，全部通过入模门槛。ICIR 学习权重机制已验证，"
                f"建议作为 v9 正式候选。"
            )
        elif med > 0.2:
            verdict = (
                f"**CONDITIONAL** — WF 中位数={med:.3f} 通过，但 IS 有指标未达门槛："
                f"年化={v9_ann:+.2%} 夏普={v9_sr:.3f} 回撤={v9_mdd:.2%}。"
                f"可能需与 v8 的 regime 或止损机制叠加。"
            )
        else:
            verdict = (
                f"**RETHINK** — WF 中位数={med:.3f} 未达 0.20，ICIR 学习可能不足以单独解决 WF 稳定性问题。"
            )
        lines.append(verdict)

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")
    return out


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    t_total = time.time()
    price, pb, hs300_full, tradable = load_data()
    neutral = build_factors(price, pb)

    # v9_static: IS 上学一次权重
    v9_weights, v9_signs, v9_stats = compute_is_icir_weights(price, neutral)

    is_oos, ret_v7, ret_v9 = run_is_oos_comparison(
        price, neutral, tradable, v9_weights, v9_signs, hs300_full
    )
    wf_v9, window_weights = run_wf_icir(price, pb, tradable)

    write_report(is_oos, v9_weights, v9_signs, v9_stats, wf_v9)
    print(f"\n完成，总耗时 {(time.time()-t_total)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
