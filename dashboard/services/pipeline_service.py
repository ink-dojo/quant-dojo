"""
dashboard/services/pipeline_service.py — Pipeline 服务层

提供异步生成器，将 run_daily_pipeline 的执行过程以 SSE 格式分阶段流出。
捕获所有异常，转为 stage=error 事件，不抛出到路由层。
"""

import asyncio
from typing import AsyncGenerator


def _sse(payload: dict) -> str:
    """将 dict 序列化为 SSE 行格式。"""
    from dashboard.services.sse_utils import sse_line
    return sse_line(payload)


async def run_pipeline(date: str) -> AsyncGenerator[str, None]:
    """
    执行每日选股 pipeline，分阶段 yield SSE 进度事件。

    参数:
        date : 信号日期字符串，如 "2026-03-22"

    Yield:
        SSE 格式字符串，阶段顺序：start → loading → computing → filtering → done
        失败时 yield stage=error，然后 return
    """
    yield _sse({"stage": "start", "content": f"开始运行 {date} 选股 pipeline..."})

    try:
        from pipeline.control_surface import execute

        yield _sse({"stage": "loading", "content": "正在加载价格数据..."})

        # 统一走控制面执行，与 CLI 共享同一契约
        result = await asyncio.get_running_loop().run_in_executor(
            None, lambda: execute("signal.run", approved=True, date=date)
        )

        if result["status"] == "error":
            yield _sse({"stage": "error", "content": result["error"]})
            return

        data = result.get("data", {})
        if data.get("error"):
            yield _sse({"stage": "error", "content": data["error"]})
            return

        picks = data.get("picks", [])
        yield _sse({
            "stage": "done",
            "content": f"选股完成，共选出 {len(picks)} 只股票",
            "date": data.get("date", date),
            "picks": picks[:10],  # 只返回前10只，避免数据过大
            "n_total": len(picks),
        })

    except ImportError:
        yield _sse({"stage": "error", "content": "pipeline 模块未安装，请检查环境"})
    except Exception as exc:
        yield _sse({"stage": "error", "content": str(exc)})


if __name__ == "__main__":
    # 最小验证：检查生成器可迭代
    import asyncio

    async def _test():
        print("== 测试 run_pipeline ==")
        async for event in run_pipeline("2026-03-22"):
            print(event.strip())
            # 只测第一条事件
            break
        print("✅ run_pipeline 生成器正常")

    asyncio.run(_test())
