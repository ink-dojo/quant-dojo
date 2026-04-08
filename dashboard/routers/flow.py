"""
routers/flow.py — 工作流状态路由

GET /api/flow/status
  返回整条工作流的状态卡片（data / signal / portfolio / risk / weekly / research）
  + 建议的下一步动作。
"""
from fastapi import APIRouter

from dashboard.services.flow_service import get_flow_status

router = APIRouter()


@router.get("/status")
def flow_status() -> dict:
    """返回当前工作流状态与下一步建议。"""
    return get_flow_status()
