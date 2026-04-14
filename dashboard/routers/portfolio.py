"""
routers/portfolio.py — 持仓路由

GET /api/portfolio/        → 持仓摘要和绩效
GET /api/portfolio/nav     → 净值历史
GET /api/portfolio/trades  → 成交明细（最新在前）
"""

from fastapi import APIRouter

from dashboard.services.portfolio_service import (
    get_nav_history,
    get_portfolio_summary,
    get_trades_history,
)

router = APIRouter()


@router.get("")
def portfolio_summary() -> dict:
    """返回当前持仓列表和绩效摘要（nav/return/sharpe/drawdown）。"""
    return get_portfolio_summary()


@router.get("/nav")
def nav_history() -> list:
    """返回净值历史，格式 [{"date": "...", "nav": ...}, ...]。"""
    return get_nav_history()


@router.get("/trades")
def trades_history(limit: int = 100) -> dict:
    """返回最近 N 条成交记录，最新在前；默认 100 条。"""
    return get_trades_history(limit=limit)
