"""
routers/portfolio.py — 持仓路由

GET /api/portfolio/     → 持仓摘要和绩效
GET /api/portfolio/nav  → 净值历史
"""

from fastapi import APIRouter

from dashboard.services.portfolio_service import get_nav_history, get_portfolio_summary

router = APIRouter()


@router.get("/")
def portfolio_summary() -> dict:
    """返回当前持仓列表和绩效摘要（nav/return/sharpe/drawdown）。"""
    return get_portfolio_summary()


@router.get("/nav")
def nav_history() -> list:
    """返回净值历史，格式 [{"date": "...", "nav": ...}, ...]。"""
    return get_nav_history()
