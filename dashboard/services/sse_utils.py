"""
SSE 工具函数 — Dashboard 所有 SSE 端点的共享序列化

确保 backtest_service 和 pipeline_service 产出格式一致的事件。
"""
import json


def sse_line(data: dict) -> str:
    """
    将字典序列化为 SSE data 行

    参数:
        data: 事件数据

    返回:
        "data: {json}\n\n" 格式字符串
    """
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


if __name__ == "__main__":
    result = sse_line({"stage": "test", "content": "hello"})
    assert result.startswith("data: ") and result.endswith("\n\n"), f"格式异常: {repr(result)}"
    print(f"✅ sse_line ok: {repr(result)}")
