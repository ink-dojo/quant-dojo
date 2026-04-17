"""
v25 2022 亏损诊断 — 找 2022 sharpe=-0.84 / ann=-12.9% 的根因。

三个假设:
  H1: regime indicator 失灵 — HS300<MA120 在 2022 熊市里没及时识别, 导致止损不触发
  H2: regime 触发了但 v16 底层因子本身在熊市方向反转 — 减仓无法阻止亏损
  H3: 50% 半仓减幅不够 — 即使正确识别熊市, 半仓仍承担了全亏

诊断步骤:
  1. 把 fresh v25 equity 按 HS300 regime 切成 bull/bear 两段, 分别算统计
  2. 同步对 v16 equity (cached 或 fresh) 做同样切分, 对比 v25 overlay 减掉了多少 DD
  3. 2022 逐日 flag: regime / v16 return / v25 return / 累计对比
  4. 结论: 应该升级 regime 还是换因子, 还是两者都需要

不调参! 只诊断。

输出 journal/v25_2022_postmortem_{date}.md
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from pipeline.strategy_registry import get_strategy
from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.metrics import (
    annualized_return, sharpe_ratio, max_drawdown, win_rate,
)
from utils.stop_loss import hs300_bear_regime

V25_MA = 120
V25_THR = -0.10
N_STOCKS = 30
WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"


def run_v16_fresh() -> pd.Series:
    """跑 fresh v16, 返回 daily portfolio return."""
    print("  (重跑 fresh v16 底层 — 需要几分钟)")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[valid]
    entry = get_strategy("multi_factor_v16")
    strat = entry.factory({"n_stocks": N_STOCKS})
    res = strat.run(price)
    col = "portfolio_return" if "portfolio_return" in res.columns else "returns"
    r = res[col].astype(float).loc[START:END]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def load_v25_fresh() -> pd.Series:
    """从 live/runs 取当天 fresh v25 equity。"""
    files = sorted(
        Path("live/runs").glob("multi_factor_v25_*_equity.csv"),
        key=lambda p: p.stat().st_mtime,
    )
    path = files[-1]
    df = pd.read_csv(path, parse_dates=["date"]).set_index("date")
    r = df["portfolio_return"].astype(float).loc[START:END]
    first_nz = r.ne(0).idxmax() if r.ne(0).any() else r.index[0]
    return r.loc[first_nz:]


def get_hs300_regime(dates: pd.DatetimeIndex) -> pd.Series:
    """按 v25 内部相同参数算 regime (不 shift 侵入, 与 overlay 一致)。"""
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")
    hs300_close = hs300["399300"].dropna()
    regime = hs300_bear_regime(hs300_close, ma_window=V25_MA, shift_days=1)
    return regime.reindex(dates).fillna(False).astype(bool)


def stats_block(r: pd.Series, label: str) -> dict:
    return {
        "label": label,
        "n_days": int(len(r)),
        "ann_return": float(annualized_return(r)) if len(r) > 0 else 0.0,
        "sharpe": float(sharpe_ratio(r)) if len(r) > 1 else 0.0,
        "max_drawdown": float(max_drawdown(r)) if len(r) > 0 else 0.0,
        "win_rate": float(win_rate(r)) if len(r) > 0 else 0.0,
        "cum_return": float((1 + r).prod() - 1) if len(r) > 0 else 0.0,
    }


def main():
    print("[1/5] 加载 v25 fresh equity…")
    v25 = load_v25_fresh()
    print(f"  v25 n={len(v25)} ({v25.index[0].date()} ~ {v25.index[-1].date()})")

    print("[2/5] 重跑 v16 fresh 同数据底层…")
    v16 = run_v16_fresh()
    common = v25.index.intersection(v16.index)
    v25, v16 = v25.loc[common], v16.loc[common]
    print(f"  对齐后 n={len(common)}")

    print("[3/5] 加载 HS300 regime flag…")
    regime = get_hs300_regime(common)
    bear_days = int(regime.sum())
    print(f"  熊市日: {bear_days}/{len(common)}  ({bear_days/len(common):.1%})")

    # 2022 子集
    m2022 = (v25.index.year == 2022)
    v25_2022 = v25[m2022]
    v16_2022 = v16[m2022]
    reg_2022 = regime[m2022]
    print(f"  2022 子集 n={len(v25_2022)} 熊市日 {int(reg_2022.sum())}/{len(reg_2022)}")

    # ───────── 分析 ─────────
    print("[4/5] 分段统计…")

    rows_full = [
        stats_block(v16, "v16 全期"),
        stats_block(v25, "v25 全期"),
        stats_block(v16[regime], "v16 (bear only, 全期)"),
        stats_block(v25[regime], "v25 (bear only, 全期)"),
        stats_block(v16[~regime], "v16 (bull only, 全期)"),
        stats_block(v25[~regime], "v25 (bull only, 全期)"),
    ]
    df_full = pd.DataFrame(rows_full)

    rows_2022 = [
        stats_block(v16_2022, "v16 2022"),
        stats_block(v25_2022, "v25 2022"),
        stats_block(v16_2022[reg_2022], "v16 2022 (bear)"),
        stats_block(v25_2022[reg_2022], "v25 2022 (bear)"),
        stats_block(v16_2022[~reg_2022], "v16 2022 (bull)"),
        stats_block(v25_2022[~reg_2022], "v25 2022 (bull)"),
    ]
    df_2022 = pd.DataFrame(rows_2022)

    # overlay 减免 DD 的定量
    overlay_diff = (v25 - v16).rename("overlay_impact")
    od_2022 = overlay_diff[m2022]
    od_bear = overlay_diff[regime]
    od_bull = overlay_diff[~regime]

    # ── H1/H2/H3 判定 ──────────────────────────────
    h1 = {
        "bear_days_2022": int(reg_2022.sum()),
        "trading_days_2022": len(reg_2022),
        "bear_coverage_2022": float(reg_2022.mean()),
    }
    h2 = {
        "v16_2022_ann": float(annualized_return(v16_2022)),
        "v16_2022_bear_ann": float(annualized_return(v16_2022[reg_2022])) if reg_2022.any() else None,
        "v16_2022_bull_ann": float(annualized_return(v16_2022[~reg_2022])) if (~reg_2022).any() else None,
        "v16_bear_mean_daily": float(v16[regime].mean()),
        "v16_bull_mean_daily": float(v16[~regime].mean()),
    }
    h3 = {
        "overlay_mean_in_bear": float(od_bear.mean()),
        "overlay_mean_in_bull": float(od_bull.mean()),
        "overlay_total_impact_2022": float(od_2022.sum()),
        "overlay_total_impact_full": float(overlay_diff.sum()),
    }

    # ───── markdown 输出 ─────
    print("[5/5] 写 markdown 报告…")
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# v25 2022 亏损诊断 — {today}")
    lines.append("")
    lines.append(f"> 数据: v25 fresh run {v25.index[0].date()} ~ {v25.index[-1].date()}, n={len(v25)}")
    lines.append(f"> regime: HS300<MA{V25_MA} shift(1), 全期熊市覆盖率 {regime.mean():.1%}")
    lines.append("")
    lines.append("## 1. 全期 vs 熊市/牛市 分段")
    lines.append("")
    lines.append(df_full.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")
    lines.append("## 2. 2022 年逐 regime 分段")
    lines.append("")
    lines.append(df_2022.to_markdown(index=False, floatfmt=".4f"))
    lines.append("")

    lines.append("## 3. 假设判定")
    lines.append("")
    lines.append("### H1: regime 指标失灵")
    lines.append(f"- 2022 交易日: {h1['trading_days_2022']}")
    lines.append(f"- 其中 HS300<MA120 熊市日: {h1['bear_days_2022']} ({h1['bear_coverage_2022']:.1%})")
    if h1["bear_coverage_2022"] < 0.3:
        lines.append("- **判定**: regime 覆盖 <30%, 止损很少触发 → H1 部分成立")
    elif h1["bear_coverage_2022"] > 0.7:
        lines.append("- **判定**: regime 覆盖 >70%, 止损大部分时间在运行 → H1 不成立, 问题在 H2/H3")
    else:
        lines.append(f"- **判定**: regime 覆盖 ~50%, 中等触发")
    lines.append("")

    lines.append("### H2: v16 底层因子在熊市方向反转")
    lines.append(f"- v16 全期熊市日均: {h2['v16_bear_mean_daily']*10000:.2f} bp/day")
    lines.append(f"- v16 全期牛市日均: {h2['v16_bull_mean_daily']*10000:.2f} bp/day")
    lines.append(f"- v16 2022 年化: {h2['v16_2022_ann']:.2%}")
    if h2["v16_2022_bear_ann"] is not None:
        lines.append(f"- v16 2022 熊市段年化: {h2['v16_2022_bear_ann']:.2%}")
    if h2["v16_2022_bull_ann"] is not None:
        lines.append(f"- v16 2022 牛市段年化: {h2['v16_2022_bull_ann']:.2%}")
    if h2["v16_bear_mean_daily"] < 0 and h2["v16_bull_mean_daily"] > 0:
        lines.append("- **判定**: v16 因子在熊市段平均亏损, 牛市段盈利 → H2 成立, 因子存在 regime dependence")
    elif h2["v16_bear_mean_daily"] > 0:
        lines.append("- **判定**: v16 因子在熊市段仍平均盈利 → H2 不成立")
    else:
        lines.append("- **判定**: 结果不典型, 需要更细粒度分析")
    lines.append("")

    lines.append("### H3: 半仓减幅不够")
    lines.append(f"- overlay 平均减免 (bear): {h3['overlay_mean_in_bear']*10000:+.2f} bp/day")
    lines.append(f"- overlay 平均减免 (bull): {h3['overlay_mean_in_bull']*10000:+.2f} bp/day (应该≈0)")
    lines.append(f"- overlay 2022 全年影响: {h3['overlay_total_impact_2022']*100:+.2f}% (累加)")
    lines.append(f"- overlay 全期影响: {h3['overlay_total_impact_full']*100:+.2f}% (累加)")
    if h3["overlay_mean_in_bear"] > 0 and abs(h3["overlay_total_impact_2022"]) < 0.05:
        lines.append("- **判定**: overlay 在熊市减免有限 (<5% 年度冲击) → 减仓幅度不够, H3 部分成立")
    lines.append("")

    lines.append("## 4. 不抄近道的下一步")
    lines.append("")
    lines.append("基于诊断, 合规的研究方向（不是调 threshold/ma 参数）:")
    lines.append("")
    lines.append("1. **因子替换 / 扩展**: 找熊市段仍正 IC 的因子（低波、红利、质量类），")
    lines.append("   用 regime-conditional IC 筛选后加入或替换 v16 的弱因子。")
    lines.append("2. **Regime 指标升级**: HS300 MA120 是经典但滞后；考虑 credit spread、")
    lines.append("   A 股隐含波动率 (若有)、或成分股广度 (A/D line) 作为更早期 regime 信号。")
    lines.append("3. **Dynamic hedge**: 熊市段开 ETF 空头对冲 (非止损减仓), 保留 alpha 暴露。")
    lines.append("4. **拒绝参数微调**: sweep 里 threshold=-0.05 看似更好, 但分年检验同样会暴露")
    lines.append("   2022 regime risk。调参只是 reshuffle 历史噪声, 不改变根本问题。")
    lines.append("")
    lines.append("每条路径都需要在独立 OOS 样本上验证后才算数，DSR 和 PSR 同步跟踪。")
    lines.append("")

    out_md = Path(f"journal/v25_2022_postmortem_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    # 终端摘要
    print("\n=== 关键事实 ===")
    print(f"  2022 regime 覆盖: {h1['bear_coverage_2022']:.1%}  ({h1['bear_days_2022']} days)")
    print(f"  v16 熊市日均 vs 牛市日均: {h2['v16_bear_mean_daily']*10000:+.2f} vs {h2['v16_bull_mean_daily']*10000:+.2f} bp/day")
    print(f"  v25 overlay 2022 年度冲击: {h3['overlay_total_impact_2022']*100:+.2f}%")
    print(f"  v16 2022 ann: {h2['v16_2022_ann']:.2%}   v25 2022 ann: {annualized_return(v25_2022):.2%}")


if __name__ == "__main__":
    main()
