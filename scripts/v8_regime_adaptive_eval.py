"""
v8 候选研究：市场状态自适应因子权重

核心改动：
  - 牛市（bull）：加大动量权重，削减均值回归权重
  - 震荡（flat）：沿用 v7 标准权重
  - 熊市（bear）：加大低波动 / CGO 权重，削减动量

对比：v7固定权重 vs v8自适应权重，同样的因子集，只改换仓时的权重逻辑。
目标：WF 夏普中位数从 0.00 提升到 >0.20。

运行：python scripts/v8_regime_adaptive_eval.py
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
from utils.factor_analysis import (
    compute_ic_series, ic_summary,
    neutralize_factor_by_industry,
)
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.market_regime import (
    rsrs_regime_mask, llt_timing, higher_moment_timing,
    classify_regime_3state, smooth_regime,
)
from utils.stop_loss import half_position_stop
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest, run_backtest_adaptive

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START = "2013-01-01"
IS_START     = "2015-01-01"
IS_END       = "2024-12-31"
OOS_START    = "2025-01-01"
OOS_END      = "2025-12-31"
N_STOCKS     = 30
COST         = 0.003

# ── v7 基准权重（固定） ──────────────────────────────────────────
V7_WEIGHTS = {
    "team_coin":       0.30,
    "low_vol_20d":     0.25,
    "cgo_simple":      0.20,
    "enhanced_mom_60": 0.15,
    "bp":              0.10,
}

# ── v8 三档自适应权重（v2：收敛 bull 激进程度，控制回撤）────────────
# v1 问题：bull 状态 momentum 30% 导致 IS 回撤 -44%（超门槛 -30%）
# v2 修正：
#   bull  动量从 30% → 22%，low_vol 从 10% → 15%（保留部分防御）
#   bear  不变
#   切换平滑：classify_regime_3state → smooth_regime(window=5)
V8_REGIME_WEIGHTS = {
    "bull": {
        "team_coin":       0.33,   # 动量类，牛市有效
        "enhanced_mom_60": 0.22,   # 经典动量（从 30% 降至 22%，减少回撤）
        "bp":              0.20,   # 价值，穿越周期
        "low_vol_20d":     0.15,   # 保留部分防御（从 10% 升至 15%）
        "cgo_simple":      0.10,   # 少量均值回归
    },
    "flat": V7_WEIGHTS,            # 震荡市：v7 原始权重不变
    "bear": {
        "low_vol_20d":     0.40,   # 低波动防御，最大化
        "cgo_simple":      0.25,   # 均值回归，熊市最有效
        "team_coin":       0.20,   # 保留，熊市也有一定效果
        "bp":              0.10,   # 价值，防御
        "enhanced_mom_60": 0.05,   # 动量在熊市基本无效
    },
}

# 平滑参数（避免单日噪音触发权重切换）
REGIME_SMOOTH_WINDOW = 5   # 5日滚动投票
REGIME_SMOOTH_THRESH = 2   # 净得分 ≥ 2 才切换

# 组合层动态止损（方案2）
# 累计回撤超过 STOP_LOSS_THRESH 时降仓至 50%，净值创新高后恢复满仓
STOP_LOSS_THRESH = -0.08   # -8% 触发降仓


# ══════════════════════════════════════════════════════════════════
# 数据加载
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
# 因子构建
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
# 市场状态分类
# ══════════════════════════════════════════════════════════════════

def build_regime(hs300_full):
    print("\n[3/5] 计算市场状态（三档）...")
    if hs300_full is None:
        print("  无 HS300，跳过择时，全程 flat")
        return None, None

    regime3_raw = classify_regime_3state(
        close=hs300_full["close"],
        high=hs300_full["high"],
        low=hs300_full["low"],
    )
    regime3 = smooth_regime(regime3_raw, window=REGIME_SMOOTH_WINDOW, bull_threshold=REGIME_SMOOTH_THRESH, bear_threshold=-REGIME_SMOOTH_THRESH)

    raw_counts = regime3_raw.value_counts()
    smooth_counts = regime3.value_counts()
    total = len(regime3.dropna())
    print(f"  {'状态':<8} {'原始':>8} {'平滑后':>8}")
    for state in ["bull", "flat", "bear"]:
        r = raw_counts.get(state, 0)
        s = smooth_counts.get(state, 0)
        print(f"  {state:<8} {r:>5}天({r/total:.0%}) → {s:>5}天({s/total:.0%})")

    # v7 原始二元择时（用于对比基准）
    try:
        rsrs = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])
        llt = llt_timing(hs300_full["close"])
        hm = higher_moment_timing(hs300_full["close"], order=5)
        c = rsrs.index.intersection(llt.index).intersection(hm.index)
        vote = rsrs.loc[c].astype(int) + llt.loc[c].astype(int) + hm.loc[c].astype(int)
        v7_regime_mask = vote >= 2
    except Exception:
        v7_regime_mask = None

    return regime3, v7_regime_mask


# ══════════════════════════════════════════════════════════════════
# IS 对比回测
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


def run_is_oos_comparison(price, neutral, tradable, regime3, v7_regime_mask, hs300_full):
    print("\n[4/5] IS/OOS 对比...")

    hs300_ret = hs300_full["close"].pct_change().dropna() if hs300_full is not None else None

    # v7 基准（固定权重 + 二元择时）
    ret_v7 = run_backtest(
        price, neutral, V7_WEIGHTS, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, regime_mask=v7_regime_mask, lag1=True,
    )

    # v8 自适应（三档权重，无二元择时——自适应权重本身就是 regime-aware）
    ret_v8 = run_backtest_adaptive(
        price, neutral,
        regime_weights=V8_REGIME_WEIGHTS,
        regime_series=regime3,
        n_stocks=N_STOCKS, cost=COST,
        mask=tradable, lag1=True,
    ) if regime3 is not None else pd.Series(dtype=float)

    # v8 加组合层止损
    ret_v8_sl = half_position_stop(ret_v8, threshold=STOP_LOSS_THRESH) if len(ret_v8) > 0 else ret_v8

    results = {}
    for label, ret in [("v7_fixed", ret_v7), ("v8_adaptive", ret_v8), ("v8_adaptive+sl", ret_v8_sl)]:
        is_ret  = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret, hs300_ret),
            "oos": calc_metrics(oos_ret, hs300_ret) if len(oos_ret) > 20 else {},
        }
        m = results[label]["is"]
        print(f"  {label} IS: 年化={m.get('ann',0):+.2%}  夏普={m.get('sr',0):.4f}"
              f"  回撤={m.get('mdd',0):.2%}  超额={m.get('excess',float('nan')):+.2%}")

    return results, ret_v7, ret_v8, ret_v8_sl


# ══════════════════════════════════════════════════════════════════
# Walk-Forward（三档自适应）
# ══════════════════════════════════════════════════════════════════

def run_wf_adaptive(price, pb, tradable, regime3):
    print("\n[5/5] Walk-Forward 验证（v8 自适应）...")
    if regime3 is None:
        print("  无 regime，跳过")
        return None

    symbols = list(price.columns)
    pb_full = pb.reindex(index=price.index, columns=symbols)
    regime_full = regime3

    def wf_fn(price_slice, _fdata, train_start, train_end, test_start, test_end):
        pb_slice = pb_full.reindex(index=price_slice.index, columns=price_slice.columns)

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

        industry_df = get_industry_classification(symbols=symbols, use_cache=True)
        neutral_factors = {
            name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
            for name, fac in local_factors.items()
        }

        # regime series 切到本窗口范围
        regime_slice = regime_full.reindex(price_slice.index).ffill().bfill()

        wf_ret = run_backtest_adaptive(
            price_slice, neutral_factors,
            regime_weights=V8_REGIME_WEIGHTS,
            regime_series=regime_slice,
            n_stocks=N_STOCKS, cost=COST,
            mask=None, lag1=True,
        )
        # 加组合层止损
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

def write_report(is_oos, wf_v7_ref, wf_v8):
    """
    wf_v7_ref: {"sharpe_mean": 0.4808, "sharpe_median": 0.0, "win_rate": 0.53}  (来自 v7 历史结果)
    wf_v8: dict from run_wf_adaptive
    """
    out = Path(__file__).parent.parent / "journal" / f"v8_regime_adaptive_eval_{date.today().strftime('%Y%m%d')}.md"

    lines = [
        f"# v8 市场状态自适应 — 评估报告 — {date.today()}",
        "",
        "## 权重设计",
        "",
        "| 状态 | team_coin | low_vol | cgo | momentum | bp |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    for state, w in V8_REGIME_WEIGHTS.items():
        total = sum(w.values())
        lines.append(
            f"| {state} | {w.get('team_coin',0)/total:.0%} | {w.get('low_vol_20d',0)/total:.0%}"
            f" | {w.get('cgo_simple',0)/total:.0%} | {w.get('enhanced_mom_60',0)/total:.0%}"
            f" | {w.get('bp',0)/total:.0%} |"
        )

    lines += [
        "",
        "## IS/OOS 对比",
        "",
        "| 策略 | 区间 | 年化 | 夏普 | 最大回撤 | 超额 |",
        "| --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for label in ["v7_fixed", "v8_adaptive", "v8_adaptive+sl"]:
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
        f"| v7（固定权重，历史基准） | 17 | 0.4808 | **0.0000** | 53% |",
    ]
    if wf_v8:
        med = wf_v8['sharpe_median']
        verdict = "✅ 改善" if med > 0.1 else ("⚠️ 轻微改善" if med > 0 else "❌ 未改善")
        lines.append(
            f"| v8（自适应权重） | {wf_v8['windows']} | {wf_v8['sharpe_mean']:.4f}"
            f" | **{med:.4f}** {verdict} | {wf_v8['win_rate']:.0%} |"
        )

    lines += ["", "## 结论", ""]
    if wf_v8:
        med = wf_v8['sharpe_median']
        v8_sl = is_oos.get("v8_adaptive+sl", {}).get("is", {})
        v8_mdd = v8_sl.get("mdd", -99)
        v8_sr  = v8_sl.get("sr", 0)
        v7_sr  = is_oos.get("v7_fixed", {}).get("is", {}).get("sr", 0)
        if med > 0.2 and v8_mdd > -0.30 and v8_sr >= v7_sr * 0.85:
            verdict = (
                f"**PROMOTE** — WF 中位数={med:.4f}，IS 回撤={v8_mdd:.2%}（通过 -30% 门槛），"
                f"夏普={v8_sr:.4f}。建议作为 v8 正式候选提交入模。"
            )
        elif med > 0.2:
            verdict = (
                f"**CONDITIONAL** — WF 中位数={med:.4f} 已达标，但 IS 回撤={v8_mdd:.2%} 仍超 -30% 门槛。"
                f"需进一步加强止损或收窄 bull 权重。"
            )
        elif med > 0.0:
            verdict = "**CONDITIONAL** — WF 中位数有改善但未达 0.20，继续优化权重设计。"
        else:
            verdict = "**RETHINK** — WF 中位数未改善，市场状态分类或权重设计需要重新调整。"
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
    regime3, v7_regime_mask = build_regime(hs300_full)
    is_oos, ret_v7, ret_v8, ret_v8_sl = run_is_oos_comparison(
        price, neutral, tradable, regime3, v7_regime_mask, hs300_full
    )
    wf_summary = run_wf_adaptive(price, pb, tradable, regime3)

    # v7 WF 历史基准
    wf_v7_ref = {"sharpe_mean": 0.4808, "sharpe_median": 0.0000, "win_rate": 0.53}
    write_report(is_oos, wf_v7_ref, wf_summary)

    print(f"\n完成，总耗时 {(time.time()-t_total)/60:.1f} 分钟")


if __name__ == "__main__":
    main()
