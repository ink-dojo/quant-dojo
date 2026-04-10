"""
dashboard/services/auto_service.py — 策略自动生成服务层

提供异步生成器，将 idea_to_strategy 流水线的各阶段进度以 SSE 格式流出。
核心问题：run_idea_pipeline 是同步阻塞函数，SSE 需要异步。
解决方案：用 asyncio.Queue 作为同步 progress_callback → 异步 yield 的桥接器。

阶段顺序：
  start → parsing → parsed → writing_spec → backtesting → risk_gate → fm_review → done（或 error）
"""

import asyncio
import json
from typing import AsyncGenerator


def _sse(payload: dict) -> str:
    """将 dict 序列化为 SSE 行格式。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def run_idea_pipeline_sse(
    idea: str,
    start: str,
    end: str,
) -> AsyncGenerator[str, None]:
    """
    将 idea_to_strategy 流水线包装为 SSE 异步生成器。

    参数：
        idea  — 用户输入的自然语言策略想法
        start — 回测开始日期 "YYYY-MM-DD"
        end   — 回测结束日期 "YYYY-MM-DD"

    Yield：
        SSE 格式字符串，每条形如 data: {"stage":..., "content":...}\\n\\n
        阶段顺序：start → parsing → parsed → writing_spec
                  → backtesting → risk_gate → fm_review → done（或 error）
        失败时 yield stage=error，然后 return

    实现细节：
        同步的 run_idea_pipeline 在线程池中执行，通过
        asyncio.Queue 将 progress_callback 的调用转为可 await 的事件，
        主协程持续从 queue 消费直到 SENTINEL，再 await future 获取最终结果。
    """
    # ── 起始事件 ─────────────────────────────────────────────────
    yield _sse({"stage": "start", "content": f"开始处理策略想法：{idea}"})

    try:
        from agents.base import LLMClient
        from agents.idea_parser import IdeaParser

        # 检查 LLM 后端可用性
        llm = LLMClient()
        if llm._backend == "none":
            yield _sse({
                "stage": "error",
                "content": "LLM 后端不可用，请安装 claude CLI 或启动 Ollama",
            })
            return

        # ── 解析自然语言策略想法 ──────────────────────────────────
        yield _sse({"stage": "parsing", "content": "正在解析策略想法..."})

        loop = asyncio.get_running_loop()
        spec = await loop.run_in_executor(
            None, lambda: IdeaParser(llm).analyze(idea_text=idea)
        )

        if not spec.get("parse_ok", True):
            yield _sse({
                "stage": "error",
                "content": f"想法解析失败：{spec.get('reason', '未知原因')}",
            })
            return

        factor_names = [f["name"] for f in spec["selected_factors"]]
        yield _sse({
            "stage": "parsed",
            "content": f"已识别 {len(factor_names)} 个因子：{factor_names}",
            "hypothesis": spec.get("hypothesis", ""),
        })

        # ── 用 Queue 桥接同步 progress_callback → 异步 SSE ───────
        queue: asyncio.Queue = asyncio.Queue()
        SENTINEL = object()

        def progress_callback(stage: str, message: str) -> None:
            """
            同步回调，将进度事件安全放入 asyncio Queue。
            由线程池工作线程调用，必须用 call_soon_threadsafe。
            """
            loop.call_soon_threadsafe(
                queue.put_nowait,
                _sse({"stage": stage, "content": message}),
            )

        def _run_blocking():
            """在线程池中运行阻塞的 pipeline，结束后放入 SENTINEL。"""
            try:
                from pipeline.idea_to_strategy import run_idea_pipeline
                return run_idea_pipeline(
                    idea_text=idea,
                    spec=spec,
                    backtest_start=start,
                    backtest_end=end,
                    progress_callback=progress_callback,
                )
            finally:
                # 无论成功或异常，都确保发送 SENTINEL 解除 queue 消费循环
                loop.call_soon_threadsafe(queue.put_nowait, SENTINEL)

        # 异步启动线程池任务
        future = loop.run_in_executor(None, _run_blocking)

        # 从 queue 消费进度事件，直到 SENTINEL
        while True:
            item = await queue.get()
            if item is SENTINEL:
                break
            yield item

        # 等待 future 完成，获取最终 PipelineResult
        result = await future

        # ── 最终结果事件 ──────────────────────────────────────────
        # IdeaResult.status 枚举：
        #   passed / failed_gate / failed_parse / failed_backtest / failed_ic
        # 只有 parsed / failed_gate 才是"流水线正常走完"，其余均视为 error 通知前端。
        _HARD_FAIL_STATUSES = {"failed_parse", "failed_ic", "failed_backtest"}
        if result.status in _HARD_FAIL_STATUSES:
            err_msg = result.error or f"流水线以 {result.status} 状态结束"
            yield _sse({"stage": "error", "content": err_msg})
            return

        yield _sse({
            "stage": "done",
            "status": result.status,
            "gate_passed": result.gate_passed,
            "metrics": result.metrics,
            "report": result.report_markdown,
            "strategy_name": result.strategy_name,
        })

    except Exception as exc:
        yield _sse({"stage": "error", "content": str(exc)})


# ── 最小验证（只验证 import，不触发 LLM）──────────────────────────

if __name__ == "__main__":
    import asyncio as _asyncio

    async def _test():
        print("== 测试 run_idea_pipeline_sse ==")
        async for event in run_idea_pipeline_sse("测试想法", "2023-01-01", "2024-01-01"):
            print(event.strip())
            # 只取第一条 start 事件，避免触发真实 LLM
            break
        print("✅ run_idea_pipeline_sse 生成器正常")

    _asyncio.run(_test())
