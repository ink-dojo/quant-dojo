"""
牛熊辩论模块
参考 TradingAgents 的多智能体辩论架构，简化为三步流程：
  1. Bull Analyst → 列出做多理由
  2. Bear Analyst → 反驳 + 做空理由
  3. Moderator   → 综合结论 + 置信度
"""
from agents.base import LLMClient, BaseAgent


class BullBearDebate(BaseAgent):
    """
    牛熊辩论 Agent

    通过 LLM 分别扮演看多和看空分析师，进行结构化辩论，
    最终由主持人综合得出结论和置信度。

    使用示例:
        llm = LLMClient()
        debate = BullBearDebate(llm)
        result = debate.analyze(
            topic="000001 平安银行",
            context="PE_TTM=4.5, PB=0.45, ROE=10.8%, 净利润增速=-4.2%"
        )
        print(debate.format_report(result))
    """

    # 多方分析师 prompt 模板
    BULL_PROMPT = """你是一位看多分析师。请基于以下信息，列出3个做多理由。

讨论主题：{topic}
背景数据：{context}

要求：
1. 每个理由都要有数据支撑或逻辑论证
2. 考虑估值、成长性、行业趋势等多个维度
3. 用中文回答

请返回JSON格式：
{{"bull_arguments": ["理由1", "理由2", "理由3"]}}"""

    # 空方分析师 prompt 模板
    BEAR_PROMPT = """你是一位看空分析师。对方看多分析师提出了以下理由：
{bull_args}

讨论主题：{topic}
背景数据：{context}

请逐一反驳对方观点，并列出3个做空理由。
要求：
1. 每个理由都要有数据支撑或逻辑论证
2. 重点关注风险、估值陷阱、行业逆风等
3. 用中文回答

请返回JSON格式：
{{"rebuttals": ["反驳1", "反驳2", "反驳3"], "bear_arguments": ["做空理由1", "做空理由2", "做空理由3"]}}"""

    # 主持人 prompt 模板
    MODERATOR_PROMPT = """你是一位中立的投资研究主持人。以下是多空双方的辩论：

主题：{topic}
数据背景：{context}

【看多方】
{bull_args}

【看空方反驳】
{bear_rebuttals}

【看空方理由】
{bear_args}

请综合双方观点，给出：
1. 一句话结论（偏多/偏空/中性）
2. 置信度（0到1之间，0.5为完全不确定）
3. 关键决策因素（最影响判断的1-2个因素）

请返回JSON格式：
{{"conclusion": "你的结论", "confidence": 0.6, "key_factors": ["因素1", "因素2"]}}"""

    def analyze(self, **kwargs) -> dict:
        """
        执行牛熊辩论

        参数:
            topic   : 辩论主题，如 "动量因子" 或 "000001 平安银行"
            context : 背景数据摘要，如 IC 分析结果或估值数据

        返回:
            dict，包含 bull_args, bear_args, rebuttals, conclusion, confidence, key_factors
        """
        topic = kwargs.get("topic", "未指定主题")
        context = kwargs.get("context", "无额外数据")

        # 第一轮：多方分析
        bull_prompt = self.BULL_PROMPT.format(topic=topic, context=context)
        bull_result = self.llm.complete_json(bull_prompt)
        bull_args = bull_result.get("bull_arguments", ["（多方未给出有效理由）"])

        # 第二轮：空方反驳
        bull_args_text = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(bull_args))
        bear_prompt = self.BEAR_PROMPT.format(
            topic=topic, context=context, bull_args=bull_args_text
        )
        bear_result = self.llm.complete_json(bear_prompt)
        rebuttals = bear_result.get("rebuttals", ["（空方未给出有效反驳）"])
        bear_args = bear_result.get("bear_arguments", ["（空方未给出有效理由）"])

        # 第三轮：主持人综合
        bear_rebuttals_text = "\n".join(f"  {i+1}. {r}" for i, r in enumerate(rebuttals))
        bear_args_text = "\n".join(f"  {i+1}. {a}" for i, a in enumerate(bear_args))
        mod_prompt = self.MODERATOR_PROMPT.format(
            topic=topic,
            context=context,
            bull_args=bull_args_text,
            bear_rebuttals=bear_rebuttals_text,
            bear_args=bear_args_text,
        )
        mod_result = self.llm.complete_json(mod_prompt)

        return {
            "topic": topic,
            "bull_arguments": bull_args,
            "rebuttals": rebuttals,
            "bear_arguments": bear_args,
            "conclusion": mod_result.get("conclusion", "无法判断"),
            "confidence": mod_result.get("confidence", 0.5),
            "key_factors": mod_result.get("key_factors", []),
        }


def debate_factor(factor_name: str, ic_summary: dict, llm: LLMClient = None) -> dict:
    """
    对因子分析结果进行牛熊辩论

    参数:
        factor_name : 因子名称，如 "动量因子_20日"
        ic_summary  : utils/factor_analysis.ic_summary() 的输出 dict
                      包含 IC_mean, IC_std, ICIR, pct_pos, t_stat
        llm         : LLMClient 实例，为 None 时自动创建

    返回:
        辩论结果 dict
    """
    if llm is None:
        llm = LLMClient()

    # 把 IC 统计结果格式化为 context
    context_parts = [
        f"因子名称: {factor_name}",
        f"IC 均值: {ic_summary.get('IC_mean', 'N/A'):.4f}" if isinstance(ic_summary.get('IC_mean'), (int, float)) else f"IC 均值: {ic_summary.get('IC_mean', 'N/A')}",
        f"ICIR: {ic_summary.get('ICIR', 'N/A'):.4f}" if isinstance(ic_summary.get('ICIR'), (int, float)) else f"ICIR: {ic_summary.get('ICIR', 'N/A')}",
        f"IC>0 占比: {ic_summary.get('pct_pos', 'N/A'):.2%}" if isinstance(ic_summary.get('pct_pos'), (int, float)) else f"IC>0 占比: {ic_summary.get('pct_pos', 'N/A')}",
        f"t 统计量: {ic_summary.get('t_stat', 'N/A'):.4f}" if isinstance(ic_summary.get('t_stat'), (int, float)) else f"t 统计量: {ic_summary.get('t_stat', 'N/A')}",
    ]
    context = "\n".join(context_parts)

    debate = BullBearDebate(llm)
    return debate.analyze(topic=f"因子有效性: {factor_name}", context=context)


if __name__ == "__main__":
    # 最小验证：用极坐标价量因子的 IC 数据做一次辩论
    print("=" * 50)
    print("牛熊辩论测试 — 极坐标价量因子")
    print("=" * 50)

    ic_data = {
        "name": "极坐标价量因子",
        "IC_mean": -0.031,
        "IC_std": 0.11,
        "ICIR": -0.28,
        "pct_pos": 0.38,
        "t_stat": -4.2,
    }

    result = debate_factor("极坐标价量因子", ic_data)
    debate = BullBearDebate(LLMClient())
    print(debate.format_report(result))
    print("✅ 辩论测试完成")
