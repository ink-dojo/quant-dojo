"""
Market breadth regime 指标研究 (纯 regime 质量分析, 不跑策略过门测试)。

动机 (来自 v27_half audit 合规路径 2):
  HS300 MA120 regime 以大盘股为基础, 对 2022 年小盘暴跌反应滞后;
  若独立指标 (breadth) 能更早识别 bear, 是合规升级方向 (而非微调 MA 窗口)。

预注册设计 (先定义再看数据, 不调参):
  breadth_t = (rising_t - falling_t) / (rising_t + falling_t)
  rising_t  = #{stocks: daily_ret > 0 at t}
  falling_t = #{stocks: daily_ret < 0 at t}
  smoothed = breadth.rolling(20).mean()
  bear_breadth = (smoothed < 0).shift(1)   # 20 日平滑<0, shift(1) 避免偷看

  (该规则用最简单的 1 个自由参数: window=20, 对应月度水平)

比较维度 (不是过门测试, 是 regime 质量分析):
  1. 全期 coverage 差异 (bear 覆盖率)
  2. 2022 子集的 "首次进入 bear" 日期对比 — breadth 是否领先?
  3. 切换频次对比 (噪声程度)
  4. 两 regime 的 AND / OR / XOR 日历差异

输出: journal/breadth_regime_research_{date}.md (纯指标研究, 无策略 metric)
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import numpy as np
import pandas as pd

from utils.local_data_loader import get_all_symbols, load_price_wide
from utils.stop_loss import hs300_bear_regime

WARMUP = "2019-01-01"
START = "2022-01-01"
END = "2025-12-31"
BREADTH_WINDOW = 20  # 预注册: 月度水平
HS300_MA = 120


def compute_breadth(price: pd.DataFrame, window: int = 20) -> pd.Series:
    """每日 (上涨-下跌) / (上涨+下跌), 再 window 日平滑。"""
    ret = price.pct_change()
    rising = (ret > 0).sum(axis=1)
    falling = (ret < 0).sum(axis=1)
    total = rising + falling
    raw = (rising - falling) / total.where(total > 0, np.nan)
    return raw.rolling(window, min_periods=max(5, window // 2)).mean()


def first_bear_entry(regime: pd.Series) -> pd.Timestamp | None:
    mask = regime[regime].index
    return mask[0] if len(mask) > 0 else None


def switch_count(regime: pd.Series) -> int:
    """True↔False 切换次数。"""
    r = regime.astype(int)
    return int((r.diff().fillna(0) != 0).sum())


def main():
    print("[1/5] 加载价格宽表…")
    symbols = get_all_symbols()
    price = load_price_wide(symbols, WARMUP, END, field="close")
    valid = price.columns[price.notna().sum() > 500]
    price = price[list(valid)]
    print(f"  股票: {len(valid)}, 日期: {len(price)}")

    print(f"[2/5] 计算 breadth ({BREADTH_WINDOW} 日平滑) …")
    breadth = compute_breadth(price, window=BREADTH_WINDOW)
    bear_breadth = (breadth < 0).shift(1).fillna(False).astype(bool)
    bear_breadth = bear_breadth.loc[START:END]
    print(f"  breadth 序列 range: [{breadth.min():.3f}, {breadth.max():.3f}]")

    print(f"[3/5] 计算 HS300 MA{HS300_MA} regime …")
    hs300 = load_price_wide(["399300"], "2018-01-01", END, field="close")["399300"].dropna()
    bear_hs300 = hs300_bear_regime(hs300, ma_window=HS300_MA, shift_days=1).reindex(bear_breadth.index).fillna(False).astype(bool)

    print("[4/5] 统计对比…")
    total_days = len(bear_breadth)
    cov_b = float(bear_breadth.mean())
    cov_h = float(bear_hs300.mean())

    # 日历交集 / 并集 / 对称差
    both = (bear_breadth & bear_hs300).sum()
    only_b = (bear_breadth & ~bear_hs300).sum()
    only_h = (~bear_breadth & bear_hs300).sum()
    neither = (~bear_breadth & ~bear_hs300).sum()
    agreement = (both + neither) / total_days
    cohen_kappa = None
    try:
        # κ = (p_o - p_e) / (1 - p_e)
        p_o = agreement
        p_b1, p_h1 = cov_b, cov_h
        p_e = p_b1 * p_h1 + (1 - p_b1) * (1 - p_h1)
        cohen_kappa = (p_o - p_e) / (1 - p_e) if (1 - p_e) > 0 else float("nan")
    except Exception:
        cohen_kappa = None

    # 2022 首次进入 bear
    mask_2022 = (bear_breadth.index.year == 2022)
    b_2022 = bear_breadth[mask_2022]
    h_2022 = bear_hs300[mask_2022]
    first_b = first_bear_entry(b_2022)
    first_h = first_bear_entry(h_2022)

    # 切换次数
    sw_b = switch_count(bear_breadth)
    sw_h = switch_count(bear_hs300)

    print("[5/5] 写 markdown…")
    today = date.today().strftime("%Y%m%d")
    lines = []
    lines.append(f"# Market breadth regime 指标研究 — {today}")
    lines.append("")
    lines.append("> 目的: regime 指标质量分析 (非策略过门测试)")
    lines.append(f"> breadth 规则 (预注册, 不调参): (rising-falling)/(rising+falling), {BREADTH_WINDOW} 日平滑, <0 → bear, shift(1)")
    lines.append(f"> HS300 基线: MA{HS300_MA}, shift(1)")
    lines.append(f"> eval 段: {bear_breadth.index[0].date()} ~ {bear_breadth.index[-1].date()}, n={total_days}")
    lines.append("")

    lines.append("## 1. 覆盖率对比")
    lines.append("")
    lines.append(f"- bear_breadth 覆盖: **{cov_b:.1%}**")
    lines.append(f"- bear_hs300   覆盖: **{cov_h:.1%}**")
    lines.append("")

    lines.append("## 2. 日历一致性 (2×2)")
    lines.append("")
    lines.append(f"| | bear_hs300=T | bear_hs300=F |")
    lines.append(f"|:--|--:|--:|")
    lines.append(f"| bear_breadth=T | {both} | {only_b} |")
    lines.append(f"| bear_breadth=F | {only_h} | {neither} |")
    lines.append("")
    lines.append(f"- 一致率 (两者相同的天数比例): **{agreement:.1%}**")
    lines.append(f"- Cohen's κ: **{cohen_kappa:.3f}** (0 = 随机一致, 1 = 完全一致)")
    lines.append("")

    lines.append("## 3. 2022 首次进入 bear")
    lines.append("")
    lines.append(f"- bear_breadth 首次 True: {first_b.date() if first_b is not None else '(2022 内未触发)'}")
    lines.append(f"- bear_hs300   首次 True: {first_h.date() if first_h is not None else '(2022 内未触发)'}")
    if first_b is not None and first_h is not None:
        delta = (first_h - first_b).days
        if delta > 0:
            lines.append(f"- **breadth 领先 HS300 {delta} 天** (breadth 更早识别)")
        elif delta < 0:
            lines.append(f"- **HS300 领先 breadth {-delta} 天** (breadth 滞后)")
        else:
            lines.append(f"- 两者同日进入 bear")
    lines.append("")

    lines.append("## 4. 切换频次 (噪声度)")
    lines.append("")
    lines.append(f"- bear_breadth 切换次数: {sw_b}")
    lines.append(f"- bear_hs300   切换次数: {sw_h}")
    lines.append(f"- 说明: 次数越多噪声越大, 换仓成本越高 (同切换成本 0.1%/次)")
    lines.append("")

    lines.append("## 5. 诚实结论 (非过门判定)")
    lines.append("")
    # 不做过门判断, 只做定性结论
    if first_b and first_h and (first_h > first_b):
        lines.append(f"- **breadth 在 2022 早期领先 HS300 MA{HS300_MA} 识别 bear ({(first_h - first_b).days} 天领先)** — 值得作为 v28 候选")
    elif first_b and first_h and (first_h < first_b):
        lines.append(f"- breadth 在 2022 滞后于 HS300 MA{HS300_MA} — 不作为升级候选")
    else:
        lines.append(f"- breadth 与 HS300 MA{HS300_MA} 在 2022 进入时间接近 — 无明显优势")
    lines.append(f"- 一致率 {agreement:.1%}, κ={cohen_kappa:.2f}: {'高度相关, breadth 主要重复 HS300 信息' if cohen_kappa and cohen_kappa > 0.6 else '相对独立, breadth 可能提供额外信号'}")
    lines.append("")
    lines.append("## 6. 不抄近道的下一步")
    lines.append("")
    lines.append("1. 本文件只定性评估 regime 指标独立性, **不跑** breadth+v16 过门测试 (那会复制 v27 的 DSR 问题)")
    lines.append("2. 若要做 v28 候选 (breadth-gated v16 half position), 必须:")
    lines.append("   (a) 用 2026 Q1+ 独立 live 样本, 不重用 2022-2025 backtest 样本")
    lines.append("   (b) 严禁按本文件结果反向选择 window=20 (这本身就是一个自由度)")
    lines.append("   (c) 若要改 window, 必须预注册多个候选, 用 DSR 修正")
    lines.append("3. 严禁: 并排跑 breadth-window-{5,10,20,40,60} × threshold-{0, -0.1, -0.2} 做 15 组扫描 — 典型 p-hack")
    lines.append("")

    out_md = Path(f"journal/breadth_regime_research_{today}.md")
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"\n✓ 写出 {out_md}")

    print("\n=== 指标对比 ===")
    print(f"  breadth bear 覆盖: {cov_b:.1%}  |  HS300 bear 覆盖: {cov_h:.1%}")
    print(f"  一致率 {agreement:.1%}, Cohen's κ = {cohen_kappa:.3f}")
    print(f"  2022 首次 bear: breadth={first_b.date() if first_b else 'N/A'}, HS300={first_h.date() if first_h else 'N/A'}")
    print(f"  切换次数: breadth={sw_b}, HS300={sw_h}")


if __name__ == "__main__":
    main()
