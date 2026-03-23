"""
回测 API 路由 — 策略注册表、运行记录、回测触发

端点:
  GET  /api/backtest/strategies        列出已注册策略
  GET  /api/backtest/runs              列出历史回测记录
  GET  /api/backtest/runs/{run_id}     获取单条运行详情
  POST /api/backtest/compare           对比多个运行
  POST /api/backtest/run               触发回测（SSE 流式）
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

router = APIRouter(tags=["backtest"])


# ── 请求模型 ─────────────────────────────────────────────────

class BacktestRunRequest(BaseModel):
    """回测运行请求"""
    strategy_id: str
    start: str
    end: str
    params: Optional[dict] = None


class CompareRequest(BaseModel):
    """对比请求"""
    run_ids: list[str]


# ── 端点 ─────────────────────────────────────────────────────

@router.get("/strategies")
def api_strategies():
    """列出所有已注册策略"""
    try:
        from dashboard.services.backtest_service import get_strategies
        return get_strategies()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs")
def api_runs(
    strategy: str = Query(None, description="按策略 ID 过滤"),
    limit: int = Query(20, description="返回条数"),
):
    """列出历史回测记录"""
    try:
        from dashboard.services.backtest_service import get_runs
        return get_runs(strategy_id=strategy, limit=limit)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runs/{run_id}")
def api_run_detail(run_id: str):
    """获取单条运行详情"""
    try:
        from dashboard.services.backtest_service import get_run_detail
        return get_run_detail(run_id)
    except (FileNotFoundError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/compare")
def api_compare(req: CompareRequest):
    """对比多个运行记录"""
    try:
        from dashboard.services.backtest_service import compare_runs
        return compare_runs(req.run_ids)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/run")
async def api_run_backtest(req: BacktestRunRequest):
    """触发回测（SSE 流式返回进度）"""
    from dashboard.services.backtest_service import run_backtest_async

    async def event_stream():
        async for chunk in run_backtest_async(
            strategy_id=req.strategy_id,
            start=req.start,
            end=req.end,
            params=req.params,
        ):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
    )
