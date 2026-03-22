"""
dashboard/services/ai_service.py — AI 分析服务层

提供异步生成器，将 BullBearDebate / StockAnalyst 的结果以 SSE 格式分阶段流出。
每个生成器均捕获所有异常，转为 stage=error 事件，绝不抛出到路由层。
"""

import asyncio
import json
from datetime import date, timedelta
from typing import AsyncGenerator


def _sse(payload: dict) -> str:
    """将 dict 序列化为 SSE 行格式。"""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


async def run_debate(symbol: str, context: str) -> AsyncGenerator[str, None]:
    """
    执行牛熊辩论，分阶段 yield SSE 字符串。

    参数:
        symbol  : 股票代码或主题，如 "000001"
        context : 背景数据文本，如 IC/估值摘要

    Yield:
        SSE 格式字符串，每条形如 data: {"stage":..., "content":...}\\n\\n
        阶段顺序：start → bull → bear → moderator → done
        失败时 yield stage=error，然后 return
    """
    yield _sse({"stage": "start", "content": f"开始对 {symbol} 进行牛熊辩论..."})

    try:
        from agents.base import LLMClient
        from agents.debate import BullBearDebate

        llm = LLMClient()
        if llm._backend == "none":
            yield _sse({"stage": "error", "content": "LLM 后端不可用，请安装 claude CLI 或启动 Ollama"})
            return

        debate = BullBearDebate(llm)
        loop = asyncio.get_event_loop()
        topic = symbol

        # ── 第一轮：多方分析 ────────────────────────────────────────
        bull_prompt = debate.BULL_PROMPT.format(topic=topic, context=context)
        bull_result = await loop.run_in_executor(None, llm.complete_json, bull_prompt)
        bull_args = bull_result.get("bull_arguments", ["（多方未给出有效理由）"])
        yield _sse({"stage": "bull", "content": bull_args})

        # ── 第二轮：空方反驳 ────────────────────────────────────────
        bull_args_text = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(bull_args))
        bear_prompt = debate.BEAR_PROMPT.format(
            topic=topic, context=context, bull_args=bull_args_text
        )
        bear_result = await loop.run_in_executor(None, llm.complete_json, bear_prompt)
        rebuttals = bear_result.get("rebuttals", ["（空方未给出有效反驳）"])
        bear_args = bear_result.get("bear_arguments", ["（空方未给出有效理由）"])
        yield _sse({"stage": "bear", "content": bear_args, "rebuttals": rebuttals})

        # ── 第三轮：主持人综合 ──────────────────────────────────────
        bear_rebuttals_text = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(rebuttals))
        bear_args_text = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(bear_args))
        mod_prompt = debate.MODERATOR_PROMPT.format(
            topic=topic,
            context=context,
            bull_args=bull_args_text,
            bear_rebuttals=bear_rebuttals_text,
            bear_args=bear_args_text,
        )
        mod_result = await loop.run_in_executor(None, llm.complete_json, mod_prompt)
        yield _sse({
            "stage": "moderator",
            "content": mod_result.get("conclusion", "无法判断"),
            "confidence": mod_result.get("confidence", 0.5),
            "key_factors": mod_result.get("key_factors", []),
        })

        yield _sse({"stage": "done"})

    except Exception as exc:
        yield _sse({"stage": "error", "content": str(exc)})


async def run_analyze(symbol: str) -> AsyncGenerator[str, None]:
    """
    对单只股票执行综合分析，分阶段 yield SSE 字符串。

    参数:
        symbol : 股票代码，如 "000001"

    Yield:
        SSE 格式字符串，阶段顺序：start → analyzing → result → done
        失败时 yield stage=error，然后 return
    """
    yield _sse({"stage": "start", "content": f"开始分析 {symbol}..."})

    try:
        from agents.base import LLMClient
        from agents.stock_analyst import StockAnalyst

        llm = LLMClient()
        if llm._backend == "none":
            yield _sse({"stage": "error", "content": "LLM 后端不可用，请安装 claude CLI 或启动 Ollama"})
            return

        yield _sse({"stage": "analyzing", "content": "正在拉取价格/估值/财务数据..."})

        # 默认分析区间：最近一年
        end_date = str(date.today())
        start_date = str(date.today() - timedelta(days=365))

        loop = asyncio.get_event_loop()
        analyst = StockAnalyst(llm)

        # StockAnalyst.analyze 是阻塞调用，放到线程池中执行
        result = await loop.run_in_executor(
            None, lambda: analyst.analyze(symbol, start_date, end_date)
        )

        if not result:
            yield _sse({"stage": "error", "content": f"无法获取 {symbol} 的数据，请检查代码是否正确"})
            return

        yield _sse({"stage": "result", "content": result})
        yield _sse({"stage": "done"})

    except Exception as exc:
        yield _sse({"stage": "error", "content": str(exc)})


if __name__ == "__main__":
    # 最小验证：检查生成器可迭代
    import asyncio

    async def _test():
        print("== 测试 run_debate ==")
        async for event in run_debate("000001", "PE=10, PB=1.2, ROE=12%"):
            print(event.strip())
            # 只测第一条事件，避免触发真实 LLM
            break
        print("✅ run_debate 生成器正常")

        print("== 测试 run_analyze ==")
        async for event in run_analyze("000001"):
            print(event.strip())
            break
        print("✅ run_analyze 生成器正常")

    asyncio.run(_test())
