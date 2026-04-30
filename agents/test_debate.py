"""
牛熊辩论快速测试
用极坐标价量因子（IC均值 -0.031，ICIR -0.28）作为 context 跑一次辩论
"""
from agents import debate_factor


class FakeLLM:
    """Deterministic test double; default pytest must not call external LLMs."""

    def complete_json(self, prompt: str) -> dict:
        if "bull_arguments" in prompt and "bear_arguments" not in prompt:
            return {
                "bull_arguments": [
                    "IC 为负且 t 统计显著，可作为反转方向使用",
                    "IC>0 占比低说明方向稳定，适合取反后入库",
                    "与价量行为相关，可能补充传统基本面因子",
                ]
            }
        if "bear_arguments" in prompt:
            return {
                "rebuttals": [
                    "负 IC 不等于可交易收益，成本可能吞噬边际",
                    "ICIR 偏低，单因子稳定性不足",
                    "需要检验行业和市值中性化后的残余有效性",
                ],
                "bear_arguments": [
                    "ICIR 只有 -0.28，独立入模质量有限",
                    "若换手较高，真实滑点会放大衰减",
                    "缺少样本外和 regime 分层验证",
                ],
            }
        return {
            "conclusion": "偏空原始方向，但可作为反转候选继续验证",
            "confidence": 0.72,
            "key_factors": ["负 IC 显著性", "交易成本敏感性"],
        }


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

    # 用 debate_factor 便捷函数；传入 fake LLM，避免默认测试依赖 claude/Ollama。
    result = debate_factor("极坐标价量因子", ic_data, llm=FakeLLM())

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
