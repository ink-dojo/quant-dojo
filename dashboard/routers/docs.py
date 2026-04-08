"""
routers/docs.py — 仓库 markdown 文档浏览路由

GET /api/docs/tree              返回所有可读 markdown 的元数据列表
GET /api/docs/read?rel=<path>   返回指定 .md 文件的原始内容
"""
from fastapi import APIRouter, Query

from dashboard.services.docs_service import list_docs, read_doc

router = APIRouter()


@router.get("/tree")
def docs_tree() -> dict:
    """返回整个仓库的 markdown 文档树（按更新时间倒序）。"""
    return list_docs()


@router.get("/read")
def docs_read(rel: str = Query(..., description="相对 repo root 的 .md 文件路径")) -> dict:
    """读取指定 markdown 文件的原文（严格校验路径不越界）。"""
    return read_doc(rel)
