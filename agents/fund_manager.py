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


    def build_fund_playbook(
        self,
        team_size: int = 2,
        current_phase: str = "paper_trading",
        target_aum_cny: float = 5e7,
        timeline_years: int = 3,
    ) -> str:
        """
        生成从模拟盘到量化私募的完整运营手册（Markdown）。

        参数:
            team_size      : 当前团队人数
            current_phase  : 当前阶段标识（"paper_trading" / "personal_account" / "raising"）
            target_aum_cny : 目标 AUM（人民币），默认 5000 万
            timeline_years : 计划几年内完成首次募资

        返回:
            Markdown 格式的运营手册
        """
        # 从 quant_mentor 借用知识常量（避免重复定义）
        try:
            from agents.quant_mentor import CHINA_FUND_SETUP, COMMON_MISTAKES, SYSTEM_ARCHITECTURE
        except ImportError:
            return "错误：无法导入 quant_mentor 知识常量，请确认 agents/quant_mentor.py 存在"

        aum_wan = int(target_aum_cny / 10000)
        lines = [
            "# 量化私募从模拟盘到首只基金产品 — 运营手册",
            "",
            f"> 适用场景：{team_size} 人团队，当前阶段：{current_phase}，"
            f"目标 AUM：{aum_wan} 万，计划 {timeline_years} 年内完成首次募资",
            "",
        ]

        # ── 阶段路线图 ────────────────────────────────────────────────
        phase_map = {
            "paper_trading":      "phase_1_prove_alpha",
            "personal_account":   "phase_2_personal_account",
            "company_setup":      "phase_3_incorporation",
            "amac":               "phase_4_amac_registration",
            "raising":            "phase_5_product_filing",
            "operating":          "phase_6_operations",
        }
        current_key = phase_map.get(current_phase, "phase_1_prove_alpha")
        phase_keys = list(phase_map.values())
        current_idx = phase_keys.index(current_key) if current_key in phase_keys else 0

        for i, key in enumerate(phase_keys):
            if key not in CHINA_FUND_SETUP:
                continue
            info = CHINA_FUND_SETUP[key]
            status = "▶ 当前" if i == current_idx else ("✅ 完成" if i < current_idx else "○ 待做")
            lines += [
                f"## {status}  {info.get('name', key)}",
                "",
            ]
            if "gate" in info:
                lines += [f"> **准入门槛**：{info['gate']}", ""]
            if "why" in info:
                lines += [f"**为什么重要**：{info['why']}", ""]
            if "actions" in info:
                lines += ["**行动清单**：", ""]
                acts_val = info["actions"]
                if isinstance(acts_val, dict):
                    for owner, acts in acts_val.items():
                        lines.append(f"*{owner}*:")
                        for a in acts:
                            lines.append(f"  - [ ] {a}")
                else:
                    for a in acts_val:
                        lines.append(f"  - [ ] {a}")
                lines.append("")
            if "requirements" in info and isinstance(info["requirements"], list):
                lines += ["**核心要求**：", ""]
                for r in info["requirements"]:
                    lines.append(f"- {r}")
                lines.append("")
            if "deliverables" in info:
                lines += ["**交付物**：", ""]
                for d in info["deliverables"]:
                    lines.append(f"- {d}")
                lines.append("")
            if "cost" in info:
                lines += [f"**费用估算**：{info['cost']}", ""]
            if "timeline" in info:
                lines += [f"**耗时**：{info['timeline']}", ""]
            if "blocker" in info:
                lines += [f"⚠️ **注意**：{info['blocker']}", ""]
            lines.append("")

        # ── AUM 目标和容量约束 ────────────────────────────────────────
        lines += [
            "---",
            "",
            "## 容量约束与 AUM 规划",
            "",
            f"目标 AUM：**{aum_wan} 万**",
            "",
            "| AUM 规模 | 典型策略类型 | 换手频率 | 容量注意事项 |",
            "|----------|-------------|----------|--------------|",
            "| < 3000 万 | 小盘量化选股 | 月度/双周 | 单笔 < 日均成交量 2% |",
            "| 3000-1亿 | 中盘 + 小盘混合 | 双周/周 | 需控制冲击，测试容量上限 |",
            "| 1-5亿 | 中大盘为主 | 周度 | Barra 因子中性化，多因子分散 |",
            "| > 5亿 | 大盘 + 指增 | 日度/周度 | 需 QP 优化器，因子暴露精细控制 |",
            "",
            "> **容量估算方法**：找出策略最小流动性股票，"
            "计算「单日最大可建仓金额 = 该股日均成交量 × 5%」，"
            "汇总得到策略容量上限",
            "",
        ]

        # ── 服务商选择 ────────────────────────────────────────────────
        if "phase_5_product_filing" in CHINA_FUND_SETUP:
            sp = CHINA_FUND_SETUP["phase_5_product_filing"].get("service_providers", {})
            if sp:
                lines += [
                    "## 关键服务商",
                    "",
                    "| 角色 | 功能 | 费率参考 |",
                    "|------|------|----------|",
                ]
                for role, desc in sp.items():
                    parts = desc.split("；")
                    fee = parts[-1].strip() if len(parts) > 1 else "—"
                    func = parts[0].strip()[:40]
                    lines.append(f"| {role} | {func} | {fee} |")
                lines.append("")

        # ── 运营成本估算 ──────────────────────────────────────────────
        lines += [
            "## 年度运营成本估算（首只产品，~1 亿 AUM）",
            "",
            "| 项目 | 年费估算 | 备注 |",
            "|------|----------|------|",
            "| 律所（合规顾问）| 5-15 万 | 中基协登记、合同起草、监管事务 |",
            "| 托管银行 | 10-30 万 | 费率 0.1-0.3%/年，按 AUM |",
            "| 外包服务机构（TA）| 10-20 万 | 估值核算、投资者服务 |",
            "| 年度审计 | 3-8 万 | 会计师事务所 |",
            "| 数据（Wind）| 10-30 万 | 实时行情 + 财务数据 |",
            "| 服务器/云计算 | 2-5 万 | 信号生成、风控、监控 |",
            "| **合计** | **40-110 万/年** | 不含人员和管理费收入 |",
            "",
            f"> 盈亏平衡点：管理费 1.5%/年 × AUM。"
            f"若固定成本 60 万/年，AUM 需达到 **{int(60/0.015/10000)} 万** 才能覆盖运营成本。",
            "",
        ]

        # ── 常见坑（仅 high/critical）────────────────────────────────
        lines += [
            "## 高危风险清单",
            "",
        ]
        for m in COMMON_MISTAKES:
            if m["severity"] in ("critical", "high"):
                icon = "🔴" if m["severity"] == "critical" else "🟠"
                lines.append(f"- {icon} **{m['name']}**")
                lines.append(f"  - {m['description']}")
                if m.get("advice"):
                    lines.append(f"  - 建议：{m['advice']}")
        lines.append("")

        # ── LLM 个性化点评 ────────────────────────────────────────────
        llm = self._get_llm()
        if llm:
            try:
                prompt = (
                    f"你是一个量化私募基金创始人兼 CIO，经历过从零到十亿 AUM 的全程。\n\n"
                    f"团队情况：{team_size} 人，当前阶段：{current_phase}，"
                    f"目标 AUM：{aum_wan} 万，计划 {timeline_years} 年完成首次募资。\n\n"
                    "请用 200 字给这个团队写一段个性化的战略建议："
                    "在这个阶段，最重要的 1 件事是什么？最大的风险是什么？"
                    "直接讲，不要废话。中文。"
                )
                commentary = llm.complete(prompt, max_tokens=350)
                lines += ["## CIO 战略建议（AI 生成）", "", commentary, ""]
            except Exception as e:
                _log.warning("build_fund_playbook LLM 失败: %s", e)

        lines += [
            "---",
            f"*生成时间：{datetime.now().strftime('%Y-%m-%d')} | "
            "来源：FundManager.build_fund_playbook() + QuantMentor 知识库*",
        ]
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
