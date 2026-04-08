"""
dashboard/services/research_service.py — Phase 7 研究助理服务层

把 pipeline/research_planner（提议层）和 pipeline/experiment_store（记录层）
封装成前端直接可消费的 dict，不暴露 dataclass。

所有函数都捕获异常，失败时返回 {"error": "...", ...} 结构而不是抛。
"""
from __future__ import annotations

from typing import Any


def list_experiments_for_view(limit: int = 50) -> dict:
    """
    列出最近的实验记录，按 created_at 倒序。

    返回:
      {
        "experiments": [{experiment_id, question_type, priority, question_text,
                         status, run_id, result_summary, created_at, ...}],
        "counts_by_status": {"proposed": 3, "success": 12, ...},
      }
    """
    try:
        from dataclasses import asdict

        from pipeline.experiment_store import list_experiments

        records = list_experiments(limit=limit)
        experiments = [asdict(r) for r in records]
        counts: dict[str, int] = {}
        for e in experiments:
            s = e.get("status", "proposed")
            counts[s] = counts.get(s, 0) + 1
        return {"experiments": experiments, "counts_by_status": counts}
    except Exception as exc:
        return {"experiments": [], "counts_by_status": {}, "error": str(exc)}


def plan_current_questions() -> dict:
    """
    用当前系统状态（factor_health）跑一次 research_planner，返回当前的提议列表。

    这是"只读"调用 —— 不持久化任何 question，只是把当下应该做什么暴露给前端。
    """
    try:
        from dataclasses import asdict

        from pipeline.research_planner import plan_research

        health_raw: dict = {}
        try:
            from pipeline.factor_monitor import factor_health_report
            health_raw = factor_health_report() or {}
        except Exception:
            health_raw = {}

        risk_alerts: list[dict] = []
        try:
            from dashboard.services.risk_service import get_risk_alerts

            raw = get_risk_alerts()
            if isinstance(raw, list):
                risk_alerts = raw
        except Exception:
            risk_alerts = []

        questions = plan_research(
            factor_health=health_raw,
            risk_alerts=risk_alerts,
            divergence=None,
        )
        return {
            "questions": [asdict(q) for q in questions],
            "n": len(questions),
        }
    except Exception as exc:
        return {"questions": [], "n": 0, "error": str(exc)}


if __name__ == "__main__":
    import json as _j
    print("=== experiments ===")
    print(_j.dumps(list_experiments_for_view(), ensure_ascii=False, indent=2))
    print("\n=== current questions ===")
    print(_j.dumps(plan_current_questions(), ensure_ascii=False, indent=2))
