"""
test_research_planner.py — Phase 7 研究提议层单测

覆盖 pipeline/research_planner.py：
  - 空输入 → no_action 占位
  - factor_decay detector 的 degraded/dead/insufficient_data/healthy 分支
  - risk_alert detector 的 DRAWDOWN_CRITICAL/WARNING + CONCENTRATION_EXCEEDED
  - divergence detector 的阈值切换（中 → 高）+ 方向文案
  - plan_research 去重和优先级排序
  - render_plan_markdown 输出
"""
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from pipeline.research_planner import (
    HIGH_DRIFT_THRESHOLD,
    LIVE_BT_DRIFT_THRESHOLD,
    ResearchQuestion,
    _divergence_questions,
    _factor_decay_questions,
    _risk_alert_questions,
    plan_research,
    render_plan_markdown,
)


# ────────────────────────────────────────────────────────────
# 空输入
# ────────────────────────────────────────────────────────────

class TestEmptyInput:
    def test_all_none_returns_no_action(self):
        qs = plan_research()
        assert len(qs) == 1
        assert qs[0].type == "no_action"
        assert qs[0].priority == "low"
        assert qs[0].proposed_experiment is None

    def test_empty_dicts_return_no_action(self):
        qs = plan_research(factor_health={}, risk_alerts=[], divergence={})
        assert len(qs) == 1
        assert qs[0].id == "no_action"

    def test_only_healthy_factors_returns_no_action(self):
        health = {
            "mom_20": {"status": "healthy", "rolling_ic": 0.04, "t_stat": 3.5, "n_obs": 200},
            "bp": {"status": "healthy", "rolling_ic": 0.03, "t_stat": 3.2, "n_obs": 200},
        }
        qs = plan_research(factor_health=health)
        assert len(qs) == 1
        assert qs[0].type == "no_action"


# ────────────────────────────────────────────────────────────
# _factor_decay_questions
# ────────────────────────────────────────────────────────────

class TestFactorDecayQuestions:
    def test_none_input(self):
        assert _factor_decay_questions(None) == []
        assert _factor_decay_questions({}) == []

    def test_degraded_produces_medium_with_experiment(self):
        health = {
            "mom_20": {"status": "degraded", "rolling_ic": 0.012, "t_stat": 1.2, "n_obs": 80},
        }
        qs = _factor_decay_questions(health)
        assert len(qs) == 1
        q = qs[0]
        assert q.priority == "medium"
        assert q.type == "factor_decay"
        assert q.id == "factor_decay_mom_20"
        assert "mom_20" in q.question
        assert "degraded" in q.rationale
        assert q.proposed_experiment["command"] == "backtest.run"
        assert q.proposed_experiment["params"]["drop_factor"] == "mom_20"

    def test_dead_produces_high_priority(self):
        health = {
            "bp": {"status": "dead", "rolling_ic": 0.001, "t_stat": 0.2, "n_obs": 200},
        }
        qs = _factor_decay_questions(health)
        assert len(qs) == 1
        assert qs[0].priority == "high"
        assert "失效" in qs[0].question or "dead" in qs[0].question.lower()
        assert qs[0].proposed_experiment is not None

    def test_insufficient_data_is_low_without_experiment(self):
        health = {
            "turnover": {"status": "insufficient_data", "rolling_ic": 0.0, "t_stat": 0.0, "n_obs": 5},
        }
        qs = _factor_decay_questions(health)
        assert len(qs) == 1
        q = qs[0]
        assert q.priority == "low"
        assert q.type == "factor_insufficient"
        assert q.proposed_experiment is None

    def test_healthy_and_no_data_are_ignored(self):
        health = {
            "a": {"status": "healthy"},
            "b": {"status": "no_data"},
        }
        qs = _factor_decay_questions(health)
        assert qs == []

    def test_multiple_factors_sorted_by_name(self):
        health = {
            "zeta": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.0, "n_obs": 100},
            "alpha": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},
        }
        qs = _factor_decay_questions(health)
        assert len(qs) == 2
        # sorted 保证 alpha 在 zeta 前
        assert qs[0].id == "factor_decay_alpha"
        assert qs[1].id == "factor_decay_zeta"


# ────────────────────────────────────────────────────────────
# _risk_alert_questions
# ────────────────────────────────────────────────────────────

class TestRiskAlertQuestions:
    def test_none_input(self):
        assert _risk_alert_questions(None) == []
        assert _risk_alert_questions([]) == []

    def test_drawdown_critical_is_high(self):
        alerts = [{"level": "critical", "code": "DRAWDOWN_CRITICAL", "msg": "drawdown -30%"}]
        qs = _risk_alert_questions(alerts)
        assert len(qs) == 1
        assert qs[0].priority == "high"
        assert qs[0].id == "drawdown_critical"
        assert qs[0].proposed_experiment is not None

    def test_drawdown_warning_is_medium(self):
        alerts = [{"level": "warning", "code": "DRAWDOWN_WARNING", "msg": "drawdown -18%"}]
        qs = _risk_alert_questions(alerts)
        assert len(qs) == 1
        assert qs[0].priority == "medium"
        assert qs[0].id == "drawdown_warning"

    def test_concentration_exceeded_uses_symbol_in_id(self):
        alerts = [{
            "level": "warning", "code": "CONCENTRATION_EXCEEDED",
            "msg": "600519 占比 12%", "symbol": "600519",
        }]
        qs = _risk_alert_questions(alerts)
        assert len(qs) == 1
        assert qs[0].id == "concentration_600519"
        assert "600519" in qs[0].question
        assert qs[0].proposed_experiment["params"]["max_weight"] == 0.08

    def test_unknown_code_is_ignored(self):
        alerts = [{"level": "warning", "code": "SECTOR_CONCENTRATION", "msg": "..."}]
        qs = _risk_alert_questions(alerts)
        assert qs == []

    def test_multiple_alerts_all_produced(self):
        alerts = [
            {"level": "critical", "code": "DRAWDOWN_CRITICAL", "msg": "x"},
            {"level": "warning", "code": "CONCENTRATION_EXCEEDED", "msg": "y", "symbol": "000001"},
        ]
        qs = _risk_alert_questions(alerts)
        assert len(qs) == 2


# ────────────────────────────────────────────────────────────
# _divergence_questions
# ────────────────────────────────────────────────────────────

class TestDivergenceQuestions:
    def test_none_or_missing_diff(self):
        assert _divergence_questions(None) == []
        assert _divergence_questions({}) == []
        assert _divergence_questions({"foo": 1}) == []

    def test_below_threshold_ignored(self):
        assert _divergence_questions({"cumulative_diff": 0.005}) == []
        assert _divergence_questions({"cumulative_diff": -0.005}) == []

    def test_medium_diff(self):
        qs = _divergence_questions({"cumulative_diff": LIVE_BT_DRIFT_THRESHOLD})
        assert len(qs) == 1
        assert qs[0].priority == "medium"

    def test_high_diff(self):
        qs = _divergence_questions({"cumulative_diff": HIGH_DRIFT_THRESHOLD})
        assert len(qs) == 1
        assert qs[0].priority == "high"

    def test_negative_direction_text(self):
        qs = _divergence_questions({"cumulative_diff": -0.025})
        assert len(qs) == 1
        assert "少赚" in qs[0].question

    def test_positive_direction_text(self):
        qs = _divergence_questions({"cumulative_diff": 0.025})
        assert len(qs) == 1
        assert "多赚" in qs[0].question


# ────────────────────────────────────────────────────────────
# plan_research 组合和排序
# ────────────────────────────────────────────────────────────

class TestPlanResearch:
    def test_priority_sorting(self):
        health = {
            "mom": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80},  # medium
            "bp": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100},  # high
            "turnover": {"status": "insufficient_data", "n_obs": 5},  # low
        }
        qs = plan_research(factor_health=health)
        assert qs[0].priority == "high"
        assert qs[-1].priority == "low"

    def test_combined_state(self):
        health = {"mom": {"status": "dead", "rolling_ic": 0.0, "t_stat": 0.1, "n_obs": 100}}
        alerts = [{"level": "warning", "code": "DRAWDOWN_WARNING", "msg": "x"}]
        div = {"cumulative_diff": -0.02}
        qs = plan_research(factor_health=health, risk_alerts=alerts, divergence=div)
        assert len(qs) == 3
        # high 的 factor_dead 应该排第一
        assert qs[0].priority == "high"

    def test_dedupe_by_id(self):
        # 同一个 factor id 不应该出现两次（防御）
        health = {"mom": {"status": "degraded", "rolling_ic": 0.01, "t_stat": 1.2, "n_obs": 80}}
        qs = plan_research(factor_health=health)
        ids = [q.id for q in qs]
        assert len(ids) == len(set(ids))


# ────────────────────────────────────────────────────────────
# render_plan_markdown
# ────────────────────────────────────────────────────────────

class TestRenderPlanMarkdown:
    def test_no_action_rendering(self):
        md = render_plan_markdown(plan_research())
        assert "# 研究计划" in md
        assert "no_action" in md
        assert "🟢" in md

    def test_high_priority_badge(self):
        q = ResearchQuestion(
            id="test", type="factor_decay", priority="high",
            question="q?", rationale="r",
            proposed_experiment={"command": "backtest.run", "params": {"drop_factor": "mom"}},
        )
        md = render_plan_markdown([q])
        assert "🔴" in md
        assert "drop_factor=mom" in md

    def test_renders_experiment_absence(self):
        q = ResearchQuestion(
            id="x", type="factor_insufficient", priority="low",
            question="q?", rationale="r", proposed_experiment=None,
        )
        md = render_plan_markdown([q])
        assert "暂无可执行" in md
