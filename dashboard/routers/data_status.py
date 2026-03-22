"""
routers/data_status.py — 数据状态路由

GET /api/data/status → 检查数据目录新鲜度和完整性
"""

from fastapi import APIRouter

router = APIRouter()


@router.get("/status")
def data_status() -> dict:
    """
    调用 pipeline.data_checker.check_data_freshness() 返回数据新鲜度报告。

    失败时返回含 error 字段的 dict。
    """
    try:
        from pipeline.data_checker import check_data_freshness
        return check_data_freshness()
    except Exception as e:
        return {"error": str(e)}
