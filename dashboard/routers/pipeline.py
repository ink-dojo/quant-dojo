"""
routers/pipeline.py — Pipeline 控制路由

POST /api/pipeline/run → 触发每日选股 pipeline（SSE 流）
"""

from datetime import date

from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from dashboard.services.pipeline_service import run_pipeline

router = APIRouter()


class PipelineRequest(BaseModel):
    date: str = ""  # 默认为空，服务层会取今日日期


@router.post("/run")
def pipeline_run(req: PipelineRequest) -> StreamingResponse:
    """
    触发每日选股 pipeline，以 SSE 流返回进度事件。

    请求体: {"date": "2026-03-22"}（date 为空时取当前系统日期）
    返回: text/event-stream，事件阶段：start → loading → computing → done / error
    """
    # date 为空时使用今日日期
    run_date = req.date.strip() or str(date.today())
    return StreamingResponse(
        run_pipeline(run_date),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
