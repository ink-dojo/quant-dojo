"""
v10 候选研究：ICIR 学习权重 + 组合层止损

把 v9（ICIR 动态学权重）和 v8 的 half_position_stop（-8% 降仓 50%）拼在一起。

相对 v8 优势：去掉了两层人工成分
  - 不需要手工 regime 识别（120日均线+RSRS）
  - 不需要手工 bull/flat/bear × 5 因子的权重表（15 个人工数字）
  - 只留一个客观的止损参数

设计目标：通过完整 Admission Gate
  年化 >15% / 夏普 >0.8 / IS 回撤 <-30% / WF 中位数 >0.20

运行：python scripts/v10_icir_stoploss_eval.py
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
from utils.stop_loss import half_position_stop
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START     = "2013-01-01"
IS_START         = "2015-01-01"
IS_END           = "2024-12-31"
OOS_START        = "2025-01-01"
OOS_END          = "2025-12-31"
N_STOCKS         = 30
COST             = 0.003
FWD_DAYS         = 20
MIN_WEIGHT       = 0.05
STOP_LOSS_THRESH = -0.08   # 累计回撤超 -8% 降仓 50%

V7_WEIGHTS = {
    "team_coin":       0.30,
    "low_vol_20d":     0.25,
    "cgo_simple":      0.20,
    "enhanced_mom_60": 0.15,
    "bp":              0.10,
}


# ══════════════════════════════════════════════════════════════════
# 数据加载 / 因子构建（同 v9）
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
# ICIR 学习（同 v9_static 路径）
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
    print("\n[4/5] IS/OOS 对比（v7 vs v9 vs v10）...")
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
    # v10（v9 + 止损）
    ret_v10 = half_position_stop(ret_v9, threshold=STOP_LOSS_THRESH) if len(ret_v9) > 0 else ret_v9

    results = {}
    for label, ret in [("v7_fixed", ret_v7), ("v9_static", ret_v9), ("v10_icir+sl", ret_v10)]:
        is_ret  = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret, hs300_ret),
            "oos": calc_metrics(oos_ret, hs300_ret) if len(oos_ret) > 20 else {},
        }
        m = results[label]["is"]
        print(f"  {label:<14} IS: 年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
              f"  回撤={m.get('mdd',0):.2%}  超额={m.get('excess',float('nan')):+.2%}")
    return results, ret_v7, ret_v9, ret_v10


# ══════════════════════════════════════════════════════════════════
# WF：ICIR 学权重 + 止损
# ══════════════════════════════════════════════════════════════════

def run_wf_v10(price, pb, tradable):
    print("\n[5/5] Walk-Forward（v10：每窗口 ICIR + 止损）...")
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

        # 回测
        wf_ret = run_backtest(
            price_slice, neutral_signed, w_res["weights"],
            n_stocks=N_STOCKS, cost=COST, mask=None, lag1=True,
        )
        # 止损
        if len(wf_ret) > 0:
            wf_ret = half_position_stop(wf_ret, threshold=STOP_LOSS_THRESH)
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
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()
    return wf_summary


# ══════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════

def write_report(is_oos, weights, signs, stats, wf_v10):
    out = Path(__file__).parent.parent / "journal" / f"v10_icir_stoploss_eval_{date.today().strftime('%Y%m%d')}.md"
    lines = [
        f"# v10 ICIR 学习 + 组合止损 — 评估报告 — {date.today()}",
        "",
        "## 方法",
        "",
        f"- 因子权重：训练期 {FWD_DAYS} 日前向收益计算 ICIR，权重 ∝ |ICIR|，min_weight {MIN_WEIGHT:.0%}",
        f"- 组合止损：累计回撤 > {STOP_LOSS_THRESH:.0%} 降仓至 50%，净值新高后恢复满仓",
        "- 严格无未来泄漏：ICIR 训练窗口截断至 train_end-fwd_days",
        "",
        "## 权重（IS 整段学到的）",
        "",
        "| 因子 | ICIR | 方向 | v7 权重 | v10 权重 |",
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
    for label in ["v7_fixed", "v9_static", "v10_icir+sl"]:
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
        "| v7（手工权重） | 17 | 0.4808 | **0.0000** | 53% |",
        "| v8（regime+止损） | 17 | 0.4917 | 0.2756 | 71% |",
        "| v9（ICIR 无止损） | 17 | 0.6322 | 0.5256 | 65% |",
    ]
    if wf_v10:
        med = wf_v10['sharpe_median']
        verdict = "✅" if med > 0.2 else "❌"
        lines.append(
            f"| **v10（ICIR+止损）** | {wf_v10['windows']} | {wf_v10['sharpe_mean']:.4f}"
            f" | **{med:.4f}** {verdict} | {wf_v10['win_rate']:.0%} |"
        )

    # Admission Gate
    lines += [
        "",
        "## Admission Gate 检查（v10 IS）",
        "",
        "| 指标 | 结果 | 门槛 | 状态 |",
        "| --- | ---: | ---: | :---: |",
    ]
    v10 = is_oos.get("v10_icir+sl", {}).get("is", {})
    v10_ann, v10_sr, v10_mdd = v10.get("ann", 0), v10.get("sr", 0), v10.get("mdd", 0)
    wf_med = wf_v10["sharpe_median"] if wf_v10 else 0
    checks = [
        ("年化收益", f"{v10_ann:+.2%}", ">15%",    v10_ann > 0.15),
        ("夏普比率", f"{v10_sr:.4f}",   ">0.8",    v10_sr > 0.8),
        ("最大回撤", f"{v10_mdd:.2%}",  "<-30%",  v10_mdd > -0.30),
        ("WF 夏普中位数", f"{wf_med:.4f}", ">0.20",  wf_med > 0.20),
    ]
    for name, val, target, ok in checks:
        lines.append(f"| {name} | {val} | {target} | {'✅' if ok else '❌'} |")

    all_pass = all(c[3] for c in checks)

    lines += ["", "## 结论", ""]
    if all_pass:
        lines.append(
            f"### **PROMOTE** ✅\n\n"
            f"v10 通过全部 Admission Gate。相对 v8，去掉了：\n"
            f"- 手工 regime 识别（120日均线+RSRS+平滑参数）\n"
            f"- 手工 bull/flat/bear × 5因子 共 15 个权重数字\n\n"
            f"保留：5 个因子 + ICIR 自动加权 + 1 个止损阈值。\n\n"
            f"建议作为 Phase 3 最终候选合入。"
        )
    else:
        failed = [c[0] for c in checks if not c[3]]
        lines.append(
            f"### **CONDITIONAL** — 未通过门槛：{', '.join(failed)}\n\n"
            f"需进一步调整止损阈值或权重地板。"
        )

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")
    return out


def main():
    t_total = time.time()
    price, pb, hs300_full, tradable = load_data()
    neutral = build_factors(price, pb)
    weights, signs, stats = compute_is_icir_weights(price, neutral)
    is_oos, ret_v7, ret_v9, ret_v10 = run_is_oos_comparison(
        price, neutral, tradable, weights, signs, hs300_full
    )
    wf_v10 = run_wf_v10(price, pb, tradable)
    write_report(is_oos, weights, signs, stats, wf_v10)
    print(f"\n完成，总耗时 {(time.time()-t_total)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
