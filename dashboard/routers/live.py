"""
实时行情 API 路由

端点:
  GET /api/live/quote?symbols=600000,000001  获取实时行情
"""
from fastapi import APIRouter, Query

router = APIRouter(tags=["live"])


@router.get("/quote")
def live_quote(symbols: str = Query(None, description="逗号分隔的股票代码")):
    """获取实时行情"""
    from pipeline.control_surface import execute

    sym_list = symbols.split(",") if symbols else None
    result = execute("live.quote", symbols=sym_list)

    if result["status"] != "success":
        return {"error": result.get("error", "unknown")}
    return result["data"]
