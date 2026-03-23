"""
回测服务 — Dashboard 后端读取策略注册表和运行记录

为 dashboard/routers/backtest.py 提供数据，
所有业务逻辑复用 pipeline.strategy_registry 和 pipeline.run_store。
"""
from __future__ import annotations

import asyncio
import atexit
import json
from concurrent.futures import ThreadPoolExecutor
from typing import AsyncGenerator

_executor = ThreadPoolExecutor(max_workers=2)
atexit.register(_executor.shutdown, wait=False)


def get_strategies() -> list[dict]:
    """
    列出所有已注册策略（同步）

    返回:
        策略信息列表
    """
    from pipeline.strategy_registry import list_strategies
    entries = list_strategies()
    return [
        {
            "id": e.id,
            "name": e.name,
            "description": e.description,
            "hypothesis": e.hypothesis,
            "params": [
                {
                    "name": p.name,
                    "description": p.description,
                    "default": p.default,
                    "type": p.type_hint,
                }
                for p in e.params
            ],
            "default_lookback_days": e.default_lookback_days,
            "data_type": e.data_type,
        }
        for e in entries
    ]


def get_runs(strategy_id: str = None, limit: int = 20) -> list[dict]:
    """
    列出历史运行记录（同步）

    参数:
        strategy_id: 按策略 ID 过滤（可选）
        limit: 最大返回条数

    返回:
        运行记录列表
    """
    from pipeline.run_store import list_runs
    runs = list_runs(strategy_id=strategy_id, limit=limit)
    return [
        {
            "run_id": r.run_id,
            "strategy_id": r.strategy_id,
            "strategy_name": r.strategy_name,
            "params": r.params,
            "start_date": r.start_date,
            "end_date": r.end_date,
            "status": r.status,
            "metrics": r.metrics,
            "created_at": r.created_at,
            "artifacts": r.artifacts,
        }
        for r in runs
    ]


def get_run_detail(run_id: str) -> dict:
    """
    获取单条运行记录详情（同步）

    参数:
        run_id: 运行 ID

    返回:
        运行记录详情字典

    异常:
        FileNotFoundError: 记录不存在
    """
    from pipeline.run_store import get_run
    r = get_run(run_id)
    return {
        "run_id": r.run_id,
        "strategy_id": r.strategy_id,
        "strategy_name": r.strategy_name,
        "params": r.params,
        "start_date": r.start_date,
        "end_date": r.end_date,
        "status": r.status,
        "metrics": r.metrics,
        "error": r.error,
        "created_at": r.created_at,
        "artifacts": r.artifacts,
    }


def compare_runs(run_ids: list[str]) -> dict:
    """
    对比多个运行记录（同步）

    参数:
        run_ids: 运行 ID 列表

    返回:
        对比结果
    """
    from pipeline.run_store import compare_runs as _compare
    return _compare(run_ids)


async def run_backtest_async(
    strategy_id: str,
    start: str,
    end: str,
    params: dict = None,
) -> AsyncGenerator[str, None]:
    """
    异步运行回测并通过 SSE 流式返回进度（异步生成器）

    参数:
        strategy_id: 策略 ID
        start: 开始日期
        end: 结束日期
        params: 策略参数

    生成:
        SSE 格式的 data 行
    """
    import datetime
    from pipeline.strategy_registry import get_strategy, run_strategy
    from pipeline.run_store import (
        generate_run_id, RunRecord, save_run
    )

    yield _sse({"stage": "start", "content": f"正在加载策略 {strategy_id}..."})

    try:
        entry = get_strategy(strategy_id)
    except KeyError as e:
        yield _sse({"stage": "error", "content": str(e)})
        return

    yield _sse({"stage": "loading", "content": f"加载数据 {start} ~ {end}..."})

    # 在线程池中运行回测（避免阻塞事件循环）
    result = await asyncio.get_running_loop().run_in_executor(
        _executor,
        lambda: run_strategy(strategy_id, start, end, params),
    )

    if result["status"] == "failed":
        yield _sse({"stage": "error", "content": f"回测失败: {result['error']}"})
        return

    yield _sse({"stage": "computing", "content": "计算绩效指标..."})

    # 保存运行记录
    run_id = generate_run_id(strategy_id, start, end, result["params"])
    record = RunRecord(
        run_id=run_id,
        strategy_id=strategy_id,
        strategy_name=entry.name,
        params=result["params"],
        start_date=start,
        end_date=end,
        status="success",
        metrics=result["metrics"],
        created_at=datetime.datetime.now().isoformat(),
    )
    save_run(record, equity_df=result.get("results_df"))

    yield _sse({
        "stage": "done",
        "content": f"回测完成: {entry.name}",
        "run_id": run_id,
        "metrics": result["metrics"],
    })


def _sse(data: dict) -> str:
    """格式化 SSE 数据行"""
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
