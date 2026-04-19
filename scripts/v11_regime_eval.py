"""
v11 候选研究：V10 + 市场状态过滤（Regime Filter）

核心改动（相对 v10）：
  - 引入三指标多数投票择时：RSRS + LLT + 高阶矩（≥2/3 看多才建仓）
  - 择时信号全部 lag1（今日信号明日生效，防未来函数）
  - 参数均来自文献，不在 IS 上优化

严谨性说明：
  - 三个择时指标均基于过去数据的滚动计算，无未来泄漏
  - RSRS 需 600 天 zscore 窗口，warmup 从 2013 年开始以确保 IS 信号质量
  - WF 验证每个窗口内仅使用训练期前的择时信号（因果性保证）
  - 诚实预期：对缓慢熊市（2022）有效，极速急跌（2024 初）效果有限

对比体系：
  v9_static  : ICIR 权重，5 因子，无择时
  v10_static : ICIR 权重，6 因子（+reversal_skip1m），无择时
  v11_static : ICIR 权重，6 因子，+ 多数投票择时

运行：python scripts/v11_regime_eval.py
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
from utils.market_regime import rsrs_regime_mask, llt_timing, higher_moment_timing
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量 ────────────────────────────────────────────────────────
WARMUP_START = "2013-01-01"
IS_START     = "2015-01-01"
IS_END       = "2024-12-31"
OOS_START    = "2025-01-01"
OOS_END      = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003
FWD_DAYS     = 20
MIN_WEIGHT   = 0.05

DIVIDER = "=" * 65


# ══════════════════════════════════════════════════════════════════
# 数据加载
# ══════════════════════════════════════════════════════════════════

def load_data():
    print(DIVIDER)
    print("  v11 因子评估报告（V10 + 市场状态过滤）")
    print(DIVIDER)
    print("\n[1/5] 加载数据...")
    t0 = time.time()

    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP_START, OOS_END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]

    pb_raw = load_price_wide(list(valid), WARMUP_START, OOS_END, field="pb")
    pb = pb_raw.reindex(index=price.index, columns=valid)

    hs300_full = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
    common = price.index.intersection(hs300_full.index)
    price = price.loc[common]
    pb = pb.reindex(index=price.index)
    hs300_full = hs300_full.loc[common]

    tradable = apply_tradability_filter(price)
    print(f"  股票: {len(valid)} | 交易日: {len(price)} | 耗时: {time.time()-t0:.1f}s")
    return price, pb, hs300_full, tradable


# ══════════════════════════════════════════════════════════════════
# 择时信号（多数投票，与 v6 完全一致）
# ══════════════════════════════════════════════════════════════════

def build_regime_mask(hs300_full: pd.DataFrame) -> pd.Series:
    """
    三指标多数投票择时：RSRS + LLT + 高阶矩。
    ≥2/3 看多 → True（可建仓），否则 → False（清仓）。

    参数全部来自文献，不在 IS 上优化：
      RSRS : upper=0.7, lower=-0.7, window=18, zscore=600
      LLT  : alpha=0.05
      高阶矩: order=5, moment_window=20, adapt_window=90
    """
    print("\n[2/5] 构建择时信号（多数投票）...")

    close  = hs300_full["close"]
    high   = hs300_full["high"]
    low    = hs300_full["low"]

    rsrs = rsrs_regime_mask(high, low)          # 阻力支撑相对强度
    llt  = llt_timing(close)                    # 低延迟趋势线
    hm   = higher_moment_timing(close, order=5) # 高阶矩方向

    common = rsrs.index.intersection(llt.index).intersection(hm.index)
    rsrs_a, llt_a, hm_a = rsrs.loc[common], llt.loc[common], hm.loc[common]

    vote = rsrs_a.astype(int) + llt_a.astype(int) + hm_a.astype(int)
    mask = (vote >= 2)
    mask.name = "majority_bullish"

    # 统计
    bull_pct = mask.mean()
    is_mask  = mask.loc[IS_START:IS_END]
    print(f"  RSRS 看多: {rsrs_a.mean():.0%}  LLT: {llt_a.mean():.0%}  高阶矩: {hm_a.mean():.0%}")
    print(f"  全期看多: {bull_pct:.0%}  IS 看多: {is_mask.mean():.0%}  "
          f"IS 看空: {1-is_mask.mean():.0%}")

    # 换手估算（看空天数 / IS 总天数 ≈ 择时触发频率）
    bearish_days = (~is_mask).sum()
    print(f"  IS 看空天数: {bearish_days}（其中看空期间强制清仓，触发额外成本）")

    return mask


# ══════════════════════════════════════════════════════════════════
# 因子构建（v10 的 6 因子）
# ══════════════════════════════════════════════════════════════════

def build_factors(price, pb):
    print("\n[3/5] 构建因子 + 行业中性化...")
    symbols = list(price.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)

    raw = {
        "team_coin":       _team_coin(price),
        "low_vol_20d":     _low_vol_20d(price),
        "cgo_simple":      -(price / price.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(price, window=60),
        "bp":              bp_factor(pb).reindex_like(price),
        "reversal_skip1m": _reversal_skip1m(price),
    }
    neutral = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in raw.items()
    }
    return neutral, industry_df


def apply_signs(factors, signs):
    return {n: f * signs.get(n, 1) for n, f in factors.items()}


def compute_icir_weights(neutral, price):
    result = icir_weight(
        factors=neutral, price_wide=price,
        train_start=IS_START, train_end=IS_END,
        fwd_days=FWD_DAYS, min_weight=MIN_WEIGHT,
    )
    return result["weights"], result["signs"]


# ══════════════════════════════════════════════════════════════════
# IS/OOS 对比
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


def run_is_oos(price, neutral, tradable, weights, signs,
               regime_mask, hs300_full):
    print("\n[4/5] IS/OOS 回测对比（v10 vs v11）...")
    hs300_ret = hs300_full["close"].pct_change().dropna()
    neutral_signed = apply_signs(neutral, signs)

    # v10：无择时
    ret_v10 = run_backtest(price, neutral_signed, weights,
                           n_stocks=N_STOCKS, cost=COST,
                           mask=tradable, regime_mask=None, lag1=True)
    # v11：加择时
    ret_v11 = run_backtest(price, neutral_signed, weights,
                           n_stocks=N_STOCKS, cost=COST,
                           mask=tradable, regime_mask=regime_mask, lag1=True)

    header = (f"  {'策略':<14} {'年化':>8} {'波动':>8} {'夏普':>7} "
              f"{'最大回撤':>10} {'卡玛':>7} {'超额':>8}")
    sep = "  " + "-" * 66

    for period, s, e in [("IS (2015-2024)", IS_START, IS_END),
                          ("OOS (2025)",    OOS_START, OOS_END)]:
        print(f"\n  ── {period} ──")
        print(header)
        print(sep)
        for name, ret in [("v10（无择时）", ret_v10), ("v11（有择时）", ret_v11)]:
            seg = ret.loc[s:e]
            if len(seg) < 5:
                continue
            m = calc_metrics(seg, hs300_ret)
            print(f"  {name:<14} {m.get('ann',0):>8.2%} {m.get('vol',0):>8.2%} "
                  f"{m.get('sr',0):>7.4f} {m.get('mdd',0):>10.2%} "
                  f"{m.get('calmar',0):>7.2f} {m.get('excess',float('nan')):>8.2%}")

    # 急跌专项
    print(f"\n  ── 急跌行情专项 ──")
    stress = [
        ("2022 熊市",  "2022-01-01", "2022-10-31"),
        ("2024 急跌",  "2024-01-01", "2024-02-05"),
        ("2025 全段",  "2025-01-01", "2025-12-31"),
    ]
    print(f"  {'段':12} {'策略':<14} {'累计':>8} {'夏普':>7} {'最大回撤':>10}")
    print("  " + "-" * 55)
    for seg_label, s, e in stress:
        for name, ret in [("v10（无择时）", ret_v10), ("v11（有择时）", ret_v11)]:
            seg = ret.loc[s:e].fillna(0)
            if len(seg) < 3:
                continue
            cum = (1 + seg).prod() - 1
            sr  = sharpe_ratio(seg) if seg.std() > 0 else 0.0
            mdd = max_drawdown(seg)
            print(f"  {seg_label:<12} {name:<14} {cum:>8.2%} {sr:>7.3f} {mdd:>10.2%}")

        # 打印该段择时信号的看多比例（诊断用）
        seg_regime = regime_mask.loc[s:e]
        if len(seg_regime) > 0:
            bull_pct = seg_regime.mean()
            print(f"  {'':12} {'  ↳ 择时看多':14} {bull_pct:>8.0%}")
        print()

    return ret_v10, ret_v11


# ══════════════════════════════════════════════════════════════════
# Walk-Forward（v11）
# ══════════════════════════════════════════════════════════════════

def run_wf(price, pb, industry_df, regime_mask):
    print(f"\n[5/5] Walk-Forward（v11）...")

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
        w_res = icir_weight(
            factors=neutral, price_wide=price_slice,
            train_start=train_start, train_end=train_end,
            fwd_days=FWD_DAYS, min_weight=MIN_WEIGHT,
        )
        weights = w_res["weights"]
        signs   = w_res["signs"]
        neutral_signed = {n: f * signs.get(n, 1) for n, f in neutral.items()}

        # 择时 mask：在 WF 窗口内切片（因果性：regime 用过去 hs300 数据计算，无泄漏）
        local_regime = regime_mask.reindex(price_slice.index).ffill().fillna(True)

        wf_ret = run_backtest(
            price_slice, neutral_signed, weights,
            n_stocks=N_STOCKS, cost=COST,
            mask=None, regime_mask=local_regime, lag1=True,
        )
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

        # 与 v10 WF 对比（v10 WF 中位数夏普 0.58）
        print(f"\n  对比 v10 WF 中位数夏普 0.5829 → v11: {valid['sharpe'].median():.4f} "
              f"({'↑改善' if valid['sharpe'].median() > 0.5829 else '↓下降'})")
        return wf_df
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()
        return None


# ══════════════════════════════════════════════════════════════════
# 报告
# ══════════════════════════════════════════════════════════════════

def write_report(ret_v10, ret_v11, weights, signs, wf_df, regime_mask):
    out = Path(__file__).parent.parent / "journal" / f"v11_regime_eval_{date.today().strftime('%Y%m%d')}.md"

    def fmt(ret, s, e):
        seg = ret.loc[s:e]
        if len(seg) < 5:
            return "N/A"
        m = calc_metrics(seg)
        return (f"年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
                f"  回撤={m.get('mdd',0):.2%}  卡玛={m.get('calmar',0):.2f}")

    stress_rows = []
    for label, s, e in [("2022熊市","2022-01-01","2022-10-31"),
                         ("2024急跌","2024-01-01","2024-02-05"),
                         ("2025全段","2025-01-01","2025-12-31")]:
        c10 = (1 + ret_v10.loc[s:e].fillna(0)).prod() - 1
        c11 = (1 + ret_v11.loc[s:e].fillna(0)).prod() - 1
        bull = regime_mask.loc[s:e].mean()
        stress_rows.append(f"| {label} | {c10:+.2%} | {c11:+.2%} | {bull:.0%} |")

    wf_lines = []
    if wf_df is not None:
        valid = wf_df[wf_df["sharpe"].notna()]
        wf_lines = [
            "",
            "## Walk-Forward（v11）",
            "",
            f"- 窗口数: {len(wf_df)}（有效: {len(valid)}）",
            f"- 夏普均值: {valid['sharpe'].mean():.4f}",
            f"- 夏普中位数: {valid['sharpe'].median():.4f}（v10: 0.5829）",
            f"- 胜率: {(valid['total_return']>0).mean():.0%}",
            f"- 回撤均值: {valid['max_drawdown'].mean():.2%}",
        ]

    is_bull = regime_mask.loc[IS_START:IS_END].mean()

    lines = [
        f"# v11 市场状态过滤评估报告 — {date.today()}",
        "",
        "## 核心改动",
        "",
        "在 v10（6因子 ICIR 加权）基础上，引入三指标多数投票择时：",
        "**RSRS + LLT + 高阶矩**，≥2/3 看多才建仓，否则清仓持现金。",
        "",
        "参数全部来自文献，未在 IS 上优化：",
        "- RSRS：upper=0.7, lower=-0.7, window=18, zscore_window=600",
        "- LLT：alpha=0.05（二阶 IIR 低延迟趋势线）",
        "- 高阶矩：order=5，EMA alpha=0.2",
        "",
        f"IS 期间择时看多比例：{is_bull:.0%}（看空 {1-is_bull:.0%}，即约 {(1-is_bull)*2440:.0f} 天持现金）",
        "",
        "## IS 表现（2015-2024）",
        "",
        f"- v10（无择时）: {fmt(ret_v10, IS_START, IS_END)}",
        f"- v11（有择时）: {fmt(ret_v11, IS_START, IS_END)}",
        "",
        "## OOS 表现（2025）",
        "",
        f"- v10（无择时）: {fmt(ret_v10, OOS_START, OOS_END)}",
        f"- v11（有择时）: {fmt(ret_v11, OOS_START, OOS_END)}",
        "",
        "## 急跌行情对比",
        "",
        "| 段 | v10 累计 | v11 累计 | 择时看多比例 |",
        "|---|---|---|---|",
    ] + stress_rows + [
        "",
        "## 诚实评估",
        "",
        "- 择时对**缓慢熊市**（2022）有效：RSRS + LLT 能跟上趋势反转",
        "- 择时对**极速急跌**（2024 Jan-Feb）效果有限：",
        "  RSRS 基于 600 天 zscore，反应慢；LLT 延迟约 1/alpha=20 天",
        "- 择时的代价：看空期间持现金，会踏空快速反弹",
        "- 卡玛比率（年化收益/最大回撤）是判断是否值得的关键指标",
    ] + wf_lines + ["", "## 结论", "", "（待填写）"]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n  报告已写入: {out.name}")


# ══════════════════════════════════════════════════════════════════
# 主流程
# ══════════════════════════════════════════════════════════════════

def main():
    price, pb, hs300_full, tradable = load_data()
    regime_mask = build_regime_mask(hs300_full)
    neutral, industry_df = build_factors(price, pb)
    weights, signs = compute_icir_weights(neutral, price)
    ret_v10, ret_v11 = run_is_oos(
        price, neutral, tradable, weights, signs, regime_mask, hs300_full)
    wf_df = run_wf(price, pb, industry_df, regime_mask)
    write_report(ret_v10, ret_v11, weights, signs, wf_df, regime_mask)

    print(f"\n{DIVIDER}")
    print("  评估完成")
    print(DIVIDER)


if __name__ == "__main__":
    main()
