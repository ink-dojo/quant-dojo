"""
routers/risk.py — 风险预警路由

GET /api/risk/alerts → 当前持仓风险预警列表
"""

from fastapi import APIRouter

from dashboard.services.risk_service import get_risk_alerts

router = APIRouter()


@router.get("/alerts")
def risk_alerts():
    """
    返回当前持仓风险预警列表。

    无论成功失败都返回 200 JSON：
      - 成功时返回预警 list（无预警为 []）
      - 失败时返回 {"error": "...", "alerts": []}
    """
    return get_risk_alerts()
