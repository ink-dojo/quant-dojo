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
from dataclasses import dataclass, field
from datetime import datetime
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


# ══════════════════════════════════════════════════════════════
# Tier 1.4 — Daily PnL Divergence (Issue #41)
# ══════════════════════════════════════════════════════════════
# 把 compute_divergence 输出的 daily_delta 转成 z-score, 触发 alert + kill 联动.
#
# Z-score 定义: |latest_daily_delta| / std(historical_daily_deltas)
#   - z < warn_zscore  → ok      (正常噪声)
#   - z ∈ [warn, crit) → warn    (留意, 不动作)
#   - z ≥ critical     → critical (alert + 写 state file + 触发 kill HALVE)
#
# 默认: warn_zscore=2.0, critical_zscore=3.0
# false positive 期望: 正态分布下 |z|>2 概率 4.6%, |z|>3 概率 0.27%

DEFAULT_DIVERGENCE_STATE_FILE = Path(__file__).parent.parent / "live" / "tracking_divergence_state.json"


@dataclass(frozen=True)
class DivergenceAlert:
    """
    Live vs Backtest 偏差告警结果.

    suggested_kill_action: critical 时设为 'halve', 由 caller 传给
    live.event_kill_switch.evaluate(external_triggers=[...]) 联动.
    """

    zscore: float
    alert_level: str                         # "ok" | "warn" | "critical" | "insufficient_data"
    daily_delta: float                       # 最新一日 (live - bt) 偏差
    historical_std: float                    # 历史日偏差 std (剔除最新一日)
    n_observations: int                      # 历史样本数
    asof_date: str                           # 最新一日日期 YYYY-MM-DD
    fallback_reason: Optional[str] = None    # 若 alert_level=insufficient_data, 说明原因
    summary: dict = field(default_factory=dict)  # compute_divergence 的完整 summary

    def is_warn(self) -> bool:
        return self.alert_level == "warn"

    def is_critical(self) -> bool:
        return self.alert_level == "critical"

    def to_kill_trigger(self) -> Optional[dict]:
        """
        给 event_kill_switch.evaluate(external_triggers=[...]) 用的 dict.
        critical → halve; 其他 → None (不触发).
        """
        if self.is_critical():
            return {
                "action": "halve",
                "reason": (
                    f"tracking divergence z={self.zscore:.2f} ≥ 3σ "
                    f"(daily_delta={self.daily_delta:+.4%}, σ={self.historical_std:.4%}) "
                    f"on {self.asof_date}"
                ),
            }
        return None

    def to_dict(self) -> dict:
        return {
            "zscore": self.zscore,
            "alert_level": self.alert_level,
            "daily_delta": self.daily_delta,
            "historical_std": self.historical_std,
            "n_observations": self.n_observations,
            "asof_date": self.asof_date,
            "fallback_reason": self.fallback_reason,
            "kill_trigger": self.to_kill_trigger(),
        }


def compute_divergence_zscore(
    daily_delta: list[float],
    dates: list[str],
    lookback_days: int = 30,
    warn_zscore: float = 2.0,
    critical_zscore: float = 3.0,
    min_observations: int = 10,
) -> DivergenceAlert:
    """
    纯函数: 拿 daily_delta 序列, 算最新一日的 z-score 与告警等级.

    Args:
        daily_delta: 每日 (live_ret - bt_ret) 序列, 来自 compute_divergence["daily_delta"]
        dates: 对应日期序列 (与 daily_delta 等长), 用于标 asof_date
        lookback_days: 用最近 N 日做历史 σ 估计 (默认 30)
        warn_zscore / critical_zscore: 阈值 (默认 2.0 / 3.0)
        min_observations: 历史样本最少 N 个, 不够 → insufficient_data

    Returns:
        DivergenceAlert. 数据不足时 alert_level='insufficient_data'.
    """
    n_total = len(daily_delta)
    if n_total != len(dates):
        raise ValueError(f"daily_delta ({n_total}) 与 dates ({len(dates)}) 长度不一致")

    if n_total < min_observations + 1:
        return DivergenceAlert(
            zscore=0.0,
            alert_level="insufficient_data",
            daily_delta=daily_delta[-1] if n_total > 0 else 0.0,
            historical_std=0.0,
            n_observations=max(n_total - 1, 0),
            asof_date=dates[-1] if n_total > 0 else "",
            fallback_reason=(
                f"总样本 {n_total} < min_observations + 1 ({min_observations + 1}), "
                f"历史 σ 估计不可信"
            ),
        )

    # 历史窗口: 最近 lookback_days 但**不**含最新一日
    history = daily_delta[-(lookback_days + 1):-1] if lookback_days + 1 <= n_total else daily_delta[:-1]
    latest = daily_delta[-1]
    n_hist = len(history)

    # 算 σ (ddof=1, sample std)
    if n_hist < 2:
        return DivergenceAlert(
            zscore=0.0,
            alert_level="insufficient_data",
            daily_delta=latest,
            historical_std=0.0,
            n_observations=n_hist,
            asof_date=dates[-1],
            fallback_reason=f"历史样本 {n_hist} < 2, 无法算 σ",
        )

    mean_hist = sum(history) / n_hist
    var_hist = sum((x - mean_hist) ** 2 for x in history) / (n_hist - 1)
    std_hist = var_hist ** 0.5

    if std_hist < 1e-10:
        # 历史全平 → 任何偏差都是无穷大. 视为 insufficient.
        return DivergenceAlert(
            zscore=0.0,
            alert_level="insufficient_data",
            daily_delta=latest,
            historical_std=std_hist,
            n_observations=n_hist,
            asof_date=dates[-1],
            fallback_reason=f"历史 σ ≈ 0 ({std_hist:.2e}), 无法计算 z-score",
        )

    zscore = abs(latest - mean_hist) / std_hist

    if zscore >= critical_zscore:
        alert_level = "critical"
    elif zscore >= warn_zscore:
        alert_level = "warn"
    else:
        alert_level = "ok"

    return DivergenceAlert(
        zscore=zscore,
        alert_level=alert_level,
        daily_delta=latest,
        historical_std=std_hist,
        n_observations=n_hist,
        asof_date=dates[-1],
    )


def daily_pnl_divergence(
    live_nav_path: Path,
    backtest_run_path: Path,
    lookback_days: int = 30,
    warn_zscore: float = 2.0,
    critical_zscore: float = 3.0,
    min_observations: int = 10,
) -> DivergenceAlert:
    """
    高层 API: 从 live nav 文件 + backtest run JSON, 计算最新一日的 z-score 偏差告警.

    包装 compute_divergence + compute_divergence_zscore.
    """
    div = compute_divergence(live_nav_path, backtest_run_path)
    if div.get("status") != "ok":
        return DivergenceAlert(
            zscore=0.0,
            alert_level="insufficient_data",
            daily_delta=0.0,
            historical_std=0.0,
            n_observations=0,
            asof_date="",
            fallback_reason=f"compute_divergence status={div.get('status')}: {div.get('reason', '')}",
        )

    alert = compute_divergence_zscore(
        daily_delta=div["daily_delta"],
        dates=div["dates"],
        lookback_days=lookback_days,
        warn_zscore=warn_zscore,
        critical_zscore=critical_zscore,
        min_observations=min_observations,
    )
    # 把 summary 塞回去
    return DivergenceAlert(
        zscore=alert.zscore,
        alert_level=alert.alert_level,
        daily_delta=alert.daily_delta,
        historical_std=alert.historical_std,
        n_observations=alert.n_observations,
        asof_date=alert.asof_date,
        fallback_reason=alert.fallback_reason,
        summary=div.get("summary", {}),
    )


def check_and_alert(
    live_nav_path: Path,
    backtest_run_path: Path,
    state_file: Optional[Path] = DEFAULT_DIVERGENCE_STATE_FILE,
    notify: bool = True,
    lookback_days: int = 30,
    warn_zscore: float = 2.0,
    critical_zscore: float = 3.0,
) -> DivergenceAlert:
    """
    每日 cron 入口: 算 divergence, 必要时发 alert + 写 state file.

    State file 用途: 给 active_strategy.py / event_kill_switch.py 在下一次调仓时
    读取, 判断是否需要 halve. 持久化保证 cron 与策略执行解耦.

    Args:
        live_nav_path: live/portfolio/nav.csv
        backtest_run_path: 对应回测 run JSON 路径
        state_file: 写入 alert state 的 JSON 路径. None = 不写
        notify: 是否调 alert_notifier 发告警
        lookback_days/warn_zscore/critical_zscore: 见 compute_divergence_zscore

    Returns:
        DivergenceAlert.
    """
    alert = daily_pnl_divergence(
        live_nav_path=live_nav_path,
        backtest_run_path=backtest_run_path,
        lookback_days=lookback_days,
        warn_zscore=warn_zscore,
        critical_zscore=critical_zscore,
    )

    if notify:
        # 延迟 import 避免循环依赖
        try:
            from pipeline.alert_notifier import AlertLevel, send_alert
        except ImportError:
            send_alert = None  # type: ignore[assignment]

        if send_alert is not None:
            if alert.is_critical():
                send_alert(
                    level=AlertLevel.CRITICAL,
                    title=f"Live vs Backtest 偏差 {alert.zscore:.2f}σ — CRITICAL",
                    body=(
                        f"日偏差 {alert.daily_delta:+.4%}, 历史 σ {alert.historical_std:.4%}, "
                        f"基于 {alert.n_observations} 日样本. 触发 kill switch HALVE."
                    ),
                    source="LiveVsBacktest",
                    date=alert.asof_date,
                )
            elif alert.is_warn():
                send_alert(
                    level=AlertLevel.WARNING,
                    title=f"Live vs Backtest 偏差 {alert.zscore:.2f}σ — WARN",
                    body=(
                        f"日偏差 {alert.daily_delta:+.4%}, 历史 σ {alert.historical_std:.4%}. "
                        f"暂不动作, 持续 monitor."
                    ),
                    source="LiveVsBacktest",
                    date=alert.asof_date,
                )

    if state_file is not None:
        state = {
            **alert.to_dict(),
            "updated_at": datetime.now().isoformat(),
            "live_nav_path": str(live_nav_path),
            "backtest_run_path": str(backtest_run_path),
        }
        state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(state_file, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2, default=str)

    return alert


def load_divergence_state(
    state_file: Path = DEFAULT_DIVERGENCE_STATE_FILE,
) -> Optional[dict]:
    """
    给 event_kill_switch / active_strategy 读 cron 写下的 state.
    返回 None = 文件不存在 (从未跑过 check_and_alert).
    """
    if not state_file.exists():
        return None
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None

