"""
agents/fund_manager.py — 基金经理 Agent（私募视角）

灵感来源：agency-agents / Finance Tracker + Model QA Specialist
改写为 A 股量化私募语境：以 CIO / 基金经理视角对策略做投资委员会级别的评审。

职责：
  1. 对回测结果和实盘表现做"投资委员会" (IC) 级别的评审
  2. 识别策略风险点并给出带条件的批准 / 否决
  3. 对比多个策略版本，推荐资本分配方向
  4. 生成投资备忘录（Investment Memo）
  5. 提供季度 / 月度基金健康报告

评审框架（改编自 Sloan Anomaly / Finance Tracker 投资分析框架）：
  - 收益端：年化收益、Alpha、Calmar 比率
  - 风险端：最大回撤、波动率、Beta 暴露
  - 稳定性：Sharpe、IR（信息比率）、胜率
  - 因子质量：ICIR、因子多样性（Effective N）、衰减速度
  - 执行可行性：换手率、容量估算、交易成本

集成说明：
  - 可插入 idea_to_strategy.py 的 Stage 6（基金经理评审）
  - 可在 pipeline/cli.py 的 `research summarize` 后调用
  - 可在 dashboard 中触发（POST /api/fm/review）
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ══════════════════════════════════════════════════════════════════════════
# 评审门槛（与 risk_gate.DEFAULT_RULES 对齐，但此处侧重 "值不值得分配资本"）
# ══════════════════════════════════════════════════════════════════════════

REVIEW_STANDARDS = {
    # 收益端：最低要求 / 目标
    "annualized_return": {"min_pass": 0.15, "target": 0.20, "label": "年化收益"},
    "calmar_ratio":      {"min_pass": 0.60, "target": 1.00, "label": "Calmar 比率"},
    # 风险端：绝对值上限
    "max_drawdown_abs":  {"max_pass": 0.30, "target": 0.20, "label": "最大回撤"},
    "annualized_vol":    {"max_pass": 0.30, "target": 0.20, "label": "年化波动率"},
    # 稳定性
    "sharpe":            {"min_pass": 0.80, "target": 1.20, "label": "夏普比率"},
    "information_ratio": {"min_pass": 0.50, "target": 0.80, "label": "信息比率"},
    "win_rate":          {"min_pass": 0.45, "target": 0.55, "label": "胜率"},
    # 因子质量
    "icir":              {"min_pass": 0.40, "target": 0.70, "label": "ICIR（最佳因子）"},
    "effective_n":       {"min_pass": 10,   "target": 20,   "label": "有效持仓数"},
    # 执行可行性
    "annual_turnover":   {"max_pass": 24,   "target": 12,   "label": "年换手次数"},
    "n_trading_days":    {"min_pass": 700,  "target": 1000, "label": "回测天数"},
}


# ══════════════════════════════════════════════════════════════════════════
# 数据类
# ══════════════════════════════════════════════════════════════════════════

@dataclass
class ReviewItem:
    """单项指标评审结果"""
    key: str
    label: str
    actual: Optional[float]
    min_pass: Optional[float] = None
    target: Optional[float] = None
    passed: bool = True
    rating: str = "pass"      # "pass" | "warn" | "fail" | "missing"
    note: str = ""


@dataclass
class FundManagerDecision:
    """
    基金经理评审决定。

    decision:
      "approved"      — 通过，可进入模拟盘
      "conditional"   — 附条件通过（conditions 非空）
      "rejected"      — 否决
    """
    decision: str                      # "approved" | "conditional" | "rejected"
    confidence: float                  # 0~1，对决定的把握程度
    headline: str                      # 一句话结论
    rationale: str                     # 详细理由（Markdown）
    conditions: List[str] = field(default_factory=list)   # 附条件（conditional 时非空）
    risks: List[str] = field(default_factory=list)        # 主要风险点
    items: List[ReviewItem] = field(default_factory=list) # 逐项评审明细
    memo: str = ""                     # LLM 生成的投资备忘录（可选）

    def to_dict(self) -> dict:
        d = asdict(self)
        return d


# ══════════════════════════════════════════════════════════════════════════
# 主类
# ══════════════════════════════════════════════════════════════════════════

class FundManager:
    """
    基金经理 Agent（CIO / 投资委员会视角）。

    可在有 LLM 后端时生成自然语言备忘录；
    无 LLM 时仍可基于规则完成数字评审。

    使用示例::

        fm = FundManager()
        decision = fm.review_strategy(metrics, factors=["momentum", "bp"])
        print(decision.headline)
        print(decision.memo)
    """

    def __init__(self, standards: Optional[dict] = None):
        self._standards = standards or REVIEW_STANDARDS
        self._llm = None

    # ── LLM 懒加载 ──────────────────────────────────────────────────────

    def _get_llm(self):
        """懒加载 LLM 客户端；无后端时返回 None。"""
        if self._llm is None:
            try:
                from agents.base import LLMClient
                client = LLMClient()
                if client._backend != "none":
                    self._llm = client
            except Exception:
                pass
        return self._llm

    # ── 核心评审方法 ─────────────────────────────────────────────────────

    def review_strategy(
        self,
        metrics: dict,
        factors: Optional[List[str]] = None,
        strategy_name: str = "未命名策略",
        extra_context: str = "",
    ) -> FundManagerDecision:
        """
        对一个策略的回测指标做全面评审。

        参数:
            metrics        : 回测指标字典，键与 REVIEW_STANDARDS 对齐
            factors        : 使用的因子列表
            strategy_name  : 策略名称（用于报告标题）
            extra_context  : 附加背景文本（传给 LLM）

        返回:
            FundManagerDecision
        """
        # Step 1: 数字评审
        items = self._score_metrics(metrics)
        fail_items = [i for i in items if i.rating == "fail"]
        warn_items = [i for i in items if i.rating == "warn"]
        miss_items = [i for i in items if i.rating == "missing"]

        # Step 2: 确定决定
        if fail_items:
            decision = "rejected"
            confidence = max(0.6, min(0.95, 0.6 + len(fail_items) * 0.1))
            headline = f"否决 — {len(fail_items)} 项硬指标未达门槛"
        elif warn_items:
            decision = "conditional"
            confidence = 0.6
            headline = f"附条件通过 — {len(warn_items)} 项警告需跟踪"
        else:
            decision = "approved"
            confidence = 0.80
            headline = "通过 — 各项指标均达评审门槛"

        # Step 3: 构建理由
        rationale = self._build_rationale(items, strategy_name, metrics)
        conditions = self._derive_conditions(warn_items, miss_items, metrics)
        risks = self._derive_risks(fail_items, warn_items, metrics, factors)

        decision_obj = FundManagerDecision(
            decision=decision,
            confidence=confidence,
            headline=headline,
            rationale=rationale,
            conditions=conditions,
            risks=risks,
            items=items,
        )

        # Step 4: LLM 生成投资备忘录（可选）
        memo = self._draft_memo(
            decision_obj, strategy_name, metrics, factors, extra_context
        )
        decision_obj.memo = memo or ""

        return decision_obj

    def compare_strategies(
        self,
        current: dict,
        proposed: dict,
        current_name: str = "现有策略",
        proposed_name: str = "候选策略",
    ) -> dict:
        """
        横向对比两个策略，给出资本分配建议。

        参数:
            current  / proposed : 各含 metrics + factors + name 字段的字典
            current_name / proposed_name : 展示名称

        返回:
            {
              "recommendation": "keep" | "replace" | "partial",
              "advantage_count": int,          # 候选策略在几项指标上更优
              "headline": str,
              "current_review": FundManagerDecision,
              "proposed_review": FundManagerDecision,
              "memo": str,
            }
        """
        cur_rev = self.review_strategy(
            current.get("metrics", {}),
            factors=current.get("factors"),
            strategy_name=current_name,
        )
        prop_rev = self.review_strategy(
            proposed.get("metrics", {}),
            factors=proposed.get("factors"),
            strategy_name=proposed_name,
        )

        # 比较核心指标
        key_metrics = ["sharpe", "information_ratio", "annualized_return", "calmar_ratio"]
        cur_m = current.get("metrics", {})
        prop_m = proposed.get("metrics", {})

        advantage = 0
        for k in key_metrics:
            cv = cur_m.get(k) or 0
            pv = prop_m.get(k) or 0
            if k in ("max_drawdown_abs", "annualized_vol", "annual_turnover"):
                if pv < cv:
                    advantage += 1
            else:
                if pv > cv:
                    advantage += 1

        if prop_rev.decision == "rejected":
            recommendation = "keep"
            headline = f"保持 {current_name}：候选策略未通过评审"
        elif advantage >= 3 and prop_rev.decision in ("approved", "conditional"):
            recommendation = "replace"
            headline = f"建议切换至 {proposed_name}：{advantage}/{len(key_metrics)} 项核心指标更优"
        elif advantage >= 2:
            recommendation = "partial"
            headline = f"建议部分迁移至 {proposed_name}：小仓位验证后再决定"
        else:
            recommendation = "keep"
            headline = f"保持 {current_name}：候选策略未显著优于现有"

        memo = ""
        llm = self._get_llm()
        if llm:
            memo = self._compare_memo(
                cur_rev, prop_rev, cur_m, prop_m,
                current_name, proposed_name, recommendation
            )

        return {
            "recommendation": recommendation,
            "advantage_count": advantage,
            "headline": headline,
            "current_review": cur_rev.to_dict(),
            "proposed_review": prop_rev.to_dict(),
            "memo": memo,
        }

    def quarterly_review(
        self,
        portfolio_metrics: dict,
        factor_health: dict,
        live_vs_backtest: Optional[dict] = None,
    ) -> str:
        """
        生成季度基金经理述职报告（Markdown）。

        参数:
            portfolio_metrics : 季度内组合绩效指标
            factor_health     : 因子 IC 健康状态摘要
            live_vs_backtest  : 实盘 vs 回测偏差（可选）

        返回:
            Markdown 格式的季度报告字符串
        """
        date_str = datetime.now().strftime("%Y-%m-%d")
        review = self.review_strategy(
            portfolio_metrics, strategy_name="当季组合"
        )

        sections = [
            f"# 季度基金经理报告  {date_str}",
            "",
            "## 执行摘要",
            "",
            f"> **评审结论**：{review.headline}",
            "",
        ]

        # 绩效表格
        sections += ["## 绩效指标", "", "| 指标 | 实际值 | 门槛 | 评级 |", "|------|--------|------|------|"]
        for item in review.items:
            if item.rating == "missing":
                continue
            emoji = {"pass": "✅", "warn": "⚠️", "fail": "❌"}.get(item.rating, "")
            actual_s = f"{item.actual:.4f}" if item.actual is not None else "N/A"
            thresh = item.min_pass or item.target or "—"
            sections.append(f"| {item.label} | {actual_s} | {thresh} | {emoji} |")
        sections.append("")

        # 风险项
        if review.risks:
            sections += ["## 主要风险", ""]
            for r in review.risks:
                sections.append(f"- {r}")
            sections.append("")

        # 条件
        if review.conditions:
            sections += ["## 跟踪条件", ""]
            for c in review.conditions:
                sections.append(f"- [ ] {c}")
            sections.append("")

        # 因子健康
        if factor_health:
            sections += ["## 因子健康摘要", ""]
            healthy = factor_health.get("healthy", [])
            degraded = factor_health.get("degraded", [])
            dead = factor_health.get("dead", [])
            if healthy:
                sections.append(f"- ✅ 健康因子 ({len(healthy)}): {', '.join(healthy[:6])}")
            if degraded:
                sections.append(f"- ⚠️ 衰减因子 ({len(degraded)}): {', '.join(degraded[:4])}")
            if dead:
                sections.append(f"- ❌ 失效因子 ({len(dead)}): {', '.join(dead[:4])}")
            sections.append("")

        # 实盘 vs 回测偏差
        if live_vs_backtest:
            drift = live_vs_backtest.get("cumulative_drift_pct", None)
            if drift is not None:
                icon = "⚠️" if abs(drift) > 3 else "✅"
                sections += [
                    "## 实盘 vs 回测偏差",
                    "",
                    f"- {icon} 累计偏差: {drift:+.2f}%",
                    f"- 主因: {live_vs_backtest.get('main_cause', '未知')}",
                    "",
                ]

        # LLM 备忘录
        if review.memo:
            sections += ["## 基金经理点评（AI 辅助）", "", review.memo, ""]

        sections += [
            "---",
            f"*报告日期: {date_str} | 评审引擎: FundManager v1.0*",
        ]

        return "\n".join(sections)

    # ── 内部方法 ─────────────────────────────────────────────────────────

    def _score_metrics(self, metrics: dict) -> List[ReviewItem]:
        """按 REVIEW_STANDARDS 逐项打分。"""
        items: List[ReviewItem] = []
        for key, std in self._standards.items():
            label = std["label"]
            # max_drawdown 统一取绝对值
            if key == "max_drawdown_abs":
                raw = metrics.get("max_drawdown")
                actual = abs(float(raw)) if raw is not None else None
            else:
                raw = metrics.get(key)
                actual = float(raw) if raw is not None else None

            item = ReviewItem(
                key=key,
                label=label,
                actual=actual,
                min_pass=std.get("min_pass"),
                target=std.get("target"),
            )

            if actual is None:
                item.rating = "missing"
                item.passed = False
                item.note = "数据缺失"
                items.append(item)
                continue

            # 下限检查
            if "min_pass" in std and actual < std["min_pass"]:
                item.rating = "fail"
                item.passed = False
                item.note = f"{actual:.4f} < 门槛 {std['min_pass']}"
            # 上限检查（换手率、回撤等）
            elif "max_pass" in std and actual > std["max_pass"]:
                item.rating = "fail"
                item.passed = False
                item.note = f"{actual:.4f} > 上限 {std['max_pass']}"
            # 达标但未到目标 → 警告
            elif "target" in std:
                target = std["target"]
                if "max_pass" in std:
                    # 越小越好：actual > target 是警告
                    if actual > target:
                        item.rating = "warn"
                        item.note = f"达标但未达目标 {target}"
                    else:
                        item.rating = "pass"
                else:
                    # 越大越好：actual < target 是警告
                    if actual < target:
                        item.rating = "warn"
                        item.note = f"达标但未达目标 {target}"
                    else:
                        item.rating = "pass"
            else:
                item.rating = "pass"

            items.append(item)
        return items

    def _build_rationale(
        self, items: List[ReviewItem], name: str, metrics: dict
    ) -> str:
        """生成规则驱动的评审理由（Markdown）。"""
        lines = [f"### {name} 评审明细", ""]
        for item in items:
            emoji = {"pass": "✅", "warn": "⚠️", "fail": "❌", "missing": "❓"}[item.rating]
            actual_s = f"{item.actual:.4f}" if item.actual is not None else "N/A"
            lines.append(f"- {emoji} **{item.label}**: {actual_s}  {item.note}")
        return "\n".join(lines)

    def _derive_conditions(
        self, warn_items: List[ReviewItem], miss_items: List[ReviewItem], metrics: dict
    ) -> List[str]:
        """从警告项和缺失项推导出附条件清单。"""
        conds: List[str] = []
        for w in warn_items:
            conds.append(f"跟踪 {w.label}（当前 {w.actual:.4f}），下季复评是否达到目标 {w.target}")
        for m in miss_items:
            conds.append(f"补充 {m.label} 数据后再做完整评审")
        return conds

    def _derive_risks(
        self,
        fail_items: List[ReviewItem],
        warn_items: List[ReviewItem],
        metrics: dict,
        factors: Optional[List[str]],
    ) -> List[str]:
        """归纳主要风险点。"""
        risks: List[str] = []
        for f in fail_items:
            risks.append(f"硬性风险 — {f.label} 不达标（实际 {f.actual}, 门槛 {f.min_pass or f.target}）")

        # 换手率 vs 收益 不匹配
        turnover = metrics.get("annual_turnover")
        ret = metrics.get("annualized_return")
        if turnover and ret and turnover > 12 and ret < 0.20:
            risks.append("高换手 + 低收益：每次换仓创造的 Alpha 覆盖不了交易成本")

        # 因子集中度风险
        if factors and len(factors) < 3:
            risks.append(f"因子多样性不足（仅 {len(factors)} 个因子）：单因子失效风险高")

        # 实盘容量
        eff_n = metrics.get("effective_n")
        if eff_n and eff_n < 10:
            risks.append(f"有效持仓数过低（{eff_n:.1f}），集中度风险超标")

        return risks

    def _draft_memo(
        self,
        decision: FundManagerDecision,
        name: str,
        metrics: dict,
        factors: Optional[List[str]],
        extra_context: str,
    ) -> Optional[str]:
        """调用 LLM 生成投资备忘录（Investment Memo）。"""
        llm = self._get_llm()
        if llm is None:
            return None

        # 构造指标摘要
        m_lines = []
        for item in decision.items:
            if item.actual is not None:
                m_lines.append(f"  {item.label}: {item.actual:.4f}")
        metrics_text = "\n".join(m_lines) or "（无有效指标数据）"
        factor_text = "、".join(factors) if factors else "未知"
        risk_text = "\n".join(f"- {r}" for r in decision.risks) or "（无特别风险）"
        decision_text = {
            "approved": "✅ 通过",
            "conditional": "⚠️ 附条件通过",
            "rejected": "❌ 否决",
        }.get(decision.decision, decision.decision)

        prompt = f"""你是一个 A 股量化私募基金的 CIO，正在主持投资委员会对一个候选策略做最终评审。

策略名称：{name}
使用因子：{factor_text}

核心指标：
{metrics_text}

主要风险：
{risk_text}

{f'背景信息：{extra_context}' if extra_context else ''}

评审委员会结论：{decision_text}
置信度：{decision.confidence:.0%}

请写一份简洁的投资备忘录（200 字以内），内容包括：
1. 策略的核心逻辑和竞争优势（1~2 句）
2. 关键风险和保障措施（1~2 句）
3. 资金分配建议：初始配置比例 / 是否需要先小仓位验证

用中文，直接给结论，不要废话。"""

        try:
            return llm.complete(prompt, max_tokens=400)
        except Exception as e:
            logger.warning("FundManager LLM memo 失败: %s", e)
            return None

    def _compare_memo(
        self,
        cur_rev: FundManagerDecision,
        prop_rev: FundManagerDecision,
        cur_m: dict,
        prop_m: dict,
        current_name: str,
        proposed_name: str,
        recommendation: str,
    ) -> str:
        """对比两个策略并生成 LLM 比较备忘录。"""
        llm = self._get_llm()
        if llm is None:
            return ""

        def fmt(m: dict, label: str) -> str:
            keys = ["annualized_return", "sharpe", "information_ratio", "max_drawdown", "calmar_ratio"]
            lines = [f"{label}:"]
            for k in keys:
                v = m.get(k)
                if v is not None:
                    lines.append(f"  {k}: {float(v):.4f}")
            return "\n".join(lines)

        rec_map = {
            "replace": "建议切换至候选策略",
            "partial": "建议小仓位测试候选策略",
            "keep": "建议保持现有策略",
        }

        prompt = f"""你是 A 股量化私募基金 CIO，请对以下两个策略做一段对比点评（150 字以内）：

{fmt(cur_m, current_name)}

{fmt(prop_m, proposed_name)}

委员会建议：{rec_map.get(recommendation, recommendation)}

重点：说清楚为什么做这个决定，以及执行建议（如切换时机、过渡方案）。中文，直接。"""

        try:
            return llm.complete(prompt, max_tokens=300)
        except Exception as e:
            logger.warning("FundManager compare memo 失败: %s", e)
            return ""

    def render_decision_markdown(self, decision: FundManagerDecision, title: str = "") -> str:
        """
        将 FundManagerDecision 渲染为 Markdown 字符串（用于日报/周报/Dashboard）。

        参数:
            decision : FundManagerDecision 实例
            title    : 可选标题

        返回:
            Markdown 字符串
        """
        icon_map = {"approved": "✅", "conditional": "⚠️", "rejected": "❌"}
        icon = icon_map.get(decision.decision, "")
        lines = []
        if title:
            lines += [f"## {title}", ""]
        lines += [
            f"### {icon} 基金经理评审 — {decision.headline}",
            "",
            f"**置信度**: {decision.confidence:.0%}",
            "",
        ]

        lines.append(decision.rationale)
        lines.append("")

        if decision.conditions:
            lines += ["**附加条件**", ""]
            for c in decision.conditions:
                lines.append(f"- [ ] {c}")
            lines.append("")

        if decision.risks:
            lines += ["**风险提示**", ""]
            for r in decision.risks:
                lines.append(f"- ⚠️ {r}")
            lines.append("")

        if decision.memo:
            lines += ["**投资备忘录**", "", decision.memo, ""]

        return "\n".join(lines)


# ══════════════════════════════════════════════════════════════════════════
# 便捷接口（单条调用）
# ══════════════════════════════════════════════════════════════════════════

def review(metrics: dict, **kwargs) -> FundManagerDecision:
    """
    便捷接口：直接评审一组指标。

    参数:
        metrics : 回测指标字典
        **kwargs: 传给 FundManager.review_strategy 的其他参数

    返回:
        FundManagerDecision
    """
    return FundManager().review_strategy(metrics, **kwargs)


if __name__ == "__main__":
    # ── 最小验证 ──────────────────────────────────────────────────────

    # 1. 合格策略
    good = {
        "annualized_return": 0.21,
        "sharpe": 1.35,
        "information_ratio": 0.72,
        "max_drawdown": -0.18,
        "calmar_ratio": 1.17,
        "annualized_vol": 0.16,
        "win_rate": 0.53,
        "icir": 0.65,
        "effective_n": 22,
        "annual_turnover": 9,
        "n_trading_days": 950,
    }

    # 2. 不合格策略
    bad = {
        "annualized_return": 0.09,
        "sharpe": 0.55,
        "information_ratio": 0.28,
        "max_drawdown": -0.42,
        "calmar_ratio": 0.21,
        "annualized_vol": 0.38,
        "win_rate": 0.40,
        "effective_n": 5,
        "n_trading_days": 400,
    }

    fm = FundManager()

    print("=" * 60)
    print("✅ 测试：合格策略")
    d1 = fm.review_strategy(good, factors=["momentum", "bp", "low_vol"], strategy_name="多因子 v8")
    print(f"  决定: {d1.decision} | {d1.headline}")
    print(f"  风险: {d1.risks}")
    print()

    print("=" * 60)
    print("❌ 测试：不合格策略")
    d2 = fm.review_strategy(bad, factors=["momentum"], strategy_name="单因子动量")
    print(f"  决定: {d2.decision} | {d2.headline}")
    print(f"  失败项: {[i.label for i in d2.items if i.rating == 'fail']}")
    print()

    print("=" * 60)
    print("🔀 测试：策略对比")
    comp = fm.compare_strategies(
        {"metrics": bad, "factors": ["momentum"]},
        {"metrics": good, "factors": ["momentum", "bp", "low_vol"]},
        current_name="旧版单因子",
        proposed_name="新版多因子",
    )
    print(f"  建议: {comp['recommendation']} | {comp['headline']}")
    print()

    print("✅ FundManager 验证完成（无 LLM 备忘录，需 claude CLI 才能生成）")
