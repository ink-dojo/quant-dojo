"""
routers/notebooks.py — Jupyter notebook 列表路由

GET /api/notebooks/  返回 research/notebooks/ 下所有 .ipynb 的元数据
"""
from fastapi import APIRouter

from dashboard.services.notebooks_service import list_notebooks

router = APIRouter()


@router.get("/")
def notebooks() -> dict:
    """返回所有 notebook 的元数据：标题、首段描述、cell 数、大小、更新时间。"""
    return list_notebooks()
