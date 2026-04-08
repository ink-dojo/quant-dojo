"""
仪表盘 FastAPI 主程序
启动方式：uvicorn dashboard.app:app --port 8888 --reload
"""

import webbrowser
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

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
    except (ImportError, Exception):
        pass

    # 信号路由
    try:
        from dashboard.routers import signals
        app.include_router(signals.router, prefix="/api/signals")
    except (ImportError, Exception):
        pass

    # 因子路由
    try:
        from dashboard.routers import factors
        app.include_router(factors.router, prefix="/api/factors")
    except (ImportError, Exception):
        pass

    # 风险路由
    try:
        from dashboard.routers import risk
        app.include_router(risk.router, prefix="/api/risk")
    except (ImportError, Exception):
        pass

    # 数据状态路由
    try:
        from dashboard.routers import data_status
        app.include_router(data_status.router, prefix="/api/data")
    except (ImportError, Exception):
        pass

    # AI 建议路由
    try:
        from dashboard.routers import ai
        app.include_router(ai.router, prefix="/api/ai")
    except (ImportError, Exception):
        pass

    # 管道控制路由
    try:
        from dashboard.routers import pipeline
        app.include_router(pipeline.router, prefix="/api/pipeline")
    except (ImportError, Exception):
        pass

    # 回测管理路由（策略注册表 + 运行记录）
    try:
        from dashboard.routers import backtest
        app.include_router(backtest.router, prefix="/api/backtest")
    except (ImportError, Exception):
        pass

    # 实时行情路由
    try:
        from dashboard.routers import live
        app.include_router(live.router, prefix="/api/live")
    except (ImportError, Exception):
        pass

    # 操作触发路由（rebalance / weekly report）
    try:
        from dashboard.routers import trigger
        app.include_router(trigger.router, prefix="/api/trigger")
    except (ImportError, Exception):
        pass


_register_routers()


@app.get("/", response_class=FileResponse)
def index() -> FileResponse:
    """根路径：返回前端主页面 index.html。"""
    return FileResponse(str(_STATIC_DIR / "index.html"))


if __name__ == "__main__":
    import os
    import threading
    import uvicorn

    port = int(os.getenv("DASHBOARD_PORT", "8888"))
    threading.Timer(1.0, lambda: webbrowser.open(f"http://localhost:{port}")).start()
    uvicorn.run(app, host="0.0.0.0", port=port)
