"""
routers/trigger.py — 操作页触发路由（Phase 6 最后一项）

把 control_surface 里的 mutating 命令（rebalance / weekly report）暴露成
dashboard 的 POST 端点，便于前端一个按钮就触发。

设计原则：
  - 每个端点只负责一件事，入参最小
  - 所有变更命令都带上 approved=True 走审批门（调用者已是通过 dashboard
    UI 主动点击，这一步审批已在人眼里发生）
  - 错误统一转成 400，details 里带上 control_surface 的原始 error
"""
from __future__ import annotations

from datetime import date as _date

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(tags=["trigger"])


class RebalanceRequest(BaseModel):
    date: str = ""  # 空则用今日


class WeeklyReportRequest(BaseModel):
    week: str = ""  # 空则让服务层取当前 ISO 周


def _run(command: str, **kwargs) -> dict:
    """调用控制面并把结果映射到 HTTP 语义"""
    from pipeline.control_surface import execute
    result = execute(command, approved=True, **kwargs)
    status = result.get("status")
    if status == "success":
        return {"status": "ok", "command": command, "data": result.get("data", {})}
    if status == "requires_approval":
        raise HTTPException(status_code=403, detail=result.get("message", "need approval"))
    # status == "error"
    raise HTTPException(status_code=400, detail={
        "command": command,
        "error": result.get("error", "unknown"),
    })


@router.post("/rebalance")
def trigger_rebalance(req: RebalanceRequest) -> dict:
    """
    手动触发一次模拟盘调仓。

    请求体: {"date": "2026-04-07"}（空则取当天）
    响应:   {"status": "ok", "command": "rebalance.run", "data": {...}}
    """
    target = req.date.strip() or str(_date.today())
    return _run("rebalance.run", date=target)


@router.post("/weekly-report")
def trigger_weekly_report(req: WeeklyReportRequest) -> dict:
    """
    手动生成/重建当前（或指定）周的周报。

    请求体: {"week": "2026-W14"}（空则由服务层取本周）
    响应:   {"status": "ok", "command": "report.weekly", "data": {...}}
    """
    kwargs = {}
    if req.week.strip():
        kwargs["week"] = req.week.strip()
    return _run("report.weekly", **kwargs)
