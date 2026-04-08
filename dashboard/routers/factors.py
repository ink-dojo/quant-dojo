"""
routers/factors.py — 因子路由

GET /api/factors/health               → 各因子健康状态（healthy/warning/failed）
GET /api/factors/snapshot             → 最新截面因子统计（均值/中位数/分位数）
GET /api/factors/catalog              → research/factors/ 下所有因子目录 + 健康 merge
GET /api/factors/readme/{factor_dir}  → 某个因子目录的 README 原文
"""

from fastapi import APIRouter

from dashboard.services.factors_service import (
    get_factor_health,
    get_factor_snapshot,
    list_factor_catalog,
    read_factor_readme,
)

router = APIRouter()


@router.get("/health")
def factor_health() -> dict:
    """返回各因子健康状态，状态值为 healthy / warning / failed。"""
    return get_factor_health()


@router.get("/snapshot")
def factor_snapshot() -> dict:
    """返回最新日期因子截面的描述统计（均值、中位数、四分位数）。"""
    return get_factor_snapshot()


@router.get("/catalog")
def factor_catalog() -> dict:
    """扫描 research/factors/ 目录返回因子库目录页所需的完整数据。"""
    return list_factor_catalog()


@router.get("/readme/{factor_dir}")
def factor_readme(factor_dir: str) -> dict:
    """返回某个因子目录下 README.md 的原始 markdown 内容。"""
    return read_factor_readme(factor_dir)
