"""
routers/strategies.py — 策略详情路由

GET /api/strategies/active   当前激活策略的完整可读快照
GET /api/strategies/         所有已知策略的简介列表
"""
from fastapi import APIRouter

from dashboard.services.strategies_service import (
    get_active_strategy_view,
    list_all_strategies,
)

router = APIRouter()


@router.get("/active")
def active_strategy() -> dict:
    """返回当前激活策略的因子组成 + 健康状态。"""
    return get_active_strategy_view()


@router.get("/")
def all_strategies() -> list[dict]:
    """返回所有已注册策略的简介。"""
    return list_all_strategies()
