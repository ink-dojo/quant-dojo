"""
pipeline/experiment_summarizer.py — Phase 7 实验结果总结器

拿 experiment_store 里一堆记录，对比 baseline（多半是最近一次 production
回测）的 metrics，产出：

  - 结构化对比表（dict）
  - 人类可读的 markdown 报告

设计原则：
  - 纯函数：输入 ExperimentRecord 列表 + baseline metrics → 输出 dict / str
  - 不读盘（读盘由调用方完成），这样单测随便构造 fake 数据
  - 对每条实验：
      - success  → 展示 delta_sharpe / delta_max_dd / delta_total_return
      - failed   → 只说失败原因
      - skipped  → 只说跳过原因
      - proposed → 标注"未执行"
  - 给出整批 experiment 的 top-line 结论：
      - N 条 success
      - X 条有正向 sharpe 提升
      - Y 条回撤改善
"""
from __future__ import annotations

from typing import Optional

from pipeline.experiment_store import ExperimentRecord


# 只关心这几个指标的 delta
_DELTA_KEYS = ("sharpe", "max_drawdown", "total_return", "annualized_return", "information_ratio")


def compare_to_baseline(
    record: ExperimentRecord,
    baseline: Optional[dict] = None,
) -> dict:
    """
    把一条 experiment 的 result_summary 和 baseline 对比。

    返回 dict 结构：
        {
            "experiment_id": ...,
            "status": success/failed/skipped/proposed/running,
            "question": question_text,
            "priority": high/medium/low,
            "run_id": ... or None,
            "metrics": {...},        # 本实验的核心指标
            "baseline": {...} or None,
            "delta": {                # 仅 success 且 baseline 存在时
                "sharpe": +0.12,
                "max_drawdown": -0.03,
                "total_return": +0.05,
                ...
            },
            "verdict": "better" / "worse" / "neutral" / "n/a",
            "note": 失败/跳过原因文本，其它为空
        }
    """
    metrics = record.result_summary or {}
    row = {
        "experiment_id": record.experiment_id,
        "status": record.status,
        "priority": record.priority,
        "question": record.question_text,
        "question_type": record.question_type,
        "run_id": record.run_id,
        "metrics": metrics,
        "baseline": baseline or None,
        "delta": {},
        "verdict": "n/a",
        "note": "",
    }

    if record.status == "failed":
        row["note"] = f"失败：{record.error or '未知错误'}"
        return row
    if record.status == "skipped":
        row["note"] = f"跳过：{record.error or '未执行'}"
        return row
    if record.status in ("proposed", "running"):
        row["note"] = "未执行完成"
        return row

    # success 路径
    if not baseline:
        row["note"] = "无 baseline 可对比"
        return row

    delta = {}
    for k in _DELTA_KEYS:
        if k in metrics and k in baseline:
            try:
                delta[k] = float(metrics[k]) - float(baseline[k])
            except (TypeError, ValueError):
                continue
    row["delta"] = delta
    row["verdict"] = _verdict(delta)
    return row


def summarize_experiments(
    records: list[ExperimentRecord],
    baseline: Optional[dict] = None,
) -> dict:
    """
    对一批 experiment 产出汇总 dict。

    返回：
        {
            "total": N,
            "by_status": {"success": a, "failed": b, "skipped": c, ...},
            "improved": 数量（verdict=better）,
            "worsened": 数量（verdict=worse）,
            "rows": [compare_to_baseline(r) for r in records],
        }
    """
    rows = [compare_to_baseline(r, baseline) for r in records]
    by_status: dict[str, int] = {}
    for r in rows:
        by_status[r["status"]] = by_status.get(r["status"], 0) + 1
    improved = sum(1 for r in rows if r["verdict"] == "better")
    worsened = sum(1 for r in rows if r["verdict"] == "worse")
    return {
        "total": len(rows),
        "by_status": by_status,
        "improved": improved,
        "worsened": worsened,
        "rows": rows,
    }


def render_summary_markdown(summary: dict) -> str:
    """
    把 summarize_experiments 的结果渲染成 markdown 字符串。
    """
    lines: list[str] = ["# 实验结果总结", ""]
    total = summary.get("total", 0)
    by_status = summary.get("by_status", {})
    improved = summary.get("improved", 0)
    worsened = summary.get("worsened", 0)

    lines.append(f"**共 {total} 条实验**")
    if by_status:
        parts = [f"{k}={v}" for k, v in sorted(by_status.items())]
        lines.append("- 状态分布：" + ", ".join(parts))
    if total:
        lines.append(f"- 对比 baseline：改善 {improved} 条，劣化 {worsened} 条")
    lines.append("")

    rows = summary.get("rows") or []
    if not rows:
        lines.append("_无实验记录_")
        return "\n".join(lines)

    verdict_icon = {
        "better": "✅",
        "worse": "❌",
        "neutral": "➖",
        "n/a": "❔",
    }

    for i, row in enumerate(rows, 1):
        icon = verdict_icon.get(row["verdict"], "❔")
        lines.append(f"## {i}. {icon} `{row['experiment_id']}` ({row['status']})")
        lines.append("")
        lines.append(f"- **question**: {row['question']}")
        lines.append(f"- **priority**: {row['priority']}")
        if row.get("run_id"):
            lines.append(f"- **run_id**: `{row['run_id']}`")
        if row["metrics"]:
            lines.append("- **metrics**: " + _fmt_metrics(row["metrics"]))
        if row["delta"]:
            lines.append("- **delta**: " + _fmt_delta(row["delta"]))
        if row["note"]:
            lines.append(f"- **note**: {row['note']}")
        lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 私有
# ══════════════════════════════════════════════════════════════

def _verdict(delta: dict) -> str:
    """
    根据 delta 给出判断：
      - sharpe 明显上升 or 回撤明显改善 → better
      - sharpe 明显下降 or 回撤明显恶化 → worse
      - 两头都小幅波动 → neutral
    """
    if not delta:
        return "n/a"
    d_sharpe = delta.get("sharpe", 0.0)
    d_dd = delta.get("max_drawdown", 0.0)  # max_drawdown 是负数，越大越好
    # 门槛设宽松一点，避免噪声淹没信号
    better_signals = 0
    worse_signals = 0
    if d_sharpe >= 0.10:
        better_signals += 1
    elif d_sharpe <= -0.10:
        worse_signals += 1
    # max_drawdown: -0.15 → -0.10 时 delta = +0.05（改善）
    if d_dd >= 0.02:
        better_signals += 1
    elif d_dd <= -0.02:
        worse_signals += 1

    if better_signals > worse_signals:
        return "better"
    if worse_signals > better_signals:
        return "worse"
    return "neutral"


def _fmt_metrics(metrics: dict) -> str:
    chunks = []
    for k in ("sharpe", "total_return", "max_drawdown", "annualized_return", "information_ratio"):
        if k in metrics:
            chunks.append(f"{k}={_fmt_num(metrics[k])}")
    return ", ".join(chunks) if chunks else "—"


def _fmt_delta(delta: dict) -> str:
    chunks = []
    for k, v in delta.items():
        sign = "+" if v >= 0 else ""
        chunks.append(f"{k}={sign}{_fmt_num(v)}")
    return ", ".join(chunks)


def _fmt_num(x) -> str:
    try:
        fx = float(x)
    except (TypeError, ValueError):
        return str(x)
    if abs(fx) < 1:
        return f"{fx:.4f}"
    return f"{fx:.2f}"


if __name__ == "__main__":
    from pipeline.experiment_store import ExperimentRecord
    recs = [
        ExperimentRecord(
            experiment_id="exp_1", question_id="q1",
            question_type="factor_decay", question_text="drop mom?",
            priority="high", status="success", run_id="r1",
            result_summary={"sharpe": 1.4, "max_drawdown": -0.10, "total_return": 0.3},
        ),
        ExperimentRecord(
            experiment_id="exp_2", question_id="q2",
            question_type="factor_insufficient", question_text="tov 样本不足",
            priority="low", status="skipped", error="question_type=factor_insufficient",
        ),
    ]
    baseline = {"sharpe": 1.2, "max_drawdown": -0.15, "total_return": 0.2}
    s = summarize_experiments(recs, baseline=baseline)
    print(render_summary_markdown(s))
    print("✅ experiment_summarizer import ok")
