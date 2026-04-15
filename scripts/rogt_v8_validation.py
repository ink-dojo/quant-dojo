"""
ROGT 策略级完整验证 — v7+ROGT (6因子) Walk-Forward + OOS分层 + 参数敏感性

补全 factor_research.py 没有做的策略层面测试：
  1. IS 组合对比  (v7 5因子 vs v7+ROGT 6因子)
  2. Walk-Forward (6因子, train=3y, test=6m)
  3. OOS 分层回测 (单因子 ROGT，2024)
  4. 参数敏感性    (window=10/15/20/25/30)

结果写到 journal/rogt_v8_validation_YYYYMMDD.md
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
    quintile_backtest,
    neutralize_factor_by_industry,
)
from utils.fundamental_loader import get_industry_classification
from utils.tradability_filter import apply_tradability_filter
from utils.market_regime import rsrs_regime_mask, llt_timing, higher_moment_timing
from utils.alpha_factors import (
    team_coin as _team_coin,
    low_vol_20d as _low_vol_20d,
    enhanced_momentum,
    bp_factor,
    retail_open_trap,
)
from utils.walk_forward import walk_forward_test
from scripts.v6_admission_eval import run_backtest

# ── 常量 ─────────────────────────────────────────────────────────
WARMUP_START = "2013-01-01"
IS_START     = "2015-01-01"
IS_END       = "2023-12-31"   # 单因子 IS 同 factor_research.py
OOS_START    = "2024-01-01"
OOS_END      = "2024-12-31"
N_STOCKS     = 30
COST         = 0.003
ROGT_WINDOW  = 20             # baseline 参数

V7_WEIGHTS = {
    "team_coin":     0.30,
    "low_vol_20d":   0.25,
    "cgo_simple":    0.20,
    "enhanced_mom_60": 0.15,
    "bp":            0.10,
}


# ══════════════════════════════════════════════════════════════════
# 1. 数据加载
# ══════════════════════════════════════════════════════════════════

def load_all_data():
    print("=" * 60)
    print("[1/5] 加载数据（close / open / turnover / pb）...")
    t0 = time.time()
    symbols = get_all_symbols()

    close    = load_price_wide(symbols, WARMUP_START, OOS_END, field="close")
    open_p   = load_price_wide(symbols, WARMUP_START, OOS_END, field="open")
    turnover = load_price_wide(symbols, WARMUP_START, OOS_END, field="turnover")

    # 只保留 close 有效的股票（open/turnover 对齐）
    valid_syms = close.columns[close.notna().sum() > 500]
    close    = close[valid_syms]
    open_p   = open_p.reindex(columns=valid_syms)
    turnover = turnover.reindex(columns=valid_syms)

    # PB 宽表（直接从本地 CSV 加载，字段 "pb" = 市净率）
    pb = load_price_wide(symbols, WARMUP_START, OOS_END, field="pb").reindex(
        index=close.index, columns=valid_syms
    )

    # HS300 基准
    hs300 = None
    try:
        idx = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
        hs300 = idx["close"].reindex(close.index)
    except Exception as e:
        print(f"  HS300 不可用: {e}")

    tradable = apply_tradability_filter(close)

    print(f"  股票数: {len(valid_syms)} | 交易日: {len(close)} | 耗时: {time.time()-t0:.1f}s")
    return close, open_p, turnover, pb, hs300, tradable


# ══════════════════════════════════════════════════════════════════
# 2. 因子构建
# ══════════════════════════════════════════════════════════════════

def build_six_factors(close, open_p, turnover, pb, window=ROGT_WINDOW):
    """构建 v7 5因子 + ROGT，返回两个 dict（raw, 中性化）"""
    print(f"\n[2/5] 构建 6 因子（ROGT window={window}）...")
    factors = {
        "team_coin":      _team_coin(close),
        "low_vol_20d":    _low_vol_20d(close),
        "cgo_simple":     -(close / close.rolling(60).mean() - 1),
        "enhanced_mom_60": enhanced_momentum(close, window=60),
        "bp":             bp_factor(pb).reindex_like(close),
        "rogt":           retail_open_trap(close, open_p, turnover, window=window),
    }
    symbols = list(close.columns)
    industry_df = get_industry_classification(symbols=symbols, use_cache=True)
    neutral = {
        name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
        for name, fac in factors.items()
    }
    print(f"  行业覆盖: {len(industry_df)} 只")
    return factors, neutral, industry_df


# ══════════════════════════════════════════════════════════════════
# 3. IS 组合对比
# ══════════════════════════════════════════════════════════════════

def calc_metrics(ret):
    if ret is None or len(ret) == 0:
        return {}
    return {
        "ann":    annualized_return(ret),
        "vol":    annualized_volatility(ret),
        "sr":     sharpe_ratio(ret),
        "mdd":    max_drawdown(ret),
        "calmar": calmar_ratio(ret),
        "wr":     win_rate(ret),
    }


def run_is_comparison(close, neutral, tradable, hs300):
    """对比 v7(5因子) vs v7+ROGT(6因子) IS 表现"""
    print("\n[3/5] IS 组合对比...")

    regime_mask = None
    if hs300 is not None:
        try:
            hs300_full = get_index_history(symbol="sh000300", start=WARMUP_START, end=OOS_END)
            r = rsrs_regime_mask(hs300_full["high"], hs300_full["low"])
            l = llt_timing(hs300_full["close"])
            h = higher_moment_timing(hs300_full["close"], order=5)
            c = r.index.intersection(l.index).intersection(h.index)
            vote = r.loc[c].astype(int) + l.loc[c].astype(int) + h.loc[c].astype(int)
            regime_mask = vote >= 2
        except Exception as e:
            print(f"  择时不可用: {e}")

    # v7 (5因子，不含 rogt)
    weights_5 = {k: v for k, v in V7_WEIGHTS.items()}
    neutral_5 = {k: v for k, v in neutral.items() if k != "rogt"}

    ret_v7 = run_backtest(
        close, neutral_5, weights_5, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, regime_mask=regime_mask, lag1=True,
    )

    # v7+ROGT (6因子，IC加权方式直接用 ICIR 比例给 ROGT)
    fwd = close.pct_change(5).shift(-5)
    rogt_ic = compute_ic_series(
        neutral["rogt"].loc[IS_START:IS_END],
        fwd.loc[IS_START:IS_END],
        method="spearman", min_stocks=50,
    )
    rogt_icir = abs(ic_summary(rogt_ic)["ICIR"])

    # 给 ROGT 与其他因子等比例的 ICIR 权重（scale 到 10% ~ 20%）
    # 简单做法：按 ICIR 比例，ROGT 约占全部 ICIR 总和的一份
    base_icirs = {
        "team_coin": 0.3,
        "low_vol_20d": 0.25,
        "cgo_simple": 0.18,
        "enhanced_mom_60": 0.12,
        "bp": 0.08,
    }
    all_icirs = {**base_icirs, "rogt": rogt_icir}
    total = sum(all_icirs.values())
    weights_6 = {k: v / total for k, v in all_icirs.items()}

    ret_v8 = run_backtest(
        close, neutral, weights_6, n_stocks=N_STOCKS, cost=COST,
        mask=tradable, regime_mask=regime_mask, lag1=True,
    )

    results = {}
    for label, ret in [("v7_5factor", ret_v7), ("v7_plus_rogt_6factor", ret_v8)]:
        is_ret  = ret.loc[IS_START:IS_END]
        oos_ret = ret.loc[OOS_START:OOS_END]
        results[label] = {
            "is":  calc_metrics(is_ret),
            "oos": calc_metrics(oos_ret) if len(oos_ret) > 20 else {},
        }
        m = results[label]["is"]
        print(f"  {label} IS: 年化={m.get('ann',0):+.2%} 夏普={m.get('sr',0):.4f} 回撤={m.get('mdd',0):.2%}")

    return results, regime_mask, weights_6


# ══════════════════════════════════════════════════════════════════
# 4. Walk-Forward (6因子)
# ══════════════════════════════════════════════════════════════════

def run_walk_forward_6factor(close, open_p, turnover, pb, tradable, regime_mask):
    """v7+ROGT 6因子 Walk-Forward（train=3y, test=6m）"""
    print("\n[4/5] Walk-Forward 验证（6因子 + ROGT）...")

    symbols = list(close.columns)
    pb_full = pb.reindex(index=close.index, columns=symbols)

    def wf_fn(price_slice, _fdata, train_start, train_end, test_start, test_end):
        # 用 price_slice 的时间范围从全量数据中切片
        open_slice   = open_p.reindex(index=price_slice.index, columns=price_slice.columns)
        turn_slice   = turnover.reindex(index=price_slice.index, columns=price_slice.columns)
        pb_slice     = pb_full.reindex(index=price_slice.index, columns=price_slice.columns)

        # 构建 6 因子（全窗口）
        local_factors = {
            "team_coin":      _team_coin(price_slice),
            "low_vol_20d":    _low_vol_20d(price_slice),
            "cgo_simple":     -(price_slice / price_slice.rolling(60).mean() - 1),
            "enhanced_mom_60": enhanced_momentum(price_slice, window=60),
            "rogt":           retail_open_trap(price_slice, open_slice, turn_slice, window=ROGT_WINDOW),
        }
        try:
            local_factors["bp"] = bp_factor(pb_slice).reindex_like(price_slice)
        except Exception:
            pass

        # 行业中性化
        industry_df = get_industry_classification(symbols=symbols, use_cache=True)
        neutral_factors = {
            name: neutralize_factor_by_industry(fac, industry_df, show_progress=False)
            for name, fac in local_factors.items()
        }

        # IC 加权权重（训练期）
        local_fwd = price_slice.pct_change(5).shift(-5)
        local_fwd_train = local_fwd.loc[train_start:train_end]

        local_weights = {}
        for name, fac in neutral_factors.items():
            fac_train = fac.loc[train_start:train_end]
            ic_s = compute_ic_series(fac_train, local_fwd_train, method="spearman", min_stocks=50)
            if len(ic_s) > 10:
                m = ic_s.mean()
                if m > 0:
                    local_weights[name] = m

        if not local_weights:
            return pd.Series(dtype=float)

        total = sum(local_weights.values())
        local_weights = {k: v / total for k, v in local_weights.items()}

        wf_ret = run_backtest(
            price_slice, neutral_factors, local_weights, n_stocks=N_STOCKS,
            cost=COST, mask=None, regime_mask=regime_mask, lag1=True,
        )
        return wf_ret.loc[test_start:test_end] if len(wf_ret) > 0 else pd.Series(dtype=float)

    wf_summary = None
    wf_df = None
    try:
        wf_df = walk_forward_test(
            wf_fn, close.loc[WARMUP_START:IS_END], {},
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
        print(f"  夏普均值: {wf_summary['sharpe_mean']:.4f} | 中位数: {wf_summary['sharpe_median']:.4f}")
        print(f"  收益均值: {wf_summary['return_mean']:+.2%} | 胜率: {wf_summary['win_rate']:.0%}")
        print(f"  回撤均值: {wf_summary['mdd_mean']:.2%}")
    except Exception as e:
        print(f"  WF 失败: {e}")
        import traceback; traceback.print_exc()

    return wf_summary, wf_df


# ══════════════════════════════════════════════════════════════════
# 5. OOS 分层回测（单因子 ROGT，2024）
# ══════════════════════════════════════════════════════════════════

def run_oos_quintile(close, open_p, turnover):
    """在 OOS（2024）期验证 ROGT 分层单调性"""
    print("\n[5a] OOS 分层回测（ROGT，2024）...")
    factor_wide = retail_open_trap(close, open_p, turnover, window=ROGT_WINDOW)
    ret_wide    = close.pct_change().shift(-1)

    f_oos = factor_wide.loc[OOS_START:OOS_END]
    r_oos = ret_wide.loc[OOS_START:OOS_END]

    try:
        quintile_stats, ls_ret = quintile_backtest(f_oos, r_oos, n_groups=5)
        ann_ls = ls_ret.mean() * 252
        sr_ls  = ls_ret.mean() / (ls_ret.std() + 1e-10) * np.sqrt(252)
        print(f"  多空年化: {ann_ls:.2%} | 多空夏普: {sr_ls:.4f}")
        for q, row in quintile_stats.iterrows():
            ann = row.get("annual_return", row.get("ann_return", float("nan")))
            print(f"  Q{q}: {ann:.2%}")
        return quintile_stats, ls_ret
    except Exception as e:
        print(f"  OOS 分层失败: {e}")
        import traceback; traceback.print_exc()
        return None, pd.Series(dtype=float)


# ══════════════════════════════════════════════════════════════════
# 6. 参数敏感性（window）
# ══════════════════════════════════════════════════════════════════

def run_param_sensitivity(close, open_p, turnover):
    """测试不同 window 对 IS IC 的影响"""
    print("\n[5b] 参数敏感性（window=10/15/20/25/30）...")
    ret_wide = close.pct_change().shift(-1)
    rows = []
    for w in [10, 15, 20, 25, 30]:
        fac = retail_open_trap(close, open_p, turnover, window=w)
        f_is = fac.loc[IS_START:IS_END]
        r_is = ret_wide.loc[IS_START:IS_END]
        ic_s = compute_ic_series(f_is, r_is, method="spearman", min_stocks=50)
        s = ic_summary(ic_s)
        rows.append({
            "window": w,
            "IC_mean": s["IC_mean"],
            "ICIR":    s["ICIR"],
            "t_stat":  s["t_stat"],
            "pct_pos": s["pct_pos"],
        })
        print(f"  window={w:2d}: IC={s['IC_mean']:.4f}  ICIR={s['ICIR']:.4f}  t={s['t_stat']:.2f}")
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════
# 7. 报告生成
# ══════════════════════════════════════════════════════════════════

def write_report(is_results, wf_summary, oos_quintile, param_df, weights_6):
    out = Path(__file__).parent.parent / "journal" / f"rogt_v8_validation_{date.today().strftime('%Y%m%d')}.md"

    lines = [
        f"# ROGT 策略级验证报告 — v7+ROGT 6因子 — {date.today()}",
        "",
        "## 1. IS 组合对比",
        "",
        "| 组合 | 年化 | 夏普 | 最大回撤 |",
        "| --- | ---: | ---: | ---: |",
    ]

    for label, res in is_results.items():
        m = res["is"]
        lines.append(
            f"| {label} | {m.get('ann',0):+.2%} | {m.get('sr',0):.4f} | {m.get('mdd',0):.2%} |"
        )

    lines += [
        "",
        "## 2. Walk-Forward 结果（6因子，train=3y, test=6m）",
        "",
    ]
    if wf_summary:
        lines += [
            f"| 窗口数 | 有效窗口 | 夏普均值 | **夏普中位数** | 收益均值 | 胜率 | 回撤均值 |",
            f"| --- | --- | --- | --- | --- | --- | --- |",
            f"| {wf_summary['windows']} | {wf_summary['valid']} "
            f"| {wf_summary['sharpe_mean']:.4f} | **{wf_summary['sharpe_median']:.4f}** "
            f"| {wf_summary['return_mean']:+.2%} | {wf_summary['win_rate']:.0%} "
            f"| {wf_summary['mdd_mean']:.2%} |",
            "",
        ]
        med = wf_summary['sharpe_median']
        if med > 0.3:
            verdict_wf = "✅ 中位数 > 0.3，WF 稳健"
        elif med > 0.0:
            verdict_wf = "⚠️ 中位数 > 0 但 < 0.3，踩线"
        else:
            verdict_wf = "❌ 中位数 ≤ 0，WF 不稳定"
        lines.append(f"**WF 判断**：{verdict_wf}")
    else:
        lines.append("WF 未能运行（见控制台输出）")

    lines += [
        "",
        "## 3. OOS 分层回测（ROGT 单因子，2024）",
        "",
    ]
    if oos_quintile is not None:
        lines += ["| 分位数 | 年化收益 |", "| --- | ---: |"]
        for q, row in oos_quintile.iterrows():
            ann = row.get("annual_return", row.get("ann_return", float("nan")))
            lines.append(f"| Q{q} | {ann:.2%} |")
    else:
        lines.append("OOS 分层未能运行")

    lines += [
        "",
        "## 4. 参数敏感性（window）",
        "",
        "| window | IC均值 | ICIR | t-stat | IC>0% |",
        "| --- | ---: | ---: | ---: | ---: |",
    ]
    for _, row in param_df.iterrows():
        lines.append(
            f"| {int(row['window'])} | {row['IC_mean']:.4f} | {row['ICIR']:.4f} "
            f"| {row['t_stat']:.2f} | {row['pct_pos']:.1%} |"
        )

    lines += [
        "",
        "## 5. v8 因子权重（ICIR比例）",
        "",
        "| 因子 | 权重 |",
        "| --- | ---: |",
    ]
    for k, v in weights_6.items():
        lines.append(f"| {k} | {v:.3f} |")

    lines += [
        "",
        "## 6. 最终裁定",
        "",
    ]

    # 综合判断
    v7_sr   = is_results["v7_5factor"]["is"].get("sr", 0)
    v8_sr   = is_results["v7_plus_rogt_6factor"]["is"].get("sr", 0)
    improve = v8_sr - v7_sr

    if wf_summary:
        med = wf_summary['sharpe_median']
        if med > 0.0 and improve > 0:
            verdict = f"**READY** — WF 中位数 {med:.4f} > 0，IS 夏普提升 {improve:+.4f}，ROGT 可正式纳入 v8。"
        elif med > 0.0:
            verdict = f"**CONDITIONAL** — WF 中位数 {med:.4f} > 0，但 IS 未提升（{improve:+.4f}），重新评估权重。"
        else:
            verdict = f"**DEFER** — WF 中位数 {med:.4f} ≤ 0，6因子 WF 不稳定，ROGT 加入不能改善策略健壮性。"
    else:
        verdict = "**INCONCLUSIVE** — WF 未能运行，无法给出最终裁定。"

    lines.append(verdict)
    lines += ["", f"数据来源：外盘数据 `/Volumes/Crucial X10/20260320/`，IS {IS_START}~{IS_END}，OOS {OOS_START}~{OOS_END}"]

    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n报告已写入: {out}")
    return out


# ══════════════════════════════════════════════════════════════════
# Main
# ══════════════════════════════════════════════════════════════════

def main():
    t_total = time.time()

    close, open_p, turnover, pb, hs300, tradable = load_all_data()
    factors, neutral, industry_df = build_six_factors(close, open_p, turnover, pb)

    is_results, regime_mask, weights_6 = run_is_comparison(close, neutral, tradable, hs300)
    wf_summary, wf_df = run_walk_forward_6factor(close, open_p, turnover, pb, tradable, regime_mask)
    oos_quintile, oos_ls = run_oos_quintile(close, open_p, turnover)
    param_df = run_param_sensitivity(close, open_p, turnover)

    report_path = write_report(is_results, wf_summary, oos_quintile, param_df, weights_6)

    print(f"\n完成，总耗时 {(time.time()-t_total)/60:.1f} 分钟")
    print(f"报告：{report_path}")


if __name__ == "__main__":
    main()
