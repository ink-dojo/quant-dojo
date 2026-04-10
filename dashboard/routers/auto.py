"""
routers/auto.py — 策略自动生成路由

POST /api/auto/idea → 接受自然语言策略想法，流式返回各阶段进度和最终结果
"""

from datetime import date, timedelta

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.services.auto_service import run_idea_pipeline_sse

router = APIRouter()


class IdeaRequest(BaseModel):
    idea: str
    start: str = ""  # 默认空字符串，路由层自动取3年前
    end: str = ""    # 默认空字符串，路由层自动取今天


@router.post("/idea")
def submit_idea(req: IdeaRequest) -> StreamingResponse:
    """
    接受策略想法，以 SSE 流返回各阶段进度和最终结果。

    请求体: {"idea": "我想做基于ROE动量的选股策略"}
    返回: text/event-stream
    阶段: start → parsing → parsed → writing_spec
          → backtesting → risk_gate → done（或 error）
    """
    # 默认回测区间：最近3年
    end = req.end or str(date.today())
    start = req.start or str(date.today() - timedelta(days=3 * 365))

    return StreamingResponse(
        run_idea_pipeline_sse(req.idea, start, end),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
