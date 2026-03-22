"""
routers/factors.py — 因子路由

GET /api/factors/health    → 各因子健康状态（healthy/warning/failed）
GET /api/factors/snapshot  → 最新截面因子统计（均值/中位数/分位数）
"""

from fastapi import APIRouter

from dashboard.services.factors_service import get_factor_health, get_factor_snapshot

router = APIRouter()


@router.get("/health")
def factor_health() -> dict:
    """返回各因子健康状态，状态值为 healthy / warning / failed。"""
    return get_factor_health()


@router.get("/snapshot")
def factor_snapshot() -> dict:
    """返回最新日期因子截面的描述统计（均值、中位数、四分位数）。"""
    return get_factor_snapshot()
