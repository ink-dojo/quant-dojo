"""
routers/ai.py — AI 分析路由

POST /api/ai/debate  → 牛熊辩论（SSE 流）
POST /api/ai/analyze → 单股综合分析（SSE 流）
"""

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.services.ai_service import run_analyze, run_debate

router = APIRouter()


class DebateRequest(BaseModel):
    symbol: str
    context: str = ""


class AnalyzeRequest(BaseModel):
    symbol: str


@router.post("/debate")
def debate(req: DebateRequest) -> StreamingResponse:
    """
    对指定股票/主题发起牛熊辩论，以 SSE 流返回各阶段结果。

    请求体: {"symbol": "000001", "context": "PE=10, ..."}
    返回: text/event-stream，事件阶段：start → bull → bear → moderator → done
    """
    return StreamingResponse(
        run_debate(req.symbol, req.context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/analyze")
def analyze(req: AnalyzeRequest) -> StreamingResponse:
    """
    对指定股票执行综合分析，以 SSE 流返回结果。

    请求体: {"symbol": "000001"}
    返回: text/event-stream，事件阶段：start → analyzing → result → done
    """
    return StreamingResponse(
        run_analyze(req.symbol),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
