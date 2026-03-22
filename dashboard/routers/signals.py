"""
routers/signals.py — 信号路由

GET /api/signals/latest   → 最新一期信号详情
GET /api/signals/history  → 最近 10 期信号日期和持仓数
"""

from fastapi import APIRouter

from dashboard.services.signals_service import get_latest_signal, get_signal_history

router = APIRouter()


@router.get("/latest")
def latest_signal() -> dict:
    """返回最新信号的 picks/scores/excluded/as_of_date。"""
    return get_latest_signal()


@router.get("/history")
def signal_history() -> list:
    """返回最近 10 期信号的日期和持仓数，格式 [{"date": "...", "n_picks": ...}]。"""
    return get_signal_history()
