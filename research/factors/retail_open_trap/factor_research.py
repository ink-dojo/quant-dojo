"""
散户开盘追涨陷阱因子 (Retail Open Gap Trap, ROGT) — 完整研究验证脚本

运行方式：
    cd /Users/karan/work/quant-dojo
    python research/factors/retail_open_trap/factor_research.py

输出：
    - IC/ICIR/t-stat 统计量
    - 分层回测（5分组多空收益）
    - 因子衰减曲线（1~20日持仓）
    - 与现有因子的相关系数
    - Markdown 研究报告 → research/factors/retail_open_trap/report.md
"""
import sys
from pathlib import Path

# ── 项目根路径 ────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import warnings
import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from utils.local_data_loader import load_price_wide, get_all_symbols
from utils.factor_analysis import (
    compute_ic_series,
    ic_summary,
    quintile_backtest,
    factor_decay_analysis,
    winsorize,
    industry_neutralize_fast,
)
from utils.alpha_factors import (
    retail_open_trap,
    reversal_1m,
    turnover_rev,
    cgo,
)

# ══════════════════════════════════════════════════════════════
# 参数配置
# ══════════════════════════════════════════════════════════════
IS_START     = "2015-01-01"
IS_END       = "2024-12-31"
WARMUP_START = "2013-01-01"   # 因子预热期（不计入 IC 统计）
N_STOCKS_MIN = 200            # 每日截面最少股票数（不足则跳过）
WINDOW       = 20             # 因子滚动窗口（交易日）
GAP_THR      = 0.01           # 最小有效跳空阈值（1%）


def load_data(symbols):
    """加载价格、开盘价、换手率宽表"""
    print(f"[数据] 加载 {len(symbols)} 只股票，区间 {WARMUP_START} ~ {IS_END}...")

    close    = load_price_wide(symbols, WARMUP_START, IS_END, field="close")
    open_p   = load_price_wide(symbols, WARMUP_START, IS_END, field="open")
    turnover = load_price_wide(symbols, WARMUP_START, IS_END, field="turnover")
    volume   = load_price_wide(symbols, WARMUP_START, IS_END, field="volume")
    is_st    = load_price_wide(symbols, WARMUP_START, IS_END, field="is_st")

    print(f"  close shape: {close.shape}")
    print(f"  日期范围: {close.index[0].date()} ~ {close.index[-1].date()}")
    print(f"  非空率: {close.notna().mean().mean():.1%}")
    return close, open_p, turnover, volume, is_st


def apply_filters(close, is_st, min_price=2.0, min_listing_days=60):
    """剔除 ST、仙股、次新股，返回有效股票掩码"""
    # ST 掩码
    st_mask = is_st.fillna(0).astype(bool)

    # 仙股掩码（价格 < 2 元）
    low_price_mask = close < min_price

    # 次新股掩码（上市不足 60 日，用第一个非 NaN 日期判断）
    first_valid = close.apply(lambda col: col.first_valid_index())
    listing_dates = pd.Series(first_valid, index=close.columns)
    new_stock_mask = pd.DataFrame(
        index=close.index, columns=close.columns, dtype=bool
    )
    for col in close.columns:
        cutoff = listing_dates[col]
        if cutoff is None:
            new_stock_mask[col] = True
        else:
            days_listed = (close.index - cutoff).days
            new_stock_mask[col] = days_listed < min_listing_days

    valid_mask = ~(st_mask | low_price_mask | new_stock_mask)
    return valid_mask


def run_ic_analysis(factor_wide, ret_wide, valid_mask, label="ROGT"):
    """IC / ICIR / t-stat 分析"""
    # 应用有效股票掩码
    f = factor_wide.where(valid_mask)
    r = ret_wide.where(valid_mask)

    # 只取 IS 区间
    f = f.loc[IS_START:IS_END]
    r = r.loc[IS_START:IS_END]

    # 每日截面有效股票数过滤
    valid_counts = f.notna().sum(axis=1)
    valid_dates = valid_counts[valid_counts >= N_STOCKS_MIN].index
    f = f.loc[valid_dates]
    r = r.loc[valid_dates]

    ic_series = compute_ic_series(f, r, method="spearman", min_stocks=N_STOCKS_MIN)
    stats = ic_summary(ic_series, name=label)
    return ic_series, stats


def run_market_state_analysis(ic_series, close):
    """按牛熊震荡市分组统计 IC"""
    # 用沪深300代理市场状态（用全体股票均值代替）
    market_ret = close.mean(axis=1).pct_change().loc[IS_START:IS_END]
    market_ret_6m = market_ret.rolling(126).sum()

    state = pd.cut(
        market_ret_6m,
        bins=[-np.inf, -0.10, 0.10, np.inf],
        labels=["熊市(<-10%)", "震荡(-10%~10%)", "牛市(>10%)"]
    )

    results = {}
    for s in state.cat.categories:
        dates = state[state == s].index
        ic_sub = ic_series.reindex(dates).dropna()
        if len(ic_sub) < 20:
            continue
        results[s] = {
            "日数": len(ic_sub),
            "IC均值": ic_sub.mean(),
            "ICIR": ic_sub.mean() / ic_sub.std() if ic_sub.std() > 0 else np.nan,
            "IC>0占比": (ic_sub > 0).mean(),
        }
    return pd.DataFrame(results).T


def run_factor_correlation(factor_wide, close, turnover, valid_mask):
    """与主要现有因子的截面相关系数"""
    f_rogt = factor_wide.where(valid_mask).loc[IS_START:IS_END]

    # 现有因子
    ret_wide = close.pct_change().shift(-1)
    f_rev    = reversal_1m(close).where(valid_mask).loc[IS_START:IS_END]
    f_tvr    = turnover_rev(close).where(valid_mask).loc[IS_START:IS_END]
    f_cgo    = cgo(close, turnover).where(valid_mask).loc[IS_START:IS_END]

    # 每日截面相关系数均值
    common_dates = f_rogt.dropna(how="all").index
    corrs = {}
    for name, f_other in [("reversal_1m", f_rev), ("turnover_rev", f_tvr), ("cgo", f_cgo)]:
        daily_corr = []
        for d in common_dates[:252]:  # 用第一年估算
            row_rogt  = f_rogt.loc[d].dropna()
            row_other = f_other.loc[d].reindex(row_rogt.index).dropna()
            common = row_rogt.index.intersection(row_other.index)
            if len(common) < 50:
                continue
            c = row_rogt[common].corr(row_other[common], method="spearman")
            daily_corr.append(c)
        corrs[name] = np.nanmean(daily_corr) if daily_corr else np.nan

    return corrs


def format_report(stats, quintile_stats, ls_ret, decay_results,
                  state_ic, corrs, ic_series):
    """生成 Markdown 研究报告"""

    ann_ls = ls_ret.mean() * 252
    sharpe_ls = ls_ret.mean() / ls_ret.std() * np.sqrt(252) if ls_ret.std() > 0 else np.nan
    max_dd = (ls_ret.cumsum() - ls_ret.cumsum().cummax()).min()

    lines = [
        "# 散户开盘追涨陷阱因子（ROGT）研究报告",
        "",
        f"> 生成日期：{pd.Timestamp.now().strftime('%Y-%m-%d')}  ",
        f"> 研究区间：{IS_START} ~ {IS_END}（IS，共 {ic_series.notna().sum()} 个截面日）  ",
        f"> 因子代码：`retail_open_trap` in `utils/alpha_factors.py`",
        "",
        "---",
        "",
        "## 1. 因子逻辑",
        "",
        "**A 股散户心理机制**：",
        "- 散户收盘后刷微信群/股吧接收推荐，带着「明天会大涨」的预期",
        "- 9:30 集合竞价集中追涨 → 股价跳空高开",
        "- 机构利用散户热情在高位出货（分销）",
        "- 当天高开低走，收盘价回落至开盘下方",
        "- 被套散户形成持续抛压，未来收益偏负",
        "",
        "**信号三要素（同时满足才计分）**：",
        "1. `gap > 1%`：显著正跳空（过滤微小噪音）",
        "2. `close < open`：当日从开盘价下跌（高开低走）",
        "3. `turnover > 均值`：成交放量（确认散户参与度）",
        "",
        "**因子方向**：正向（高值 = 近期少陷阱 = 走势干净 = 预期超额收益高）",
        "",
        "---",
        "",
        "## 2. IC / ICIR 统计",
        "",
        "| 指标 | 值 |",
        "|------|----|",
        f"| IC 均值 | {stats.get('IC_mean', float('nan')):.4f} |",
        f"| IC 标准差 | {stats.get('IC_std', float('nan')):.4f} |",
        f"| ICIR | {stats.get('ICIR', float('nan')):.4f} |",
        f"| IC>0 占比 | {stats.get('pct_pos', float('nan')):.1%} |",
        f"| t-stat | {stats.get('t_stat', float('nan')):.2f} |",
        "",
        "> IC>0.02 且 ICIR>0.2 且 |t-stat|>2 视为有效因子",
        "",
        "---",
        "",
        "## 3. 多空组合表现（5 分组）",
        "",
        "| 指标 | 值 |",
        "|------|----|",
        f"| 多空年化收益 | {ann_ls:.2%} |",
        f"| 多空夏普 | {sharpe_ls:.4f} |",
        f"| 多空最大回撤 | {max_dd:.2%} |",
        "",
    ]

    # 分层收益表
    if quintile_stats is not None and not quintile_stats.empty:
        lines += ["**各分组年化收益**：", ""]
        lines += ["| 分组 | 年化收益 |", "|------|---------|"]
        for g in quintile_stats.columns:
            ann = quintile_stats[g].mean() * 252
            lines.append(f"| {g} | {ann:.2%} |")
        lines.append("")

    lines += [
        "---",
        "",
        "## 4. 市场状态分层 IC",
        "",
    ]

    if state_ic is not None and not state_ic.empty:
        lines += ["| 市场状态 | 日数 | IC均值 | ICIR | IC>0占比 |",
                  "|---------|------|--------|------|---------|"]
        for idx, row in state_ic.iterrows():
            lines.append(
                f"| {idx} | {int(row.get('日数', 0))} "
                f"| {row.get('IC均值', float('nan')):.4f} "
                f"| {row.get('ICIR', float('nan')):.4f} "
                f"| {row.get('IC>0占比', float('nan')):.1%} |"
            )
        lines.append("")

    lines += [
        "---",
        "",
        "## 5. 与现有因子相关性（截面 Rank 相关）",
        "",
        "| 因子 | 相关系数 | 解释 |",
        "|------|---------|------|",
    ]
    for fname, corr in corrs.items():
        level = "低" if abs(corr) < 0.3 else "中" if abs(corr) < 0.6 else "高"
        lines.append(f"| {fname} | {corr:.3f} | 相关性{level} |")
    lines += [
        "",
        "> |r| < 0.3 说明因子提供独立 alpha 信息",
        "",
        "---",
        "",
        "## 6. 因子衰减",
        "",
    ]

    if decay_results:
        half_life = decay_results.get("half_life_days")
        recommended = decay_results.get("recommended_holding_days")
        lines += [
            f"- **半衰期**：{half_life} 天",
            f"- **推荐持仓周期**：{recommended} 天",
            "",
        ]

    lines += [
        "---",
        "",
        "## 7. 结论与建议",
        "",
    ]

    ic_mean = stats.get("IC_mean", 0)
    icir    = stats.get("ICIR", 0)
    t_stat  = stats.get("t_stat", 0)

    if abs(ic_mean) > 0.02 and abs(icir) > 0.2 and abs(t_stat) > 2:
        conclusion = "✅ **因子有效**：IC/ICIR/t-stat 全部通过门槛，建议纳入候选因子池。"
    elif abs(ic_mean) > 0.015 and abs(icir) > 0.15:
        conclusion = "⚠️ **因子边缘有效**：指标接近门槛，建议进一步优化参数或结合其他因子。"
    else:
        conclusion = "❌ **因子不显著**：当前参数下未通过门槛，需要重新设计或放弃。"

    lines += [
        conclusion,
        "",
        "**后续研究方向**：",
        "- 参数敏感性：`gap_threshold` 在 0.5%~3% 区间，`window` 在 10~40 天",
        "- 行业中性化后 IC 是否改善",
        "- 与 `reversal_1m` 组合，看多空收益是否叠加",
        "- 分析哪些行业/市值段因子效果更强",
        "",
        "---",
        "",
        "_报告由 `research/factors/retail_open_trap/factor_research.py` 自动生成_",
    ]

    return "\n".join(lines)


def main():
    print("=" * 60)
    print("散户开盘追涨陷阱因子 (ROGT) — 研究验证")
    print("=" * 60)

    # ── 1. 加载数据 ───────────────────────────────────────────
    symbols = get_all_symbols()
    print(f"[数据] 股票池：{len(symbols)} 只")

    close, open_p, turnover, volume, is_st = load_data(symbols)

    # ── 2. 计算因子 ───────────────────────────────────────────
    print("\n[因子] 计算 retail_open_trap ...")
    factor_wide = retail_open_trap(
        close=close,
        open_price=open_p,
        turnover=turnover,
        window=WINDOW,
        gap_threshold=GAP_THR,
    )
    print(f"  因子非空率（IS期）: {factor_wide.loc[IS_START:IS_END].notna().mean().mean():.1%}")
    print(f"  因子均值: {factor_wide.loc[IS_START:IS_END].stack().mean():.6f}")
    print(f"  因子标准差: {factor_wide.loc[IS_START:IS_END].stack().std():.6f}")

    # ── 3. 有效掩码 ───────────────────────────────────────────
    print("\n[过滤] 剔除 ST / 仙股 / 次新股...")
    valid_mask = apply_filters(close, is_st)
    valid_count_is = valid_mask.loc[IS_START:IS_END].sum(axis=1).mean()
    print(f"  IS 期日均有效股票数：{valid_count_is:.0f}")

    # ── 4. 次日收益 ───────────────────────────────────────────
    ret_wide = close.pct_change().shift(-1)

    # ── 5. IC 分析 ────────────────────────────────────────────
    print("\n[IC] 计算 Rank IC...")
    ic_series, stats = run_ic_analysis(factor_wide, ret_wide, valid_mask)
    print(f"  IC 均值  : {stats['IC_mean']:.4f}")
    print(f"  ICIR     : {stats['ICIR']:.4f}")
    print(f"  t-stat   : {stats['t_stat']:.2f}")
    print(f"  IC>0占比 : {stats['pct_pos']:.1%}")

    # ── 6. 分层回测 ───────────────────────────────────────────
    print("\n[分层] 5 分组回测（IS 期）...")
    f_is = factor_wide.where(valid_mask).loc[IS_START:IS_END]
    r_is = ret_wide.where(valid_mask).loc[IS_START:IS_END]
    try:
        quintile_stats, ls_ret = quintile_backtest(f_is, r_is, n_groups=5)
        ann_ls = ls_ret.mean() * 252
        sr_ls  = ls_ret.mean() / ls_ret.std() * np.sqrt(252)
        print(f"  多空年化: {ann_ls:.2%} | 多空夏普: {sr_ls:.4f}")
    except Exception as e:
        print(f"  分层回测失败: {e}")
        quintile_stats, ls_ret = None, pd.Series(dtype=float)

    # ── 7. 衰减分析 ───────────────────────────────────────────
    print("\n[衰减] 因子衰减分析（1~20日）...")
    try:
        decay_results = factor_decay_analysis(
            f_is, r_is, max_lag=20, smooth=True
        )
        print(f"  半衰期: {decay_results.get('half_life_days')} 天")
        print(f"  推荐持仓: {decay_results.get('recommended_holding_days')} 天")
    except Exception as e:
        print(f"  衰减分析失败: {e}")
        decay_results = {}

    # ── 8. 市场状态分层 ──────────────────────────────────────
    print("\n[状态] 牛/熊/震荡市 IC 分层...")
    try:
        state_ic = run_market_state_analysis(ic_series, close)
        print(state_ic.to_string())
    except Exception as e:
        print(f"  市场状态分析失败: {e}")
        state_ic = pd.DataFrame()

    # ── 9. 因子相关性 ─────────────────────────────────────────
    print("\n[相关] 与现有因子的截面相关系数...")
    try:
        corrs = run_factor_correlation(factor_wide, close, turnover, valid_mask)
        for k, v in corrs.items():
            print(f"  ROGT vs {k}: {v:.3f}")
    except Exception as e:
        print(f"  相关性分析失败: {e}")
        corrs = {}

    # ── 10. 生成报告 ──────────────────────────────────────────
    print("\n[报告] 生成 Markdown 报告...")
    report_md = format_report(
        stats=stats,
        quintile_stats=quintile_stats,
        ls_ret=ls_ret,
        decay_results=decay_results,
        state_ic=state_ic,
        corrs=corrs,
        ic_series=ic_series,
    )

    out_dir = Path(__file__).parent
    out_dir.mkdir(parents=True, exist_ok=True)
    report_path = out_dir / "report.md"
    report_path.write_text(report_md, encoding="utf-8")
    print(f"  报告已写入: {report_path}")

    # ── 11. 打印最终判断 ──────────────────────────────────────
    print("\n" + "=" * 60)
    ic_mean = stats.get("IC_mean", 0)
    icir    = stats.get("ICIR", 0)
    t_stat  = stats.get("t_stat", 0)

    if abs(ic_mean) > 0.02 and abs(icir) > 0.2 and abs(t_stat) > 2:
        verdict = "✅ 因子有效 — 通过 IC/ICIR/t-stat 三项门槛"
    elif abs(ic_mean) > 0.015 and abs(icir) > 0.15:
        verdict = "⚠️ 因子边缘有效 — 建议调参后再评估"
    else:
        verdict = "❌ 因子不显著 — 需重新设计"
    print(f"最终判断：{verdict}")
    print("=" * 60)

    return stats, ic_series


if __name__ == "__main__":
    main()
