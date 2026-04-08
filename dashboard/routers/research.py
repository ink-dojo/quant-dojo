"""
routers/research.py — Phase 7 研究助理路由（只读）

GET /api/research/experiments   最近的实验记录列表
GET /api/research/questions     当前系统状态对应的 research_planner 提议
"""
from fastapi import APIRouter

from dashboard.services.research_service import (
    list_experiments_for_view,
    plan_current_questions,
)

router = APIRouter()


@router.get("/experiments")
def experiments(limit: int = 50) -> dict:
    """返回最近 limit 条实验记录与按状态聚合的计数。"""
    return list_experiments_for_view(limit=limit)


@router.get("/questions")
def questions() -> dict:
    """基于当前因子健康 + 风险告警，跑一次 plan_research 返回建议问题。"""
    return plan_current_questions()
