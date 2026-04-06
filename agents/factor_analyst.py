"""
agents/factor_analyst.py — LLM 因子分析师

利用 Claude/Ollama 对因子挖掘结果进行深度分析：
  1. 解读因子排行榜背后的市场逻辑
  2. 分析推荐组合的互补性
  3. 评估策略升级的风险和收益
  4. 生成自然语言的研究报告

此 Agent 是可选的 — 无 LLM 时流水线照常运行，
有 LLM 时在 Reporter 阶段附加深度分析。
"""

import json
import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class FactorAnalyst:
    """
    LLM 驱动的因子分析师。

    在有 LLM 后端时，对因子研究结果生成自然语言解读。
    """

    def __init__(self):
        self._llm = None

    def _get_llm(self):
        """懒加载 LLM 客户端"""
        if self._llm is None:
            try:
                from agents.base import LLMClient
                client = LLMClient()
                if client._backend != "none":
                    self._llm = client
            except Exception:
                pass
        return self._llm

    def analyze_rankings(self, rankings: List[Dict], date: str) -> Optional[str]:
        """
        分析因子排行榜，生成自然语言解读。

        参数:
            rankings: 因子排行榜（FactorMiner 输出）
            date: 数据日期

        返回:
            str: 分析评论（Markdown），或 None（LLM 不可用）
        """
        llm = self._get_llm()
        if llm is None:
            return None

        # 构建排行榜文本
        ranking_text = "\n".join(
            f"{i+1}. {r['name']} (IC={r['IC_mean']:.4f}, ICIR={r['ICIR']:.4f}, "
            f"t={r['t_stat']:.4f}, L/S夏普={r['ls_sharpe']:.4f}, 类别={r['category']})"
            for i, r in enumerate(rankings[:15])
        )

        prompt = f"""你是一个 A 股量化研究分析师。以下是截至 {date} 的因子排行榜：

{ranking_text}

请用 3-5 句话分析：
1. 当前市场什么类型的因子最有效？为什么？
2. 排名前列的因子反映了什么样的市场环境？
3. 有什么值得注意的异常（如某类因子集体失效）？

简洁专业，直接给结论。"""

        try:
            return llm.complete(prompt, max_tokens=500)
        except Exception as e:
            logger.warning("LLM 因子分析失败: %s", e)
            return None

    def evaluate_strategy_change(
        self,
        current_factors: List[str],
        proposed_factors: List[str],
        current_icir: float,
        proposed_icir: float,
        rankings: List[Dict],
    ) -> Optional[str]:
        """
        评估策略变更建议，生成风险分析。

        返回:
            str: 评估意见，或 None
        """
        llm = self._get_llm()
        if llm is None:
            return None

        # 构建因子详情
        rank_lookup = {r["name"]: r for r in rankings}
        current_detail = "\n".join(
            f"  - {f}: IC={rank_lookup[f]['IC_mean']:.4f}, ICIR={rank_lookup[f]['ICIR']:.4f}"
            if f in rank_lookup else f"  - {f}: 无数据"
            for f in current_factors
        )
        proposed_detail = "\n".join(
            f"  - {f}: IC={rank_lookup[f]['IC_mean']:.4f}, ICIR={rank_lookup[f]['ICIR']:.4f}"
            if f in rank_lookup else f"  - {f}: 无数据"
            for f in proposed_factors
        )

        prompt = f"""你是一个量化策略风险顾问。请评估以下策略变更：

当前策略 (ICIR={current_icir:.4f}):
{current_detail}

建议策略 (ICIR={proposed_icir:.4f}):
{proposed_detail}

请用 3 句话评估：
1. 变更的核心风险是什么？
2. 新组合的因子多样性如何？
3. 你的建议（换/不换/部分替换）？

简洁专业。"""

        try:
            return llm.complete(prompt, max_tokens=400)
        except Exception as e:
            logger.warning("LLM 策略评估失败: %s", e)
            return None

    def daily_market_insight(self, signal_result: Dict) -> Optional[str]:
        """
        基于当日信号生成市场洞察。

        返回:
            str: 市场洞察，或 None
        """
        llm = self._get_llm()
        if llm is None:
            return None

        picks = signal_result.get("picks", [])
        excluded = signal_result.get("excluded", {})
        strategy = signal_result.get("metadata", {}).get("strategy", "unknown")
        factor_values = signal_result.get("factor_values", {})

        # 提取因子覆盖率
        factor_coverage = {
            name: len(vals) for name, vals in factor_values.items()
        }

        prompt = f"""你是一个 A 股日盘分析师。今日 {strategy} 策略选股结果：
- 入选: {len(picks)} 只
- 排除: ST={excluded.get('st', 0)}, 次新={excluded.get('new_listing', 0)}, 低价={excluded.get('low_price', 0)}
- 各因子覆盖: {factor_coverage}
- 前 5 只: {picks[:5]}

请用 2 句话点评今日选股特征和需要关注的风险点。简洁直接。"""

        try:
            return llm.complete(prompt, max_tokens=300)
        except Exception as e:
            logger.warning("LLM 市场洞察失败: %s", e)
            return None
