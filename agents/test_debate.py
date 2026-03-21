"""
牛熊辩论快速测试
用极坐标价量因子（IC均值 -0.031，ICIR -0.28）作为 context 跑一次辩论
"""
from agents import LLMClient, BullBearDebate, debate_factor


def test_debate():
    """测试牛熊辩论功能"""
    # 极坐标价量因子的 IC 统计数据
    ic_data = {
        "name": "极坐标价量因子",
        "IC_mean": -0.031,
        "IC_std": 0.11,
        "ICIR": -0.28,
        "pct_pos": 0.38,
        "t_stat": -4.2,
    }

    print("=" * 60)
    print("  牛熊辩论测试 — 极坐标价量因子")
    print("  IC均值=-0.031, ICIR=-0.28（显著的反转因子）")
    print("=" * 60)
    print()

    # 用 debate_factor 便捷函数
    result = debate_factor("极坐标价量因子", ic_data)

    # 打印结果
    print("【做多方观点】")
    for i, arg in enumerate(result.get("bull_arguments", []), 1):
        print(f"  {i}. {arg}")
    print()

    print("【做空方反驳】")
    for i, r in enumerate(result.get("rebuttals", []), 1):
        print(f"  {i}. {r}")
    print()

    print("【做空方观点】")
    for i, arg in enumerate(result.get("bear_arguments", []), 1):
        print(f"  {i}. {arg}")
    print()

    print("【主持人结论】")
    print(f"  结论: {result.get('conclusion', '无')}")
    print(f"  置信度: {result.get('confidence', 'N/A')}")
    print(f"  关键因素: {result.get('key_factors', [])}")
    print()

    # 基本断言
    assert "bull_arguments" in result, "缺少 bull_arguments"
    assert "bear_arguments" in result, "缺少 bear_arguments"
    assert "conclusion" in result, "缺少 conclusion"
    assert "confidence" in result, "缺少 confidence"

    print("✅ 辩论测试通过！结构完整，LLM 响应正常。")


if __name__ == "__main__":
    test_debate()
