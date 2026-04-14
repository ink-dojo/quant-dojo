"""
仪表盘 FastAPI 主程序
启动方式：uvicorn dashboard.app:app --port 8888 --reload
"""

import logging
import webbrowser
from pathlib import Path

from fastapi import FastAPI

_log = logging.getLogger(__name__)
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

# 创建 FastAPI 应用实例
app = FastAPI(
    title="量化工作台",
    description="A股量化研究仪表盘",
    version="0.1.0",
)

# 静态文件目录路径
_STATIC_DIR = Path(__file__).parent / "static"

# 挂载静态文件夹到 /static
app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")


def _register_routers() -> None:
    """注册各业务路由模块，若模块不存在则跳过（容错）。"""
    # 持仓管理路由
    try:
        from dashboard.routers import portfolio
        app.include_router(portfolio.router, prefix="/api/portfolio")
    except (ImportError, Exception) as e:
        _log.warning("Router 'portfolio' failed to load: %s", e)

    # 信号路由
    try:
        from dashboard.routers import signals
        app.include_router(signals.router, prefix="/api/signals")
    except (ImportError, Exception) as e:
        _log.warning("Router 'signals' failed to load: %s", e)

    # 因子路由
    try:
        from dashboard.routers import factors
        app.include_router(factors.router, prefix="/api/factors")
    except (ImportError, Exception) as e:
        _log.warning("Router 'factors' failed to load: %s", e)

    # 风险路由
    try:
        from dashboard.routers import risk
        app.include_router(risk.router, prefix="/api/risk")
    except (ImportError, Exception) as e:
        _log.warning("Router 'risk' failed to load: %s", e)

    # 数据状态路由
    try:
        from dashboard.routers import data_status
        app.include_router(data_status.router, prefix="/api/data")
    except (ImportError, Exception) as e:
        _log.warning("Router 'data_status' failed to load: %s", e)

    # AI 建议路由
    try:
        from dashboard.routers import ai
        app.include_router(ai.router, prefix="/api/ai")
    except (ImportError, Exception) as e:
        _log.warning("Router 'ai' failed to load: %s", e)

    # 管道控制路由
    try:
        from dashboard.routers import pipeline
        app.include_router(pipeline.router, prefix="/api/pipeline")
    except (ImportError, Exception) as e:
        _log.warning("Router 'pipeline' failed to load: %s", e)

    # 回测管理路由（策略注册表 + 运行记录）
    try:
        from dashboard.routers import backtest
        app.include_router(backtest.router, prefix="/api/backtest")
    except (ImportError, Exception) as e:
        _log.warning("Router 'backtest' failed to load: %s", e)

    # 实时行情路由
    try:
        from dashboard.routers import live
        app.include_router(live.router, prefix="/api/live")
    except (ImportError, Exception) as e:
        _log.warning("Router 'live' failed to load: %s", e)

    # 操作触发路由（rebalance / weekly report）
    try:
        from dashboard.routers import trigger
        app.include_router(trigger.router, prefix="/api/trigger")
    except (ImportError, Exception) as e:
        _log.warning("Router 'trigger' failed to load: %s", e)

    # 工作流总览（data → signal → portfolio → risk → weekly → research）
    try:
        from dashboard.routers import flow
        app.include_router(flow.router, prefix="/api/flow")
    except (ImportError, Exception) as e:
        _log.warning("Router 'flow' failed to load: %s", e)

    # 策略详情（当前策略 / 所有策略）
    try:
        from dashboard.routers import strategies
        app.include_router(strategies.router, prefix="/api/strategies")
    except (ImportError, Exception) as e:
        _log.warning("Router 'strategies' failed to load: %s", e)

    # Phase 7 研究助理（实验列表 + 当前提议）
    try:
        from dashboard.routers import research
        app.include_router(research.router, prefix="/api/research")
    except (ImportError, Exception) as e:
        _log.warning("Router 'research' failed to load: %s", e)

    # 仓库 markdown 文档浏览
    try:
        from dashboard.routers import docs
        app.include_router(docs.router, prefix="/api/docs")
    except (ImportError, Exception) as e:
        _log.warning("Router 'docs' failed to load: %s", e)

    # Jupyter notebook 列表
    try:
        from dashboard.routers import notebooks
        app.include_router(notebooks.router, prefix="/api/notebooks")
    except (ImportError, Exception) as e:
        _log.warning("Router 'notebooks' failed to load: %s", e)

    # 策略自动生成路由（自然语言想法 → SSE 流水线）
    try:
        from dashboard.routers.auto import router as auto_router
        app.include_router(auto_router, prefix="/api/auto")
        _log.info("Router 'auto' loaded")
    except (ImportError, Exception) as e:
        _log.warning("Router 'auto' failed to load: %s", e)


_register_routers()


@app.get("/", response_class=FileResponse)
def index() -> Response:
    """根路径：返回前端主页面 index.html。"""
    resp = FileResponse(str(_STATIC_DIR / "index.html"))
    resp.headers["Cache-Control"] = "no-cache, must-revalidate"
    return resp


if __name__ == "__main__":
    import os
    import threading
    import uvicorn

    port = int(os.getenv("DASHBOARD_PORT", "8888"))
    host = os.environ.get("DASHBOARD_HOST", "127.0.0.1")
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run(app, host=host, port=port)
