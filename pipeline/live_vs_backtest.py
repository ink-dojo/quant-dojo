"""
live_vs_backtest.py — 实盘模拟 vs 回测对比工具

回答 Phase 5 的"实盘 vs 回测差异分析（滑点、延迟）"问题：
  - 同一个策略在回测里赚多少？
  - 同一段时间内 paper trader 真正跑出来多少？
  - 偏差从哪一天开始拉开？
  - 是单边漂移（系统性滑点）还是噪声？

输入：
  - 回测 run JSON 路径（含 equity_csv 引用）
  - live nav.csv 路径
  - 可选起止日期窗口

输出：
  - dict，含 daily / cumulative 偏差序列与汇总统计
  - 可选地把结果写成 Markdown 报告
"""
from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class DivergenceSummary:
    """汇总指标"""
    n_overlap_days: int
    live_total_return: float
    backtest_total_return: float
    total_delta: float          # live - backtest, 累计
    mean_daily_delta: float     # 每日偏差均值
    std_daily_delta: float
    max_abs_daily_delta: float
    max_abs_daily_date: str
    final_gap_pct: float        # 期末累计 NAV 偏差相对回测 NAV 的百分比

    def to_dict(self) -> dict:
        return {
            "n_overlap_days": self.n_overlap_days,
            "live_total_return": self.live_total_return,
            "backtest_total_return": self.backtest_total_return,
            "total_delta": self.total_delta,
            "mean_daily_delta": self.mean_daily_delta,
            "std_daily_delta": self.std_daily_delta,
            "max_abs_daily_delta": self.max_abs_daily_delta,
            "max_abs_daily_date": self.max_abs_daily_date,
            "final_gap_pct": self.final_gap_pct,
        }


def _read_nav_csv(path: Path) -> dict[str, float]:
    """读 nav.csv 为 {date: nav} 字典；忽略空行/损坏行"""
    if not path.exists():
        return {}
    out: dict[str, float] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date", "").strip()
            n = row.get("nav", "").strip()
            if not d or not n:
                continue
            try:
                out[d] = float(n)
            except ValueError:
                continue
    return out


def _read_backtest_equity(path: Path) -> dict[str, float]:
    """
    读回测 equity_csv 为 {date: cumulative_return} 字典。
    cumulative_return 是相对初始净值的累计收益率（不含初始 1）。
    """
    if not path.exists():
        return {}
    out: dict[str, float] = {}
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date", "").strip()
            if not d:
                continue
            try:
                out[d] = float(row.get("cumulative_return", 0))
            except ValueError:
                continue
    return out


def compute_divergence(
    live_nav_path: Path,
    backtest_run_path: Path,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> dict:
    """
    比较 live nav.csv 与回测 equity_csv 在共同日期上的累计收益偏差。

    步骤：
      1. 加载两份净值序列；live 用初始 NAV 折算成累计收益率
      2. 取共同交易日交集（可选窗口过滤）
      3. 计算每日 daily_return 与 cumulative 偏差
      4. 汇总指标返回

    参数：
        live_nav_path     : live/portfolio/nav.csv 的路径
        backtest_run_path : 回测 run JSON 的路径（含 artifacts.equity_csv 字段）
        start, end        : 可选窗口过滤 (YYYY-MM-DD)

    返回：
        dict，含 keys:
          - status        : "ok" / "no_overlap" / "missing_data"
          - n_overlap     : 共同天数
          - dates         : 排序好的共同日期
          - live_cum      : list[float]，对齐到第一天为 0 的累计收益
          - bt_cum        : 同上
          - daily_delta   : 每日 (live_ret - bt_ret) 列表
          - summary       : DivergenceSummary.to_dict()
          - meta          : {live_nav_file, backtest_run, equity_csv}
    """
    if not live_nav_path.exists():
        return {"status": "missing_data", "reason": f"live nav not found: {live_nav_path}"}
    if not backtest_run_path.exists():
        return {"status": "missing_data", "reason": f"backtest run not found: {backtest_run_path}"}

    with open(backtest_run_path, "r", encoding="utf-8") as f:
        run = json.load(f)

    eq_csv = run.get("artifacts", {}).get("equity_csv")
    if not eq_csv:
        return {"status": "missing_data", "reason": "backtest run lacks artifacts.equity_csv"}
    eq_path = Path(eq_csv)
    if not eq_path.exists():
        return {"status": "missing_data", "reason": f"equity csv not found: {eq_path}"}

    live = _read_nav_csv(live_nav_path)
    bt_cum = _read_backtest_equity(eq_path)

    if not live:
        return {"status": "missing_data", "reason": "live nav csv is empty"}
    if not bt_cum:
        return {"status": "missing_data", "reason": "backtest equity csv is empty"}

    # 找共同日期
    common = sorted(set(live.keys()) & set(bt_cum.keys()))
    if start:
        common = [d for d in common if d >= start]
    if end:
        common = [d for d in common if d <= end]

    if not common:
        return {
            "status": "no_overlap",
            "reason": "live nav and backtest equity have no overlapping trade dates",
            "live_dates": sorted(live.keys()),
            "backtest_dates": sorted(bt_cum.keys())[:5] + ["..."] + sorted(bt_cum.keys())[-5:],
        }

    # 把 live nav 折算成"以共同窗口第一天为基准"的累计收益
    base_live = live[common[0]]
    base_bt = bt_cum[common[0]]
    live_cum = [(live[d] / base_live - 1) for d in common]
    bt_cum_aligned = [(bt_cum[d] - base_bt) for d in common]
    daily_delta = []
    for i, d in enumerate(common):
        # 用累计差分得到日度偏差
        if i == 0:
            daily_delta.append(0.0)
        else:
            live_d = live_cum[i] - live_cum[i - 1]
            bt_d = bt_cum_aligned[i] - bt_cum_aligned[i - 1]
            daily_delta.append(live_d - bt_d)

    n = len(common)
    final_gap = live_cum[-1] - bt_cum_aligned[-1]
    mean_dd = sum(daily_delta) / n
    var_dd = sum((x - mean_dd) ** 2 for x in daily_delta) / max(n - 1, 1)
    std_dd = var_dd ** 0.5
    max_abs_idx = max(range(n), key=lambda i: abs(daily_delta[i]))

    summary = DivergenceSummary(
        n_overlap_days=n,
        live_total_return=live_cum[-1],
        backtest_total_return=bt_cum_aligned[-1],
        total_delta=final_gap,
        mean_daily_delta=mean_dd,
        std_daily_delta=std_dd,
        max_abs_daily_delta=daily_delta[max_abs_idx],
        max_abs_daily_date=common[max_abs_idx],
        final_gap_pct=(
            (final_gap / (1 + bt_cum_aligned[-1]) * 100)
            if (1 + bt_cum_aligned[-1]) != 0
            else 0.0
        ),
    )

    return {
        "status": "ok",
        "n_overlap": n,
        "dates": common,
        "live_cum": live_cum,
        "bt_cum": bt_cum_aligned,
        "daily_delta": daily_delta,
        "summary": summary.to_dict(),
        "meta": {
            "live_nav_file": str(live_nav_path),
            "backtest_run": run.get("run_id", ""),
            "strategy_id": run.get("strategy_id", ""),
            "equity_csv": str(eq_path),
        },
    }


def render_markdown_report(div: dict) -> str:
    """把 compute_divergence 的结果渲染成 Markdown 报告"""
    if div.get("status") != "ok":
        return f"# 实盘 vs 回测对比\n\n**状态**: {div.get('status')}\n\n原因: {div.get('reason', '-')}\n"

    s = div["summary"]
    meta = div["meta"]

    lines = ["# 实盘 vs 回测对比\n"]
    lines.append(f"- **回测 run**: `{meta['backtest_run']}` (策略 `{meta['strategy_id']}`)")
    lines.append(f"- **live nav**: `{Path(meta['live_nav_file']).name}`")
    lines.append(f"- **共同交易日**: {s['n_overlap_days']} 天 "
                 f"({div['dates'][0]} ~ {div['dates'][-1]})")
    lines.append("")
    lines.append("## 累计收益")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|----|---:|")
    lines.append(f"| live 累计收益 | {s['live_total_return']:+.4%} |")
    lines.append(f"| backtest 累计收益 | {s['backtest_total_return']:+.4%} |")
    lines.append(f"| **累计偏差 (live - bt)** | **{s['total_delta']:+.4%}** |")
    lines.append(f"| 期末 NAV 偏差占 bt 比重 | {s['final_gap_pct']:+.2f}% |")
    lines.append("")
    lines.append("## 日度偏差")
    lines.append("")
    lines.append("| 项 | 值 |")
    lines.append("|----|---:|")
    lines.append(f"| 日均偏差 | {s['mean_daily_delta']:+.4%} |")
    lines.append(f"| 偏差波动 σ | {s['std_daily_delta']:.4%} |")
    lines.append(f"| 最大绝对日偏差 | {s['max_abs_daily_delta']:+.4%} (on {s['max_abs_daily_date']}) |")
    lines.append("")
    lines.append("## 每日明细")
    lines.append("")
    lines.append("| 日期 | live 累计 | bt 累计 | 日偏差 |")
    lines.append("|------|----------:|--------:|------:|")
    for i, d in enumerate(div["dates"]):
        lines.append(
            f"| {d} | {div['live_cum'][i]:+.4%} | "
            f"{div['bt_cum'][i]:+.4%} | {div['daily_delta'][i]:+.4%} |"
        )
    lines.append("")
    return "\n".join(lines)
