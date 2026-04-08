"""
pipeline/research_planner.py — Phase 7 AI 研究助理的提议层

把系统当前状态（factor_health / risk_alerts / live-vs-backtest divergence）
转成一组结构化的 ResearchQuestion，供下游 experiment_runner 拉起 backtest。

设计原则：
  - **纯函数**：不读盘不写盘，输入 dict → 输出 dataclass list，便于单测
  - **规则驱动，不是 LLM**：每条 question 的 rationale 指向具体数据证据，
    未来若要接 LLM 也应该是做措辞润色或次序建议，不应让模型决定是否跑 backtest
  - **优先级敏感**：high > medium > low，low 只占提示位（如 insufficient_data）
  - **可 dedupe**：detector 之间可能对同一因子各自产出 question，
    plan_research 按 id 去重

问题类型：
  - factor_decay          : 因子 IC 显著下降 / 消失
  - factor_insufficient   : 样本不足无法判断（低优，纯提示）
  - drawdown_spike        : 回撤超阈值
  - concentration         : 单股/行业集中度超限
  - live_vs_bt_drift      : 实盘和回测累计偏差
  - no_action             : 一切健康时的占位
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Optional


# ══════════════════════════════════════════════════════════════
# 常量 —— 集中在文件顶部，单测可 monkeypatch
# ══════════════════════════════════════════════════════════════

# factor_monitor 里 t_stat < 这个值就算"不显著"，和 degraded 合并成 medium 级
FACTOR_DECAY_T_STAT_THRESHOLD = 1.5

# live vs backtest 累计偏差门槛：>=1% 中等，>=3% 高
LIVE_BT_DRIFT_THRESHOLD = 0.01
HIGH_DRIFT_THRESHOLD = 0.03

# 优先级权重，数字越小越紧急
_PRIORITY_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class ResearchQuestion:
    """
    一条研究问题。

    - id                  : 稳定标识符，用于 dedupe 和 experiment_store 回指
    - type                : factor_decay / factor_insufficient /
                            drawdown_spike / concentration /
                            live_vs_bt_drift / no_action
    - priority            : high / medium / low
    - question            : 人类可读的一句话
    - rationale           : 支持这个 question 的数据证据
    - proposed_experiment : {"command": "backtest.run", "params": {...}}
                            为 None 时 runner 会落 skipped
    - source              : 额外溯源字段，供 summarizer/CLI 展示
    """
    id: str
    type: str
    priority: str
    question: str
    rationale: str
    proposed_experiment: Optional[dict] = None
    source: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# ══════════════════════════════════════════════════════════════
# 私有 detector —— 每个独立，便于单测
# ══════════════════════════════════════════════════════════════

def _factor_decay_questions(factor_health: Optional[dict]) -> list[ResearchQuestion]:
    """
    factor_health 结构见 pipeline.factor_monitor.factor_health_report：
        {factor_name: {rolling_ic, n_obs, t_stat, status}}
    status ∈ {healthy, degraded, dead, insufficient_data, no_data}
    """
    if not factor_health:
        return []

    out: list[ResearchQuestion] = []
    # sorted 保证 factor 顺序稳定，测试可以锁 list index
    for name, info in sorted(factor_health.items()):
        status = (info or {}).get("status")
        ic = (info or {}).get("rolling_ic")
        t_stat = (info or {}).get("t_stat")
        n_obs = (info or {}).get("n_obs")

        if status == "degraded":
            out.append(ResearchQuestion(
                id=f"factor_decay_{name}",
                type="factor_decay",
                priority="medium",
                question=f"因子 {name} 是否已经进入长期降级？是否该替换？",
                rationale=(
                    f"rolling_ic={ic}, t_stat={t_stat}, n_obs={n_obs}; "
                    f"status=degraded，IC 均值低但 t-stat 尚有残留"
                ),
                proposed_experiment={
                    "command": "backtest.run",
                    "params": {"drop_factor": name},
                },
                source={"factor": name, "status": status},
            ))
        elif status == "dead":
            out.append(ResearchQuestion(
                id=f"factor_decay_{name}",
                type="factor_decay",
                priority="high",
                question=f"因子 {name} 已失效（dead），建议立即移除并回测对照",
                rationale=(
                    f"rolling_ic={ic}, t_stat={t_stat}, n_obs={n_obs}; "
                    f"status=dead，IC 均值接近 0 且无显著性"
                ),
                proposed_experiment={
                    "command": "backtest.run",
                    "params": {"drop_factor": name},
                },
                source={"factor": name, "status": status},
            ))
        elif status == "insufficient_data":
            # 低优提醒，不配 proposed_experiment —— 没东西可跑
            out.append(ResearchQuestion(
                id=f"factor_insufficient_{name}",
                type="factor_insufficient",
                priority="low",
                question=f"因子 {name} 样本不足，等更多数据再复审",
                rationale=f"n_obs={n_obs} 低于判定门槛",
                proposed_experiment=None,
                source={"factor": name, "status": status},
            ))
        # healthy / no_data 不产出问题
    return out


def _risk_alert_questions(risk_alerts: Optional[list]) -> list[ResearchQuestion]:
    """
    risk_alerts 结构见 live.risk_monitor.check_risk_alerts：
        [{level, code, msg, symbol, as_of_date}, ...]
    只关心 code 中的 DRAWDOWN_CRITICAL / DRAWDOWN_WARNING / CONCENTRATION_EXCEEDED。
    """
    if not risk_alerts:
        return []
    out: list[ResearchQuestion] = []
    for alert in risk_alerts:
        code = alert.get("code")
        msg = alert.get("msg", "")
        symbol = alert.get("symbol") or ""

        if code == "DRAWDOWN_CRITICAL":
            out.append(ResearchQuestion(
                id="drawdown_critical",
                type="drawdown_spike",
                priority="high",
                question="组合回撤达到 critical 阈值，是否需要降低仓位或加入止损？",
                rationale=f"risk_monitor: {msg}",
                proposed_experiment={
                    "command": "backtest.run",
                    "params": {"stop_loss_pct": 0.08},
                },
                source={"code": code, "msg": msg},
            ))
        elif code == "DRAWDOWN_WARNING":
            out.append(ResearchQuestion(
                id="drawdown_warning",
                type="drawdown_spike",
                priority="medium",
                question="组合回撤进入警戒区，建议做一次带止损的对照回测",
                rationale=f"risk_monitor: {msg}",
                proposed_experiment={
                    "command": "backtest.run",
                    "params": {"stop_loss_pct": 0.10},
                },
                source={"code": code, "msg": msg},
            ))
        elif code == "CONCENTRATION_EXCEEDED":
            out.append(ResearchQuestion(
                id=f"concentration_{symbol or 'portfolio'}",
                type="concentration",
                priority="medium",
                question=(
                    f"{symbol or '组合'} 集中度超限，是否应收紧单票 max_weight？"
                ),
                rationale=f"risk_monitor: {msg}",
                proposed_experiment={
                    "command": "backtest.run",
                    "params": {"max_weight": 0.08},
                },
                source={"code": code, "msg": msg, "symbol": symbol},
            ))
    return out


def _divergence_questions(divergence: Optional[dict]) -> list[ResearchQuestion]:
    """
    divergence 结构见 pipeline.live_vs_backtest.compute_divergence：
        {"cumulative_diff": float, ...}
    cumulative_diff > 0 → 实盘多赚；< 0 → 少赚
    """
    if not divergence:
        return []
    diff = divergence.get("cumulative_diff")
    if diff is None:
        return []

    abs_diff = abs(diff)
    if abs_diff < LIVE_BT_DRIFT_THRESHOLD:
        return []

    direction = "少赚" if diff < 0 else "多赚"
    priority = "high" if abs_diff >= HIGH_DRIFT_THRESHOLD else "medium"
    return [ResearchQuestion(
        id="live_vs_bt_drift",
        type="live_vs_bt_drift",
        priority=priority,
        question=(
            f"实盘相比回测累计{direction} {abs_diff:.2%}，"
            f"是否是滑点 / 成本 / 信号延迟？"
        ),
        rationale=(
            f"compute_divergence: cumulative_diff={diff:+.2%}, "
            f"超过阈值 {LIVE_BT_DRIFT_THRESHOLD:.2%}"
        ),
        proposed_experiment={
            "command": "backtest.run",
            "params": {"commission": 0.0025, "slippage": 0.001},
        },
        source={"cumulative_diff": diff},
    )]


# ══════════════════════════════════════════════════════════════
# 公共入口
# ══════════════════════════════════════════════════════════════

def plan_research(
    factor_health: Optional[dict] = None,
    risk_alerts: Optional[list] = None,
    divergence: Optional[dict] = None,
) -> list[ResearchQuestion]:
    """
    综合三类系统状态，产出优先级排序后的 ResearchQuestion 列表。

    - 空输入或系统健康 → 返回 [no_action 占位]
    - 按 id 去重（同一因子的 decay/insufficient 不会重复）
    - 按 priority (high→medium→low) 排序，同级按 id 字母序保持稳定
    """
    questions: list[ResearchQuestion] = []
    questions.extend(_factor_decay_questions(factor_health))
    questions.extend(_risk_alert_questions(risk_alerts))
    questions.extend(_divergence_questions(divergence))

    # 按 id 去重，保留首次出现
    seen: set[str] = set()
    deduped: list[ResearchQuestion] = []
    for q in questions:
        if q.id in seen:
            continue
        seen.add(q.id)
        deduped.append(q)

    if not deduped:
        return [ResearchQuestion(
            id="no_action",
            type="no_action",
            priority="low",
            question="系统健康，本轮无需新实验",
            rationale="factor_health / risk_alerts / divergence 全部未触发阈值",
            proposed_experiment=None,
        )]

    deduped.sort(key=lambda q: (_PRIORITY_ORDER.get(q.priority, 9), q.id))
    return deduped


def render_plan_markdown(questions: list[ResearchQuestion]) -> str:
    """把 plan 渲染成 markdown，供 CLI propose 打印。"""
    if not questions:
        return "# 研究计划\n\n_空_\n"

    badge = {"high": "🔴", "medium": "🟡", "low": "🟢"}
    lines: list[str] = ["# 研究计划", ""]
    lines.append(f"**共 {len(questions)} 条 question**")
    lines.append("")
    for i, q in enumerate(questions, 1):
        icon = badge.get(q.priority, "⚪")
        lines.append(f"## {i}. {icon} `{q.id}` ({q.type})")
        lines.append("")
        lines.append(f"- **question**: {q.question}")
        lines.append(f"- **rationale**: {q.rationale}")
        if q.proposed_experiment:
            params = q.proposed_experiment.get("params") or {}
            params_str = ", ".join(f"{k}={v}" for k, v in params.items()) or "—"
            lines.append(
                f"- **experiment**: `{q.proposed_experiment.get('command')}` "
                f"({params_str})"
            )
        else:
            lines.append("- **experiment**: _暂无可执行实验_")
        lines.append("")
    return "\n".join(lines)
